from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
import os
import json
import traceback

app = FastAPI()

# -------------------------
#   CORS (permite acceso desde cualquier origen)
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
#   CONEXIÓN A POSTGRES CON POOL
# -------------------------
try:
    db_pool = psycopg2.pool.SimpleConnectionPool(
        1, 20,  # min y max conexiones
        host=os.getenv("PGHOST"),
        database=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        port=os.getenv("PGPORT", 5432),
        sslmode="require",  # obligatorio en Render
        cursor_factory=RealDictCursor
    )
    if db_pool:
        print("Pool de conexiones creado exitosamente")
except Exception as e:
    print("Error creando pool de conexiones:")
    print(traceback.format_exc())
    raise

# -------------------------
#   FUNCIÓN PARA OBTENER CONEXIÓN DEL POOL
# -------------------------
def get_conn():
    try:
        return db_pool.getconn()
    except Exception as e:
        print("Error obteniendo conexión del pool:")
        print(traceback.format_exc())
        raise

# -------------------------
#   FUNCIÓN PARA LIBERAR CONEXIÓN
# -------------------------
def release_conn(conn):
    try:
        db_pool.putconn(conn)
    except Exception as e:
        print("Error liberando conexión:")
        print(traceback.format_exc())

# -------------------------
#   FUNCIÓN PARA GENERAR GEOJSON
# -------------------------
def construir_geojson(nombre_tabla: str, tipo: str = None):
    conn = None
    try:
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

        rows = cur.fetchall()
        features = []
        for row in rows:
            features.append({
                "type": "Feature",
                "properties": {
                    "ogc_fid": row['ogc_fid'],
                    "id": row['id'],
                    "codigo": row['codigo'],
                    "tipo": row['tipo'],
                    "nivel": row['nivel']
                },
                "geometry": json.loads(row['st_asgeojson'])
            })

        return {"type": "FeatureCollection", "features": features}

    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error al consultar {nombre_tabla}: {str(e)}")
    finally:
        if conn:
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
    conn = None
    try:
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
        tipos = [row['tipo'] for row in cur.fetchall() if row['tipo'] is not None]
        return {"tipos": tipos}
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error al consultar tipos: {str(e)}")
    finally:
        if conn:
            release_conn(conn)

# -------------------------
#   ENDPOINT OPCIONAL: LISTA DE NIVELES DISPONIBLES
# -------------------------
@app.get("/Niveles")
def obtener_niveles():
    return {"niveles": [1, 2, 3]}










