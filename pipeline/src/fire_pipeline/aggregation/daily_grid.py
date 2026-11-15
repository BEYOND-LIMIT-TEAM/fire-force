import argparse
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[3]

INPUT_FILE = PROJECT_ROOT / "data/processed/fire_archive_M-C61_847830.parquet"
OUTPUT_DIR = PROJECT_ROOT / "data/aggregated/daily"

GRID_SIZE = 30_000

TARGET_CRS = (
    "+proj=aea +lat_1=20 +lat_2=-23 +lat_0=0 "
    "+lon_0=25 +datum=WGS84 +units=m +no_defs"
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not INPUT_FILE.exists():
        raise SystemExit(f"Fichier introuvable : {INPUT_FILE}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    suffix = "_sample" if args.limit else ""
    output_file = OUTPUT_DIR / f"modis_daily_grid_30km{suffix}.parquet"

    con = duckdb.connect()

    try:
        con.execute("LOAD spatial")
        con.execute("SET preserve_insertion_order = false")

        limit_sql = f"LIMIT {args.limit}" if args.limit else ""

        query = f"""
        COPY (
            WITH source AS (
                SELECT
                    acquisition_date AS date,
                    latitude,
                    longitude,
                    frp,
                    brightness
                FROM read_parquet('{INPUT_FILE.as_posix()}')
                WHERE latitude BETWEEN -90 AND 90
                  AND longitude BETWEEN -180 AND 180
                {limit_sql}
            ),
            projected AS (
                SELECT
                    date,
                    frp,
                    brightness,
                    ST_X(geom) AS x,
                    ST_Y(geom) AS y
                FROM (
                    SELECT
                        *,
                        ST_Transform(
                            ST_Point(longitude, latitude),
                            'EPSG:4326',
                            '{TARGET_CRS}',
                            always_xy := true
                        ) AS geom
                    FROM source
                )
            ),
            gridded AS (
                SELECT
                    date,
                    frp,
                    brightness,
                    CAST(FLOOR(x / {GRID_SIZE}) AS BIGINT) AS grid_x,
                    CAST(FLOOR(y / {GRID_SIZE}) AS BIGINT) AS grid_y
                FROM projected
            ),
            aggregated AS (
                SELECT
                    grid_x,
                    grid_y,
                    date,
                    COUNT(*) AS fire_count,
                    SUM(frp) AS frp_sum,
                    AVG(frp) AS frp_mean,
                    MAX(frp) AS frp_max,
                    AVG(brightness) AS brightness_mean
                FROM gridded
                GROUP BY grid_x, grid_y, date
            )
            SELECT
                CONCAT(grid_x, '_', grid_y) AS grid_id,
                grid_x,
                grid_y,
                date,
                fire_count,
                frp_sum,
                frp_mean,
                frp_max,
                brightness_mean,
                ST_X(center) AS longitude,
                ST_Y(center) AS latitude
            FROM (
                SELECT
                    *,
                    ST_Transform(
                        ST_Point(
                            (grid_x + 0.5) * {GRID_SIZE},
                            (grid_y + 0.5) * {GRID_SIZE}
                        ),
                        '{TARGET_CRS}',
                        'EPSG:4326',
                        always_xy := true
                    ) AS center
                FROM aggregated
            )
        )
        TO '{output_file.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD)
        """

        print("Début de l'agrégation...")
        con.execute(query)

        result = con.execute(f"""
            SELECT
                COUNT(*),
                COUNT(DISTINCT grid_id),
                MIN(date),
                MAX(date),
                SUM(fire_count)
            FROM read_parquet('{output_file.as_posix()}')
        """).fetchone()

        print("\nAGRÉGATION TERMINÉE")
        print(f"Lignes : {result[0]:,}")
        print(f"Cellules : {result[1]:,}")
        print(f"Première date : {result[2]}")
        print(f"Dernière date : {result[3]}")
        print(f"Détections agrégées : {result[4]:,}")
        print(f"Fichier : {output_file}")

    finally:
        con.close()


if __name__ == "__main__":
    main()
