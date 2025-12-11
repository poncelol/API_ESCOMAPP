# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.extras import RealDictCursor
import os

app = FastAPI()

# -------------------------
# CORS (para acceso desde cualquier origen)
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Función para conectarse a PostgreSQL
# -------------------------
def get_conn():
    try:
        conn = psycopg2.connect(
            host=os.getenv("PGHOST"),
            database=os.getenv("PGDATABASE"),
            user=os.getenv("PGUSER"),
            password=os.getenv("PGPASSWORD"),
            port=os.getenv("PGPORT", 5432),
            sslmode=os.getenv("PGSSLMODE", "require"),
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error de conexión a la base de datos: {str(e)}")

# -------------------------
# Función para construir GeoJSON desde tabla
# -------------------------
def construir_geojson(tabla: str, tipo: str = None):
    try:
        conn = get_conn()
        cur = conn.cursor()
        query = f"SELECT * FROM {tabla}"
        if tipo:
            query += f" WHERE tipo = %s"
            cur.execute(query, (tipo,))
        else:
            cur.execute(query)
        results = cur.fetchall()
        cur.close()
        conn.close()
        return {"data": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar {tabla}: {str(e)}")

# -------------------------
# Endpoints
# -------------------------

@app.get("/")
def root():
    return {"message": "API funcionando correctamente"}

@app.get("/Nivel1")
def nivel1(tipo: str = None):
    return construir_geojson("nivel1", tipo)

@app.get("/Nivel2")
def nivel2(tipo: str = None):
    return construir_geojson("nivel2", tipo)

@app.get("/Nivel3")
def nivel3(tipo: str = None):
    return construir_geojson("nivel3", tipo)

@app.get("/Tipos")
def tipos():
    return construir_geojson("tipos")

@app.get("/Niveles")
def niveles():
    return construir_geojson("niveles")










