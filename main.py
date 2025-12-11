from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os

app = FastAPI()

# -------------------------
# CORS (permite acceso desde Android)
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# CONEXIÓN A POSTGIS
# -------------------------
def get_conn():
    """
    Crea una conexión a la base de datos cada vez que se necesita.
    Esto evita problemas de timeout o cierre inesperado de la conexión.
    """
    return psycopg2.connect(
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT", 5432),
        sslmode="prefer",  # cambiar a "require" si tienes certificado
        cursor_factory=RealDictCursor
    )

# -------------------------
# FUNCIÓN PARA GENERAR GEOJSON
# -------------------------
def construir_geojson(nombre_tabla: str, tipo: str = None):
    conn = get_conn()
    cur = conn.cursor()

    # SQL según si viene filtro
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
    for row in cur.fetchall():
        features.append({
            "type": "Feature",
            "properties": {
                "ogc_fid": row["ogc_fid"],
                "id": row["id"],
                "codigo": row["codigo"],
                "tipo": row["tipo"],
                "nivel": row["nivel"]
            },
            "geometry": json.loads(row["st_asgeojson"])
        })

    cur.close()
    conn.close()
    return {"type": "FeatureCollection", "features": features}

# -------------------------
# ENDPOINTS POR NIVEL
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
# ENDPOINT PARA LISTA DE TIPOS
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
# ENDPOINT OPCIONAL: LISTA DE NIVELES DISPONIBLES
# -------------------------
@app.get("/Niveles")
def obtener_niveles():
    return {"niveles": [1, 2, 3]}





