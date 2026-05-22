import json
import os
import unicodedata
from urllib.parse import urlparse
from io import BytesIO

import pandas as pd
import psycopg2
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# Base de datos
# ─────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise Exception("DATABASE_URL no está definida")

DATABASE_URL = DATABASE_URL.replace(
    "postgresql://",
    "postgres://",
    1
)

_url = urlparse(DATABASE_URL)

conn = psycopg2.connect(
    dbname=_url.path[1:],
    user=_url.username,
    password=_url.password,
    host=_url.hostname,
    port=_url.port or 5432,
    sslmode="require",
)

# ─────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────

def normalizar_texto(texto: str) -> str:

    texto = texto.lower().strip()

    texto = ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )

    equivalencias = {
        "miercoles": "miércoles",
        "sabado": "sábado"
    }

    return equivalencias.get(texto, texto)


def construir_geojson(nombre_tabla: str, tipo: str = None):

    cur = conn.cursor()

    if tipo:

        cur.execute(
            f"""
            SELECT
                ogc_fid,
                codigo,
                tipo,
                nivel,
                ST_AsGeoJSON(wkb_geometry)
            FROM {nombre_tabla}
            WHERE tipo = %s;
            """,
            (tipo,)
        )

    else:

        cur.execute(
            f"""
            SELECT
                ogc_fid,
                codigo,
                tipo,
                nivel,
                ST_AsGeoJSON(wkb_geometry)
            FROM {nombre_tabla};
            """
        )

    features = []

    for ogc_fid, codigo, tipo, nivel, geom in cur.fetchall():

        features.append({
            "type": "Feature",
            "properties": {
                "ogc_fid": ogc_fid,
                "codigo": str(codigo),
                "tipo": tipo,
                "nivel": nivel
            },
            "geometry": json.loads(geom)
        })

    cur.close()

    return {
        "type": "FeatureCollection",
        "features": features
    }


def construir_geojson_nivel0():

    cur = conn.cursor()

    cur.execute("""
        SELECT
            ogc_fid,
            ST_AsGeoJSON(wkb_geometry)
        FROM nivel0;
    """)

    features = []

    for ogc_fid, geom in cur.fetchall():

        features.append({
            "type": "Feature",
            "properties": {
                "ogc_fid": ogc_fid
            },
            "geometry": json.loads(geom)
        })

    cur.close()

    return {
        "type": "FeatureCollection",
        "features": features
    }

# ─────────────────────────────────────────────────────────────
# Geometría
# ─────────────────────────────────────────────────────────────

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
        UNION
        SELECT DISTINCT tipo FROM nivel2
        UNION
        SELECT DISTINCT tipo FROM nivel3
        ORDER BY tipo;
    """)

    tipos = [
        row[0]
        for row in cur.fetchall()
        if row[0] is not None
    ]

    cur.close()

    return {"tipos": tipos}

# ─────────────────────────────────────────────────────────────
# Excel horarios
# ─────────────────────────────────────────────────────────────

@app.post("/subir_excel")
async def subir_excel(file: UploadFile = File(...)):

    cur = conn.cursor()

    try:

        contenido = await file.read()

        df = pd.read_excel(
            BytesIO(contenido),
            engine="openpyxl"
        )

        df.columns = df.columns.str.strip()

        columnas = [
            "Profesor",
            "Día",
            "Hora Entrada",
            "Hora Salida",
            "Materia",
            "Salón"
        ]

        for col in columnas:

            if col not in df.columns:
                return {"error": f"Falta columna: {col}"}

        cur.execute("TRUNCATE TABLE horarios;")
        conn.commit()

        datos = []

        for _, row in df.iterrows():

            profesor = str(row["Profesor"]).strip()

            dia = normalizar_texto(
                str(row["Día"]).strip()
            )

            materia = str(row["Materia"]).strip()

            salon = str(row["Salón"]).strip()

            entrada = pd.to_datetime(
                str(row["Hora Entrada"]).strip(),
                format="%H:%M",
                errors="coerce"
            )

            salida = pd.to_datetime(
                str(row["Hora Salida"]).strip(),
                format="%H:%M",
                errors="coerce"
            )

            if (
                pd.isna(entrada)
                or pd.isna(salida)
            ):
                continue

            datos.append((
                profesor,
                dia,
                entrada.time(),
                salida.time(),
                materia,
                salon
            ))

        cur.executemany("""
            INSERT INTO horarios (
                profesor,
                dia,
                hora_entrada,
                hora_salida,
                materia,
                salon
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, datos)

        conn.commit()

        return {
            "mensaje": "Horarios cargados",
            "insertados": len(datos)
        }

    except Exception as e:

        conn.rollback()

        return {
            "error": str(e)
        }

    finally:
        cur.close()

# ─────────────────────────────────────────────────────────────
# Profesores
# ─────────────────────────────────────────────────────────────

