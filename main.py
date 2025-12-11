from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os

app = FastAPI()

# -------------------------
#   CORS (permite acceso desde Android o cualquier origen)
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
#   FUNCION PARA OBTENER CONEXION POSTGRES EN RENDER
# -------------------------
def get_conn():
    """
    Devuelve una conexión a PostgreSQL usando variables de entorno.
    Render requiere SSL, por eso sslmode='require'.
    """
    return psycopg2.connect(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT", 5432),
        sslmode="require",  # obligatorio en Render
        cursor_factory=RealDictCursor
    )

# -------------------------
#   FUNCION PARA GENERAR GEOJSON
# -------------------------
def construir_geojson(nombre_tabla: str, tipo: str = None):
    conn = get_conn()
    cur = conn.cursor()

    if tipo:
        cur.execute(f"""
            SELECT ogc_fid, id, codigo, tipo, nivel, ST_AsGeoJSON(wkb_geometry) AS geom
            FROM {nombre_tabla}
            WHERE tipo = %s;
        """, (tipo,))
    else:
        cur.execute(f"""
            SELECT ogc_fid, id, codigo, tipo, nivel, ST_AsGeoJSON(wkb_geometry) AS geom
            FROM {nombre_tabla};
        """)

    rows = cur.fetchall()
    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "properties": {
                "ogc_fid": row["ogc_fid"],
                "id": row["id"],
                "codigo": row["codigo"],
                "tipo": row["tipo"],
                "nivel": row["nivel"]
            },
            "geometry": json.loads(row["geom"])
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
    tipos = [row["tipo"] for row in cur.fetchall() if row["tipo"] is not None]
    cur.close()
    conn.close()
    return {"tipos": tipos}

# -------------------------
#   ENDPOINT OPCIONAL: LISTA DE NIVELES DISPONIBLES
# -------------------------
@app.get("/Niveles")
def obtener_niveles():
    return {"niveles": [1, 2, 3]}








