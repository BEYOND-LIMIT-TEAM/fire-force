import os
import duckdb

SOURCE = "/home/bengon-zack/Téléchargements/DL_FIRE_J1V-C2_847831/fire_archive_J1V-C2_847831.csv"
CELLS = "/tmp/fire_grid_cells.csv"

OUTPUT_DIR = "data/aggregated/daily"
INTERMEDIATE = "/tmp/viirs_daily_all_cells.parquet"
FULL_OUTPUT = f"{OUTPUT_DIR}/viirs_daily_grid_30km.parquet"
COMMON_OUTPUT = f"{OUTPUT_DIR}/viirs_daily_grid_30km_common_2018-04-01_2025-08-03.parquet"

PROJECTION = (
    "+proj=aea +lat_1=20 +lat_2=-23 +lat_0=0 "
    "+lon_0=25 +datum=WGS84 +units=m +no_defs"
)

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs("/tmp/duckdb_viirs_tmp", exist_ok=True)

for path in (INTERMEDIATE, FULL_OUTPUT, COMMON_OUTPUT):
    if os.path.exists(path):
        raise FileExistsError(
            f"Le fichier existe déjà : {path}. "
            "Renomme-le ou déplace-le avant de relancer."
        )

if not os.path.isfile(SOURCE) or not os.path.isfile(CELLS):
    raise FileNotFoundError("CSV VIIRS ou fichier des cellules introuvable.")

def sql_path(path):
    return "'" + path.replace("'", "''") + "'"

con = duckdb.connect()
con.execute("LOAD spatial")
con.execute("SET memory_limit = '3GB'")
con.execute("SET threads = 4")
con.execute("SET preserve_insertion_order = false")
con.execute("SET temp_directory = '/tmp/duckdb_viirs_tmp'")

print("Chargement de la grille commune...", flush=True)

con.execute(f"""
    CREATE TEMP TABLE grid_cells AS
    SELECT grid_id
    FROM read_csv(
        {sql_path(CELLS)},
        header = true,
        columns = {{
            'grid_id': 'VARCHAR',
            'grid_x': 'BIGINT',
            'grid_y': 'BIGINT',
            'geom': 'VARCHAR'
        }}
    )
""")

print("Grille chargée :", con.execute(
    "SELECT COUNT(*) FROM grid_cells"
).fetchone()[0], "cellules", flush=True)

print("Début de la projection et de l'agrégation VIIRS...", flush=True)

query = f"""
COPY (
    WITH source AS (
        SELECT
            latitude, longitude, brightness, frp,
            acq_date, confidence, daynight, "type"
        FROM read_csv(
            {sql_path(SOURCE)},
            header = true,
            columns = {{
                'latitude': 'DOUBLE',
                'longitude': 'DOUBLE',
                'brightness': 'DOUBLE',
                'scan': 'DOUBLE',
                'track': 'DOUBLE',
                'acq_date': 'DATE',
                'acq_time': 'VARCHAR',
                'satellite': 'VARCHAR',
                'instrument': 'VARCHAR',
                'confidence': 'VARCHAR',
                'version': 'BIGINT',
                'bright_t31': 'DOUBLE',
                'frp': 'DOUBLE',
                'daynight': 'VARCHAR',
                'type': 'BIGINT'
            }}
        )
    ),
    projected AS (
        SELECT *,
            ST_Transform(
                ST_Point(longitude, latitude),
                'EPSG:4326',
                '{PROJECTION}',
                true
            ) AS p
        FROM source
    ),
    indexed AS (
        SELECT *,
            CAST(FLOOR(ST_X(p) / 30000) AS BIGINT) AS grid_x,
            CAST(FLOOR(ST_Y(p) / 30000) AS BIGINT) AS grid_y
        FROM projected
    ),
    aggregated AS (
        SELECT
            CAST(grid_x AS VARCHAR) || '_' ||
                CAST(grid_y AS VARCHAR) AS grid_id,
            grid_x,
            grid_y,
            acq_date AS date,
            COUNT(*) AS fire_count,
            SUM(frp) AS frp_sum,
            AVG(frp) AS frp_mean,
            MAX(frp) AS frp_max,
            AVG(brightness) AS brightness_mean,
            AVG(longitude) AS longitude_mean,
            AVG(latitude) AS latitude_mean,
            COUNT(*) FILTER (WHERE confidence = 'n') AS confidence_n,
            COUNT(*) FILTER (WHERE confidence = 'l') AS confidence_l,
            COUNT(*) FILTER (WHERE confidence = 'h') AS confidence_h,
            COUNT(*) FILTER (WHERE daynight = 'D') AS daytime_count,
            COUNT(*) FILTER (WHERE daynight = 'N') AS nighttime_count,
            COUNT(*) FILTER (WHERE "type" = 0) AS type_0_count,
            COUNT(*) FILTER (WHERE "type" = 1) AS type_1_count,
            COUNT(*) FILTER (WHERE "type" = 2) AS type_2_count,
            COUNT(*) FILTER (WHERE "type" = 3) AS type_3_count
        FROM indexed
        GROUP BY grid_x, grid_y, acq_date
    )
    SELECT
        a.*,
        (g.grid_id IS NOT NULL) AS in_common_grid
    FROM aggregated a
    LEFT JOIN grid_cells g USING (grid_id)
)
TO {sql_path(INTERMEDIATE)}
(FORMAT PARQUET, COMPRESSION ZSTD)
"""

con.execute(query)

print("Agrégation terminée. Création des deux fichiers finaux...", flush=True)

con.execute(f"""
    COPY (
        SELECT * EXCLUDE (in_common_grid)
        FROM read_parquet({sql_path(INTERMEDIATE)})
        WHERE in_common_grid
    )
    TO {sql_path(FULL_OUTPUT)}
    (FORMAT PARQUET, COMPRESSION ZSTD)
""")

con.execute(f"""
    COPY (
        SELECT * EXCLUDE (in_common_grid)
        FROM read_parquet({sql_path(INTERMEDIATE)})
        WHERE in_common_grid
          AND date BETWEEN DATE '2018-04-01' AND DATE '2025-08-03'
    )
    TO {sql_path(COMMON_OUTPUT)}
    (FORMAT PARQUET, COMPRESSION ZSTD)
""")

stats = con.execute(f"""
    SELECT
        SUM(fire_count) FILTER (WHERE in_common_grid),
        SUM(fire_count) FILTER (WHERE NOT in_common_grid),
        COUNT(DISTINCT grid_id) FILTER (WHERE NOT in_common_grid),
        MIN(date),
        MAX(date)
    FROM read_parquet({sql_path(INTERMEDIATE)})
""").fetchone()

print("\nTRAITEMENT TERMINÉ", flush=True)
print("Détections dans la grille :", stats[0])
print("Détections hors grille :", stats[1])
print("Cellules hors grille :", stats[2])
print("Période :", stats[3], "au", stats[4])
print("Fichier complet :", FULL_OUTPUT)
print("Fichier période commune :", COMMON_OUTPUT)

con.close()
