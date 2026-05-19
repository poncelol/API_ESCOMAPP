import json
import os
from urllib.parse import urlparse
from io import BytesIO

import pandas as pd
import psycopg2
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

# ── Sentry ────────────────────────────────────────────────────────────────────

sentry_sdk.init(
    dsn="https://58591f0755034a75b3a814badcacfa84@o4511414713516032.ingest.us.sentry.io/4511414725115904",
    send_default_pii=True,                  # captura IP y headers del celular
    traces_sample_rate=1.0,                 # registra el 100% de las transacciones
    profiles_sample_rate=1.0,              # perfila rendimiento de cada endpoint
    integrations=[
        StarletteIntegration(transaction_style="endpoint"),
        FastApiIntegration(transaction_style="endpoint"),
    ],
    environment=os.environ.get("RENDER_SERVICE_NAME", "local"),  # "local" si no está en Render
)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Base de datos ─────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL no está definida en Render")

DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgres://", 1)

_url = urlparse(DATABASE_URL)
conn = psycopg2.connect(
    dbname=_url.path[1:],
    user=_url.username,
    password=_url.password,
    host=_url.hostname,
    port=_url.port or 5432,
    sslmode="require",
)


# ── Utilidades ────────────────────────────────────────────────────────────────

def construir_geojson(nombre_tabla: str, tipo: str = None) -> dict:
    cur = conn.cursor()
    if tipo:
        cur.execute(
            f"SELECT ogc_fid, codigo, tipo, nivel, ST_AsGeoJSON(wkb_geometry) "
            f"FROM {nombre_tabla} WHERE tipo = %s;",
            (tipo,),
        )
    else:
        cur.execute(
            f"SELECT ogc_fid, codigo, tipo, nivel, ST_AsGeoJSON(wkb_geometry) "
            f"FROM {nombre_tabla};"
        )

    features = [
        {
            "type": "Feature",
            "properties": {
                "ogc_fid": ogc_fid,
                "codigo": codigo,
                "tipo": tipo,
                "nivel": nivel,
            },
            "geometry": json.loads(geom),
        }
        for ogc_fid, codigo, tipo, nivel, geom in cur.fetchall()
    ]
    return {"type": "FeatureCollection", "features": features}


def construir_geojson_nivel0() -> dict:
    """Nivel 0: tabla sin columnas codigo/tipo/nivel, solo geometría de fondo."""
    cur = conn.cursor()
    cur.execute("SELECT ogc_fid, ST_AsGeoJSON(wkb_geometry) FROM nivel0;")
    features = [
        {
            "type": "Feature",
            "properties": {"ogc_fid": ogc_fid},
            "geometry": json.loads(geom),
        }
        for ogc_fid, geom in cur.fetchall()
    ]
    return {"type": "FeatureCollection", "features": features}


# ── Endpoints: geometría ──────────────────────────────────────────────────────

@app.get("/Nivel0")
def nivel0():
    return construir_geojson_nivel0()


@app.get("/Nivel1")
def nivel1(tipo: str = None):
    return construir_geojson("nivel1", tipo)


@app.get("/Nivel2")
def nivel2(tipo: str = None):
    return construir_geojson("nivel2", tipo)


@app.get("/Nivel3")
def nivel3(tipo: str = None):
    return construir_geojson("nivel3", tipo)


@app.get("/Niveles")
def obtener_niveles():
    return {"niveles": [1, 2, 3]}


