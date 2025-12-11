from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
import json
import os

app = FastAPI()

# -------------------------
#   CORS (permite acceso desde Android/web)
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
#   FUNCIÓN PARA OBTENER CONEXIÓN
# -------------------------
def get_conn():
    return psycopg2.connect(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT"),
        sslmode=os.getenv("PGSSLMODE", "require")  # Usar variable de entorno PGSSLMODE
    )

# -------------------------
#   FUNCIÓN PARA GENERAR GEOJSON
# -------------------------
def construir_geojson(nombre_tabla: str, tipo: str = None):
    conn = get_conn()
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

    cur.close()
    conn.close()

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
    conn = get_conn()
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

    cur.close()
    conn.close()

    return {"tipos": tipos}

# -------------------------
#   ENDPOINT OPCIONAL: LISTA DE NIVELES DISPONIBLES
# -------------------------
@app.get("/Niveles")
def obtener_niveles():
    return {"niveles": [1, 2, 3]}







