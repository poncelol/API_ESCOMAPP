import os
import json
import tempfile
from urllib.parse import urlparse
from io import BytesIO

import pandas as pd
import geopandas as gpd

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

import psycopg2

from sqlalchemy import create_engine

# =========================================
# FASTAPI
# =========================================
app = FastAPI()

# =========================================
# GZIP (IMPORTANTE PARA GEOJSON)
# =========================================
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000
)

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
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    ""
).strip()

if not DATABASE_URL:
    raise Exception(
        "DATABASE_URL no está definida"
    )

# SQLAlchemy requiere postgresql://
if DATABASE_URL.startswith("postgres://"):

    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

url = urlparse(DATABASE_URL)

# =========================================
# FUNCIÓN CONEXIÓN
# =========================================
def get_connection():

    return psycopg2.connect(
        dbname=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port or 5432,
        sslmode="require"
    )

# =========================================
# SQLALCHEMY ENGINE
# =========================================
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300
)

# =========================================
# FUNCIÓN GEOJSON
# =========================================
def construir_geojson(
    nombre_tabla: str,
    tipo: str = None
):

    conn = get_connection()
    cur = conn.cursor()

    try:

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

                WHERE tipo = %s

                LIMIT 1000;
            """, (tipo,))

        else:

            cur.execute(f"""
                SELECT
                    ogc_fid,
                    codigo,
                    tipo,
                    nivel,
                    ST_AsGeoJSON(wkb_geometry)

                FROM {nombre_tabla}

                LIMIT 1000;
            """)

        # =====================================
        # FEATURES
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
        conn.close()

# =========================================
# ENDPOINTS MAPAS
# =========================================
@app.get("/Nivel1")
def nivel1(tipo: str = None):

    return construir_geojson(
        "nivel1",
        tipo
    )

@app.get("/Nivel2")
def nivel2(tipo: str = None):

    return construir_geojson(
        "nivel2",
        tipo
    )

@app.get("/Nivel3")
def nivel3(tipo: str = None):

    return construir_geojson(
        "nivel3",
        tipo
    )

# =========================================
# TIPOS
# =========================================
@app.get("/Tipos")
def obtener_tipos():

    conn = get_connection()
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
        conn.close()

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

    conn = get_connection()
    cur = conn.cursor()

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
        gdf = gpd.read_file(
            ruta_archivo
        )

        if gdf.empty:

            return {
                "error": "Archivo vacío"
            }

        # =====================================
        # CRS
        # =====================================
        if gdf.crs:

            gdf = gdf.to_crs(
                epsg=4326
            )

        # =====================================
        # COLUMNAS
        # =====================================
        gdf.columns = [
            c.lower()
            for c in gdf.columns
        ]

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
        # GEOMETRÍA
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
        # ÍNDICE ESPACIAL
        # =====================================
        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS
            idx_{tabla}_geom

            ON {tabla}

            USING GIST(wkb_geometry);
        """)

        conn.commit()

        return {

            "mensaje":
                "GeoPackage subido correctamente",

            "tabla":
                tabla,

            "registros":
                len(gdf),

            "columnas":
                list(gdf.columns)

        }

    except Exception as e:

        conn.rollback()

        return {
            "error": str(e)
        }

    finally:

        cur.close()
        conn.close()

# =========================================
# SUBIR EXCEL
# =========================================
@app.post("/subir_excel")
async def subir_excel(
    file: UploadFile = File(...)
):

    conn = get_connection()
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
        cur.execute(
            "TRUNCATE TABLE horarios;"
        )

        conn.commit()

        datos_validos = []
        errores = []

        # =====================================
        # VALIDAR
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

                hora_entrada = pd.to_datetime(
                    str(
                        row["Hora Entrada"]
                    ).strip(),
                    format="%H:%M",
                    errors="coerce"
                )

                hora_salida = pd.to_datetime(
                    str(
                        row["Hora Salida"]
                    ).strip(),
                    format="%H:%M",
                    errors="coerce"
                )

                if pd.isna(hora_entrada):

                    fila_error.append(
                        "Hora Entrada inválida"
                    )

                if pd.isna(hora_salida):

                    fila_error.append(
                        "Hora Salida inválida"
                    )

                if fila_error:

                    errores.append({

                        "fila":
                            index + 2,

                        "errores":
                            fila_error

                    })

                    continue

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

                    "fila":
                        index + 2,

                    "errores":
                        [str(e)]

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

                VALUES
                (
                    %s,%s,%s,%s,%s,%s
                )

            """, datos_validos)

            conn.commit()

        return {

            "mensaje":
                "Importación finalizada",

            "insertados":
                len(datos_validos),

            "errores":
                len(errores),

            "detalle_errores":
                errores

        }

    except Exception as e:

        conn.rollback()

        return {

            "error":
                "Error importando Excel",

            "detalle":
                str(e)

        }

    finally:

        cur.close()
        conn.close()

# =========================================
# PROFESORES
# =========================================
@app.get("/profesores")
def obtener_profesores():

    conn = get_connection()
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
        conn.close()

# =========================================
# HORARIO
# =========================================
@app.get("/horario")
def consultar_horario(
    profesor: str,
    salon: str,
    dia: str,
    hora: str
):

    conn = get_connection()
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

                "disponible":
                    True,

                "profesor":
                    profesor,

                "materia":
                    materia,

                "entrada":
                    str(entrada),

                "salida":
                    str(salida)

            }

        return {

            "disponible":
                False,

            "mensaje":
                "No encontrado"

        }

    except Exception as e:

        return {
            "error": str(e)
        }

    finally:

        cur.close()
        conn.close()

# =========================================
# ÚLTIMO SALÓN
# =========================================
@app.get("/ultimo_salon_profesor")
def ultimo_salon_profesor(
    profesor: str
):

    conn = get_connection()
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
                "error":
                    "Profesor no encontrado"
            }

        profesor, dia, entrada, salida, materia, salon = fila

        return {

            "profesor":
                profesor,

            "dia":
                dia,

            "materia":
                materia,

            "hora_entrada":
                str(entrada),

            "hora_salida":
                str(salida),

            "salon":
                salon

        }

    except Exception as e:

        return {
            "error": str(e)
        }

    finally:

        cur.close()
        conn.close()

# =========================================
# NIVELES
# =========================================
@app.get("/Niveles")
def obtener_niveles():

    return {
        "niveles": [1, 2, 3]
    }
