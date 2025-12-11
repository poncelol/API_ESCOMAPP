from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

app = FastAPI()

# -------------------------
#   CORS (permite acceso desde Android o web)
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
#   POOL DE CONEXIONES A POSTGRES EN RENDER
# -------------------------
try:
    db_pool = pool.SimpleConnectionPool(
        1, 20,  # min y max conexiones
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT"),
        sslmode=os.getenv("PGSSLMODE", "require"),
        cursor_factory=RealDictCursor
    )
    if db_pool:
        print("Pool de conexiones creado exitosamente")
except Exception as e:
    print(f"Error creando pool de conexiones: {e}")
    raise

# -------------------------
#   FUNCIONES AUXILIARES
# -------------------------
def get_conn():
    try:
        return db_pool.getconn()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error de conexión a la base de datos: {e}")

def release_conn(conn):
    if conn:
        db_pool.putconn(conn)

# -------------------------
#   FUNCIÓN PARA GENERAR GEOJSON
# -------------------------
def construir_geojson(nombre_tabla: str, tipo: str = None):
    conn = get_conn()
    try:
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
        for row in cur.fetchall():
            ogc_fid, sid, codigo, tipo_val, nivel, geom = row
            features.append({
                "type": "Feature",
                "properties": {
                    "ogc_fid": ogc_fid,
                    "id": sid,
                    "codigo": codigo,
                    "tipo": tipo_val,
                    "nivel": nivel
                },
                "geometry": json.loads(geom)
            })

        return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar {nombre_tabla}: {e}")
    finally:
        release_conn(conn)

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
    try:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo tipos: {e}")
    finally:
        release_conn(conn)

# -------------------------
#   ENDPOINT PARA LISTA DE NIVELES DISPONIBLES
# -------------------------
@app.get("/Niveles")
def obtener_niveles():
    return {"niveles": [1, 2, 3]}
