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
            SELECT ogc_fid, id, codigo, tipo, nivel, ST_AsGeoJSON(wkb_geometry)
            FROM {nombre_tabla}
            WHERE tipo = %s;
        """, (tipo,))
    else:
        cur.execute(f"""
            SELECT ogc_fid, id, codigo, tipo, nivel, ST_AsGeoJSON(wkb_geometry)
            FROM {nombre_tabla};
        """)

    features = []
    for ogc_fid, sid, codigo, tipo, nivel, geom in cur.fetchall():
        features.append({
            "type": "Feature",
            "properties": {
                "ogc_fid": ogc_fid,
                "id": sid,
                "codigo": codigo,
                "tipo": tipo,
                "nivel": nivel
            },
            "geometry": json.loads(geom)
        })

    return {"type": "FeatureCollection", "features": features}

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

# =========================================
#  SUBIR EXCEL → PostgreSQL
# =========================================
@app.post("/subir_excel")
async def subir_excel(file: UploadFile = File(...)):
    try:
        contenido = await file.read()
        df = pd.read_excel(BytesIO(contenido))

        columnas_requeridas = ["Profesor", "Día", "Hora Entrada", "Hora Salida", "Materia", "Salón"]
        for col in columnas_requeridas:
            if col not in df.columns:
                return {"error": f"Falta la columna {col} en el Excel"}

        cur = conn.cursor()

        for _, row in df.iterrows():
            cur.execute("""
                INSERT INTO horarios (profesor, dia, hora_entrada, hora_salida, materia, salon)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                row["Profesor"],
                row["Día"],
                row["Hora Entrada"],
                row["Hora Salida"],
                row["Materia"],
                row["Salón"]
            ))

        conn.commit()
        return {"mensaje": "Excel importado correctamente"}

    except Exception as e:
        return {"error": str(e)}

# =========================================
#  LISTA DE PROFESORES
# =========================================
@app.get("/profesores")
def obtener_profesores():
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT profesor FROM horarios ORDER BY profesor;")
    profesores = [row[0] for row in cur.fetchall()]
    return {"profesores": profesores}

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
#  LISTA DE NIVELES DISPONIBLES
# =========================================
@app.get("/Niveles")
def obtener_niveles():
    return {"niveles": [1, 2, 3]}


