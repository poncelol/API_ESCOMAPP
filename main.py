from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json

app = FastAPI()

# -------------------------
# CORS (permite acceso desde Android u otros clientes)
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Función para conectar a PostgreSQL con SSL
# -------------------------
def get_conn():
    try:
        conn = psycopg2.connect(
            host=os.getenv("PGHOST"),
            database=os.getenv("PGDATABASE"),
            user=os.getenv("PGUSER"),
            password=os.getenv("PGPASSWORD"),
            port=os.getenv("PGPORT", 5432),
            sslmode="require",  # SSL obligatorio en Render
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error de conexión a la base de datos: {str(e)}")

# -------------------------
# Función para construir GeoJSON desde tabla
# -------------------------
def construir_geojson(nombre_tabla: str, tipo: str = None):
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        if tipo:
            cur.execute(f"""
                SELECT ogc_fid, id, codigo, tipo, nivel, ST_AsGeoJSON(wkb_geometry) as geom
                FROM {nombre_tabla}
                WHERE tipo = %s;
            """, (tipo,))
        else:
            cur.execute(f"""
                SELECT ogc_fid, id, codigo, tipo, nivel, ST_AsGeoJSON(wkb_geometry) as geom
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
                "geometry": json.loads(row["geom"])
            })

        cur.close()
        conn.close()

        return {"type": "FeatureCollection", "features": features}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar {nombre_tabla}: {str(e)}")

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
        tipos = [row["tipo"] for row in cur.fetchall() if row["tipo"] is not None]
        cur.close()
        conn.close()
        return {"tipos": tipos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener tipos: {str(e)}")

# -------------------------
# ENDPOINT OPCIONAL: LISTA DE NIVELES DISPONIBLES
# -------------------------
@app.get("/Niveles")
def obtener_niveles():
    return {"niveles": [1, 2, 3]}

# -------------------------
# ENDPOINT RAÍZ
# -------------------------
@app.get("/")
def root():
    return {"message": "API FastAPI en Render funcionando!"}










