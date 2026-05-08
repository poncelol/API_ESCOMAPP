import os
import json
from urllib.parse import urlparse
from io import BytesIO
import pandas as pd
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import psycopg2

app = FastAPI()

# =========================================
#  CORS (permite acceso desde Android)
# =========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================
#  CONEXIÓN A POSTGRES / POSTGIS (Render)
# =========================================
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL no está definida en Render")

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgres://", 1)

url = urlparse(DATABASE_URL)

conn = psycopg2.connect(
    dbname=url.path[1:],
    user=url.username,
    password=url.password,
    host=url.hostname,
    port=url.port or 5432,
    sslmode='require'
)

# =========================================
# FUNCIÓN PARA CREAR GEOJSON
# =========================================
def construir_geojson(nombre_tabla: str, tipo: str = None):
    cur = conn.cursor()

    if tipo:
        cur.execute(f"""
            SELECT ogc_fid, codigo, tipo, nivel, ST_AsGeoJSON(wkb_geometry)
            FROM {nombre_tabla}
            WHERE tipo = %s;
        """, (tipo,))
    else:
        cur.execute(f"""
            SELECT ogc_fid, codigo, tipo, nivel, ST_AsGeoJSON(wkb_geometry)
            FROM {nombre_tabla};
        """)

    features = []

    for ogc_fid, codigo, tipo, nivel, geom in cur.fetchall():

        features.append({
            "type": "Feature",
            "properties": {
                "ogc_fid": ogc_fid,
                "codigo": codigo,
                "tipo": tipo,
                "nivel": nivel
            },
            "geometry": json.loads(geom)
        })

    return {
        "type": "FeatureCollection",
        "features": features
    }

# =========================================
#  ENDPOINTS GEOMETRÍA POLÍGONOS
# =========================================
@app.get("/Nivel1")
def nivel1(tipo: str = None):
    return construir_geojson("nivel1", tipo)

@app.get("/Nivel2")
def nivel2(tipo: str = None):
    return construir_geojson("nivel2", tipo)

@app.get("/Nivel3")
def nivel3(tipo: str = None):
    return construir_geojson("nivel3", tipo)

# =========================================
#  OBTENER TIPOS DE POLÍGONOS
# =========================================
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
    tipos = [row[0] for row in cur.fetchall() if row[0] is not None]
    return {"tipos": tipos}



@app.post("/subir_excel")
async def subir_excel(file: UploadFile = File(...)):
    cur = conn.cursor()

    try:
        contenido = await file.read()
        df = pd.read_excel(BytesIO(contenido), engine="openpyxl")

        # =========================
        # LIMPIEZA DE COLUMNAS
        # =========================
        df.columns = df.columns.str.strip()

        columnas_requeridas = [
            "Profesor",
            "Día",
            "Hora Entrada",
            "Hora Salida",
            "Materia",
            "Salón"
        ]

        for col in columnas_requeridas:
            if col not in df.columns:
                return {"error": f"Falta la columna: {col}"}

        # limpiar tabla
        cur.execute("TRUNCATE TABLE horarios;")
        conn.commit()

        datos_validos = []
        errores = []

        # =========================
        # VALIDACIÓN POR FILA
        # =========================
        for index, row in df.iterrows():
            fila_error = []

            try:
                profesor = str(row["Profesor"]).strip()
                dia = str(row["Día"]).strip().lower()
                materia = str(row["Materia"]).strip()
                salon = str(row["Salón"]).strip()

                # validar vacíos
                if not profesor:
                    fila_error.append("Profesor vacío")
                if not dia:
                    fila_error.append("Día vacío")
                if not materia:
                    fila_error.append("Materia vacía")
                if not salon:
                    fila_error.append("Salón vacío")

                # parseo de horas
                hora_entrada = pd.to_datetime(
                    str(row["Hora Entrada"]).strip(),
                    format="%H:%M",
                    errors="coerce"
                )

                hora_salida = pd.to_datetime(
                    str(row["Hora Salida"]).strip(),
                    format="%H:%M",
                    errors="coerce"
                )

                if pd.isna(hora_entrada):
                    fila_error.append(f"Hora Entrada inválida: {row['Hora Entrada']}")
                if pd.isna(hora_salida):
                    fila_error.append(f"Hora Salida inválida: {row['Hora Salida']}")

                # si hay errores → se guarda
                if fila_error:
                    errores.append({
                        "fila": index + 2,  # +2 por Excel (header + index base 0)
                        "datos": row.to_dict(),
                        "errores": fila_error
                    })
                    continue

                # fila válida
                datos_validos.append((
                    profesor,
                    dia,
                    hora_entrada.time(),
                    hora_salida.time(),
                    materia,
                    salon
                ))

            except Exception as e:
                errores.append({
                    "fila": index + 2,
                    "datos": row.to_dict(),
                    "errores": [str(e)]
                })

        # =========================
        # INSERT
        # =========================
        if datos_validos:
            cur.executemany("""
                INSERT INTO horarios
                (profesor, dia, hora_entrada, hora_salida, materia, salon)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, datos_validos)

            conn.commit()

        return {
            "mensaje": "Proceso de importación finalizado",
            "insertados": len(datos_validos),
            "errores": len(errores),
            "detalle_errores": errores
        }

    except Exception as e:
        conn.rollback()
        return {
            "error": "Error general en importación",
            "detalle": str(e)
        }

    finally:
        cur.close()

# =========================================
#  LISTA DE PROFESORES
# =========================================
@app.get("/profesores")
def obtener_profesores():
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT profesor FROM horarios ORDER BY profesor;")
        profesores = [row[0] for row in cur.fetchall()]
        return {"profesores": profesores}
    except Exception as e:
        return {"error": str(e)}

# =========================================
#  CONSULTAR DISPONIBILIDAD DE PROFESOR
# =========================================
@app.get("/horario")
def consultar_horario(profesor: str, salon: str, dia: str, hora: str):
    cur = conn.cursor()
    cur.execute("""
        SELECT materia, hora_entrada, hora_salida
        FROM horarios
        WHERE profesor = %s AND salon = %s AND dia = %s
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
            "salida": str(salida)
        }
    else:
        return {
            "disponible": False,
            "profesor": profesor,
            "mensaje": "No está en este salón en esta hora"
        }

# =========================================
#  OBTENER EL ÚLTIMO SALÓN DONDE ESTUVO EL PROFESOR
# =========================================
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

    profesor, dia, entrada, salida, materia, salon = fila

    return {
        "profesor": profesor,
        "dia": dia,
        "materia": materia,
        "hora_entrada": str(entrada),
        "hora_salida": str(salida),
        "salon": salon
    }

# =========================================
#  LISTA DE NIVELES DISPONIBLES
# =========================================
@app.get("/Niveles")
def obtener_niveles():
    return {"niveles": [1, 2, 3]}