@app.get("/Tipos")
def obtener_tipos():
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT tipo FROM nivel1
        UNION SELECT DISTINCT tipo FROM nivel2
        UNION SELECT DISTINCT tipo FROM nivel3
        ORDER BY tipo;
    """)
    return {"tipos": [row[0] for row in cur.fetchall() if row[0] is not None]}


# ── Endpoints: horarios ───────────────────────────────────────────────────────

@app.post("/subir_excel")
async def subir_excel(file: UploadFile = File(...)):
    cur = conn.cursor()
    try:
        contenido = await file.read()
        df = pd.read_excel(BytesIO(contenido), engine="openpyxl")
        df.columns = df.columns.str.strip()

        columnas_requeridas = ["Profesor", "Día", "Hora Entrada", "Hora Salida", "Materia", "Salón"]
        for col in columnas_requeridas:
            if col not in df.columns:
                return {"error": f"Falta la columna: {col}"}

        cur.execute("TRUNCATE TABLE horarios;")
        conn.commit()

        datos_validos = []
        errores = []

        for index, row in df.iterrows():
            fila_error = []
            try:
                profesor = str(row["Profesor"]).strip()
                dia      = str(row["Día"]).strip().lower()
                materia  = str(row["Materia"]).strip()
                salon    = str(row["Salón"]).strip()

                if not profesor: fila_error.append("Profesor vacío")
                if not dia:      fila_error.append("Día vacío")
                if not materia:  fila_error.append("Materia vacía")
                if not salon:    fila_error.append("Salón vacío")

                hora_entrada = pd.to_datetime(str(row["Hora Entrada"]).strip(), format="%H:%M", errors="coerce")
                hora_salida  = pd.to_datetime(str(row["Hora Salida"]).strip(),  format="%H:%M", errors="coerce")

                if pd.isna(hora_entrada): fila_error.append(f"Hora Entrada inválida: {row['Hora Entrada']}")
                if pd.isna(hora_salida):  fila_error.append(f"Hora Salida inválida: {row['Hora Salida']}")

                if fila_error:
                    errores.append({"fila": index + 2, "datos": row.to_dict(), "errores": fila_error})
                    continue

                datos_validos.append((profesor, dia, hora_entrada.time(), hora_salida.time(), materia, salon))

            except Exception as e:
                errores.append({"fila": index + 2, "datos": row.to_dict(), "errores": [str(e)]})

        if datos_validos:
            cur.executemany(
                "INSERT INTO horarios (profesor, dia, hora_entrada, hora_salida, materia, salon) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                datos_validos,
            )
            conn.commit()

        return {
            "mensaje": "Proceso de importación finalizado",
            "insertados": len(datos_validos),
            "errores": len(errores),
            "detalle_errores": errores,
        }

    except Exception as e:
        conn.rollback()
        sentry_sdk.capture_exception(e)   # ← reporta el error a Sentry manualmente
        return {"error": "Error general en importación", "detalle": str(e)}
    finally:
        cur.close()


@app.get("/profesores")
def obtener_profesores():
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT profesor FROM horarios ORDER BY profesor;")
        return {"profesores": [row[0] for row in cur.fetchall()]}
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return {"error": str(e)}


@app.get("/horario")
def consultar_horario(profesor: str, salon: str, dia: str, hora: str):
    cur = conn.cursor()
    cur.execute("""
        SELECT materia, hora_entrada, hora_salida
        FROM horarios
        WHERE profesor = %s
          AND salon = %s
          AND dia = %s
          AND %s::time BETWEEN hora_entrada AND hora_salida;
    """, (profesor, salon, dia, hora))

    fila = cur.fetchone()
    if fila:
        materia, entrada, salida = fila
        return {
            "disponible": True,
            "profesor": profesor,
            "materia": materia,
            "entrada": str(entrada),
            "salida": str(salida),
        }
    return {"disponible": False, "profesor": profesor, "mensaje": "No está en este salón en esta hora"}


@app.get("/ultimo_salon_profesor")
def ultimo_salon_profesor(profesor: str):
    cur = conn.cursor()

    cur.execute("""
        SELECT profesor, dia, hora_entrada, hora_salida, materia, salon
        FROM horarios
        WHERE profesor = %s
        ORDER BY hora_salida DESC
        LIMIT 1;
    """, (profesor,))

    fila = cur.fetchone()
    if not fila:
        return {"error": "No se encontró horario para este profesor"}

    profesor_db, dia, entrada, salida, materia, salon = fila

    nivel = None
    for n in [1, 2, 3]:
        cur.execute(
            f"SELECT 1 FROM nivel{n} WHERE codigo = %s LIMIT 1;",
            (salon,)
        )
        if cur.fetchone():
            nivel = n
            break

    return {
        "profesor": profesor_db,
        "dia": dia,
        "materia": materia,
        "hora_entrada": str(entrada),
        "hora_salida": str(salida),
        "salon": salon,
        "nivel": nivel,
    }

@app.get("/test-sentry")
def test_sentry():
    division = 1 / 0   # error intencional
    return {"ok": True}

