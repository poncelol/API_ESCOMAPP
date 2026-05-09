import os
import json
import tempfile
from urllib.parse import urlparse
from io import BytesIO

import pandas as pd
import geopandas as gpd

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

import psycopg2

from sqlalchemy import create_engine

# =========================================
# FASTAPI
# =========================================
app = FastAPI()

# =========================================
# CORS
# =========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================================
# DATABASE URL
# =========================================
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise Exception("DATABASE_URL no está definida")

# compatibilidad render
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgres://",
        1
    )

url = urlparse(DATABASE_URL)

# =========================================
# CONEXIÓN PSYCOPG2
# =========================================
conn = psycopg2.connect(
    dbname=url.path[1:],
    user=url.username,
    password=url.password,
    host=url.hostname,
    port=url.port or 5432,
    sslmode="require"
)

# =========================================
# SQLALCHEMY ENGINE (GeoPandas)
# =========================================
engine = create_engine(DATABASE_URL)

# =========================================
# FUNCIÓN GEOJSON
# =========================================
def construir_geojson(nombre_tabla: str, tipo: str = None):

    cur = conn.cursor()

    try:

        # =====================================
        # VALIDAR TABLA
        # =====================================
        tablas_validas = [
            "nivel1",
            "nivel2",
            "nivel3"
        ]

        if nombre_tabla not in tablas_validas:
            return {
                "error": "Tabla no permitida"
            }

        # =====================================
        # QUERY
        # =====================================
        if tipo:

            cur.execute(f"""
                SELECT
                    ogc_fid,
                    codigo,
                    tipo,
                    nivel,
                    ST_AsGeoJSON(wkb_geometry)

                FROM {nombre_tabla}

                WHERE tipo = %s;
            """, (tipo,))

        else:

            cur.execute(f"""
                SELECT
                    ogc_fid,
                    codigo,
                    tipo,
                    nivel,
                    ST_AsGeoJSON(wkb_geometry)

                FROM {nombre_tabla};
            """)

        # =====================================
        # CREAR FEATURES
        # =====================================
        features = []

        for fila in cur.fetchall():

            ogc_fid, codigo, tipo, nivel, geom = fila

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

    except Exception as e:

        return {
            "error": str(e)
        }

    finally:
        cur.close()

# =========================================
# ENDPOINTS MAPAS
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
# TIPOS
# =========================================
@app.get("/Tipos")
def obtener_tipos():

    cur = conn.cursor()

    try:

        cur.execute("""

            SELECT DISTINCT tipo FROM nivel1

            UNION

            SELECT DISTINCT tipo FROM nivel2

            UNION

            SELECT DISTINCT tipo FROM nivel3

            ORDER BY tipo;

        """)

        tipos = [
            row[0]
            for row in cur.fetchall()
            if row[0] is not None
        ]

        return {
            "tipos": tipos
        }

    except Exception as e:

        return {
            "error": str(e)
        }

    finally:
        cur.close()

