import os
import json
from urllib.parse import urlparse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2

app = FastAPI()

# -------------------------
#   CORS (permite acceso desde Android)
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite cualquier origen
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
#   CONEXIÓN A POSTGIS (Render: DATABASE_URL)
# -------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("Variable de entorno DATABASE_URL no encontrada")

# Reemplaza postgresql:// por postgres:// si es necesario
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgres://", 1)

# Parsear la URL
url = urlparse(DATABASE_URL)
conn = psycopg2.connect(
    dbname=url.path[1:],  # eliminar la barra inicial
    user=url.username,
    password=url.password,
    host=url.hostname,
    port=url.port or 5432,
    sslmode='require'
)

# -------------------------
#   FUNCIÓN PARA GENERAR GEOJSON
# -------------------------
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

# -------------------------
#   ENDPOINTS POR NIVEL
# -------------------------
@app.get("/Nivel1")
def nivel1(tipo: str = None):
    return construir_geojson("nivel1", tipo)

@app.get("/Nivel2")
def nivel2(tipo: str = None):
    return construir_geojson("nivel2", tipo)

@app.get("/Nivel3")
def nivel3(tipo: str = None):
    return construir_geojson("nivel3", tipo)

# -------------------------
#   ENDPOINT PARA LISTA DE TIPOS
# -------------------------
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

# -------------------------
#   ENDPOINT OPCIONAL: LISTA DE NIVELES DISPONIBLES
# -------------------------
@app.get("/Niveles")
def obtener_niveles():
    return {"niveles": [1, 2, 3]}