@app.get("/profesores")
def obtener_profesores():

    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT profesor
        FROM horarios
        ORDER BY profesor;
    """)

    profesores = [
        row[0]
        for row in cur.fetchall()
    ]

    cur.close()

    return {"profesores": profesores}

# ─────────────────────────────────────────────────────────────
# Horario actual
# ─────────────────────────────────────────────────────────────

@app.get("/horario")
def consultar_horario(
    profesor: str,
    salon: str,
    dia: str,
    hora: str
):

    dia = normalizar_texto(dia)

    print(f"[DEBUG] dia recibido: {dia}")
    print(f"[DEBUG] hora: {hora}")

    cur = conn.cursor()

    cur.execute("""
        SELECT
            materia,
            hora_entrada,
            hora_salida
        FROM horarios
        WHERE profesor = %s
          AND salon = %s
          AND dia = %s
          AND %s::time BETWEEN hora_entrada AND hora_salida
        ORDER BY hora_entrada ASC
        LIMIT 1;
    """, (
        profesor,
        salon,
        dia,
        hora
    ))

    fila = cur.fetchone()

    cur.close()

    if fila:

        materia, entrada, salida = fila

        return {
            "disponible": True,
            "profesor": profesor,
            "materia": materia,
            "entrada": str(entrada),
            "salida": str(salida)
        }

    return {
        "disponible": False,
        "profesor": profesor,
        "mensaje": "No está en este salón"
    }

# ─────────────────────────────────────────────────────────────
# Último salón profesor
# ─────────────────────────────────────────────────────────────

@app.get("/ultimo_salon_profesor")
def ultimo_salon_profesor(
    profesor: str,
    dia: str,
    hora: str
):

    cur = conn.cursor()

    dia_actual = normalizar_texto(dia)
    hora_actual = hora

    dias_es = [
        "lunes",
        "martes",
        "miércoles",
        "jueves",
        "viernes",
        "sábado",
        "domingo"
    ]

    print(f"[DEBUG] profesor={profesor}")
    print(f"[DEBUG] dia_actual={dia_actual}")
    print(f"[DEBUG] hora_actual={hora_actual}")

    # ─────────────────────────────────────────
    # Clase actual
    # ─────────────────────────────────────────

    cur.execute("""
        SELECT
            profesor,
            dia,
            hora_entrada,
            hora_salida,
            materia,
            salon
        FROM horarios
        WHERE profesor = %s
          AND dia = %s
          AND %s::time BETWEEN hora_entrada AND hora_salida
        ORDER BY hora_entrada ASC
        LIMIT 1;
    """, (
        profesor,
        dia_actual,
        hora_actual
    ))

    fila = cur.fetchone()

    print(f"[DEBUG] paso1: {fila}")

    # ─────────────────────────────────────────
    # Próxima clase del día
    # ─────────────────────────────────────────

    if not fila:

        cur.execute("""
            SELECT
                profesor,
                dia,
                hora_entrada,
                hora_salida,
                materia,
                salon
            FROM horarios
            WHERE profesor = %s
              AND dia = %s
              AND hora_entrada > %s::time
            ORDER BY hora_entrada ASC
            LIMIT 1;
        """, (
            profesor,
            dia_actual,
            hora_actual
        ))

        fila = cur.fetchone()

        print(f"[DEBUG] paso2: {fila}")

    # ─────────────────────────────────────────
    # Buscar próximos días
    # ─────────────────────────────────────────

    if not fila and dia_actual in dias_es:

        indice = dias_es.index(dia_actual)

        for siguiente in dias_es[indice + 1:]:

            cur.execute("""
                SELECT
                    profesor,
                    dia,
                    hora_entrada,
                    hora_salida,
                    materia,
                    salon
                FROM horarios
                WHERE profesor = %s
                  AND dia = %s
                ORDER BY hora_entrada ASC
                LIMIT 1;
            """, (
                profesor,
                siguiente
            ))

            fila = cur.fetchone()

            print(f"[DEBUG] buscando {siguiente}: {fila}")

            if fila:
                break

    # ─────────────────────────────────────────
    # Fallback semanal
    # ─────────────────────────────────────────

    if not fila:

        cur.execute("""
            SELECT
                profesor,
                dia,
                hora_entrada,
                hora_salida,
                materia,
                salon
            FROM horarios
            WHERE profesor = %s
            ORDER BY
                CASE dia
                    WHEN 'lunes' THEN 1
                    WHEN 'martes' THEN 2
                    WHEN 'miércoles' THEN 3
                    WHEN 'jueves' THEN 4
                    WHEN 'viernes' THEN 5
                    WHEN 'sábado' THEN 6
                    WHEN 'domingo' THEN 7
                END,
                hora_entrada ASC
            LIMIT 1;
        """, (profesor,))

        fila = cur.fetchone()

        print(f"[DEBUG] fallback: {fila}")

    if not fila:

        return {
            "error": "No se encontró horario"
        }

    profesor_db, dia_db, entrada, salida, materia, salon = fila

    # ─────────────────────────────────────────
    # Buscar nivel real
    # ─────────────────────────────────────────

    nivel = None

    for n in [1, 2, 3]:

        cur.execute(
            f"""
            SELECT 1
            FROM nivel{n}
            WHERE codigo::text = %s
            LIMIT 1;
            """,
            (str(salon),)
        )

        if cur.fetchone():
            nivel = n
            break

    cur.close()

    return {
        "profesor": profesor_db,
        "dia": dia_db,
        "materia": materia,
        "hora_entrada": str(entrada),
        "hora_salida": str(salida),
        "salon": str(salon),
        "nivel": nivel
    }