# =========================================
# SUBIR GPKG
# =========================================
@app.post("/subir_gpkg")
async def subir_gpkg(
    file: UploadFile = File(...),
    tabla: str = "nivel1"
):

    tablas_validas = [
        "nivel1",
        "nivel2",
        "nivel3"
    ]

    if tabla not in tablas_validas:

        return {
            "error": "Tabla inválida"
        }

    temp_dir = tempfile.mkdtemp()

    try:

        # =====================================
        # GUARDAR ARCHIVO
        # =====================================
        ruta_archivo = os.path.join(
            temp_dir,
            file.filename
        )

        contenido = await file.read()

        with open(ruta_archivo, "wb") as f:
            f.write(contenido)

        # =====================================
        # LEER GPKG
        # =====================================
        gdf = gpd.read_file(ruta_archivo)

        if gdf.empty:

            return {
                "error": "El archivo está vacío"
            }

        # =====================================
        # CRS
        # =====================================
        if gdf.crs:
            gdf = gdf.to_crs(epsg=4326)

        # =====================================
        # NORMALIZAR COLUMNAS
        # =====================================
        columnas = [c.lower() for c in gdf.columns]

        gdf.columns = columnas

        # =====================================
        # CREAR COLUMNAS SI NO EXISTEN
        # =====================================
        if "codigo" not in gdf.columns:
            gdf["codigo"] = None

        if "tipo" not in gdf.columns:
            gdf["tipo"] = "general"

        if "nivel" not in gdf.columns:

            if tabla == "nivel1":
                gdf["nivel"] = 1

            elif tabla == "nivel2":
                gdf["nivel"] = 2

            elif tabla == "nivel3":
                gdf["nivel"] = 3

        # =====================================
        # RENOMBRAR GEOMETRÍA
        # =====================================
        gdf = gdf.rename_geometry(
            "wkb_geometry"
        )

        # =====================================
        # SUBIR A POSTGIS
        # =====================================
        gdf.to_postgis(
            name=tabla,
            con=engine,
            if_exists="replace",
            index=True,
            index_label="ogc_fid"
        )

        # =====================================
        # CREAR ÍNDICE ESPACIAL
        # =====================================
        cur = conn.cursor()

        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS
            idx_{tabla}_geom

            ON {tabla}

            USING GIST(wkb_geometry);
        """)

        conn.commit()

        cur.close()

        return {

            "mensaje": "GeoPackage subido correctamente",

            "tabla": tabla,

            "registros": len(gdf),

            "columnas": list(gdf.columns)

        }

    except Exception as e:

        return {
            "error": str(e)
        }

# =========================================
# SUBIR EXCEL
# =========================================
@app.post("/subir_excel")
async def subir_excel(file: UploadFile = File(...)):

    cur = conn.cursor()

    try:

        contenido = await file.read()

        df = pd.read_excel(
            BytesIO(contenido),
            engine="openpyxl"
        )

        # =====================================
        # LIMPIAR COLUMNAS
        # =====================================
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

                return {
                    "error": f"Falta columna: {col}"
                }

        # =====================================
        # LIMPIAR TABLA
        # =====================================
        cur.execute("TRUNCATE TABLE horarios;")

        conn.commit()

        datos_validos = []

        errores = []

        # =====================================
        # VALIDAR FILAS
        # =====================================
        for index, row in df.iterrows():

            fila_error = []

            try:

                profesor = str(
                    row["Profesor"]
                ).strip()

                dia = str(
                    row["Día"]
                ).strip().lower()

                materia = str(
                    row["Materia"]
                ).strip()

                salon = str(
                    row["Salón"]
                ).strip()

                # =============================
                # VALIDAR
                # =============================
                if not profesor:
                    fila_error.append("Profesor vacío")

                if not dia:
                    fila_error.append("Día vacío")

                if not materia:
                    fila_error.append("Materia vacía")

                if not salon:
                    fila_error.append("Salón vacío")

                # =============================
                # HORAS
                # =============================
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

                    fila_error.append(
                        f"Hora Entrada inválida: {row['Hora Entrada']}"
                    )

                if pd.isna(hora_salida):

                    fila_error.append(
                        f"Hora Salida inválida: {row['Hora Salida']}"
                    )

                # =============================
                # ERRORES
                # =============================
                if fila_error:

                    errores.append({

                        "fila": index + 2,

                        "datos": row.to_dict(),

                        "errores": fila_error

                    })

                    continue

                # =============================
                # FILA VÁLIDA
                # =============================
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

        # =====================================
        # INSERT
        # =====================================
        if datos_validos:

            cur.executemany("""

                INSERT INTO horarios
                (
                    profesor,
                    dia,
                    hora_entrada,
                    hora_salida,
                    materia,
                    salon
                )

                VALUES (%s,%s,%s,%s,%s,%s)

            """, datos_validos)

            conn.commit()

        return {

            "mensaje": "Importación finalizada",

            "insertados": len(datos_validos),

            "errores": len(errores),

            "detalle_errores": errores

        }

    except Exception as e:

        conn.rollback()

        return {

            "error": "Error importando Excel",

            "detalle": str(e)

        }

    finally:
        cur.close()

# =========================================
# PROFESORES
# =========================================
@app.get("/profesores")
def obtener_profesores():

    cur = conn.cursor()

    try:

        cur.execute("""
            SELECT DISTINCT profesor
            FROM horarios
            ORDER BY profesor;
        """)

        profesores = [
            row[0]
            for row in cur.fetchall()
        ]

        return {
            "profesores": profesores
        }

    except Exception as e:

        return {
            "error": str(e)
        }

    finally:
        cur.close()

# =========================================
# CONSULTAR HORARIO
# =========================================
@app.get("/horario")
def consultar_horario(
    profesor: str,
    salon: str,
    dia: str,
    hora: str
):

    cur = conn.cursor()

    try:

        cur.execute("""

            SELECT
                materia,
                hora_entrada,
                hora_salida

            FROM horarios

            WHERE profesor = %s
            AND salon = %s
            AND dia = %s

            AND %s::time
            BETWEEN hora_entrada
            AND hora_salida;

        """, (
            profesor,
            salon,
            dia,
            hora
        ))

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

                "mensaje": "No encontrado"

            }

    except Exception as e:

        return {
            "error": str(e)
        }

    finally:
        cur.close()

# =========================================
# ÚLTIMO SALÓN
# =========================================
@app.get("/ultimo_salon_profesor")
def ultimo_salon_profesor(profesor: str):

    cur = conn.cursor()

    try:

        cur.execute("""

            SELECT
                profesor,
                dia,
                hora_entrada,
                hora_salida,
                materia,
                salon

            FROM horarios

            WHERE profesor = %s

            ORDER BY hora_salida DESC

            LIMIT 1;

        """, (profesor,))

        fila = cur.fetchone()

        if not fila:

            return {
                "error": "Profesor no encontrado"
            }

        profesor, dia, entrada, salida, materia, salon = fila

        return {

            "profesor": profesor,

            "dia": dia,

            "materia": materia,

            "hora_entrada": str(entrada),

            "hora_salida": str(salida),

            "salon": salon

        }

    except Exception as e:

        return {
            "error": str(e)
        }

    finally:
        cur.close()

# =========================================
# NIVELES
# =========================================
@app.get("/Niveles")
def obtener_niveles():

    return {
        "niveles": [1, 2, 3]
    }
