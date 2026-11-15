import os
import psycopg
from dotenv import load_dotenv

if "NEON_DATABASE_URL" not in os.environ:
    load_dotenv(".env")

BATCH_SIZE = 1000

source_conninfo = "host=/var/run/postgresql dbname=fire_monitoring user=postgres"
target_conninfo = os.environ["NEON_DATABASE_URL"]

with psycopg.connect(source_conninfo) as source, \
     psycopg.connect(target_conninfo) as target:

    total = source.execute(
        "SELECT COUNT(*) FROM neon_test.fire_grid_cells"
    ).fetchone()[0]

    print(f"Polygones à transférer : {total:,}")

    target.execute("TRUNCATE TABLE public.fire_grid_cells")

    cursor = source.cursor()
    cursor.execute("""
        SELECT
            grid_id,
            grid_x,
            grid_y,
            ST_AsText(geom)
        FROM neon_test.fire_grid_cells
        ORDER BY grid_id
    """)

    transferred = 0

    while rows := cursor.fetchmany(BATCH_SIZE):
        with target.cursor().copy("""
            COPY public.fire_grid_cells
                (grid_id, grid_x, grid_y, geom)
            FROM STDIN
        """) as copy:
            for grid_id, grid_x, grid_y, wkt in rows:
                copy.write_row((
                    grid_id,
                    grid_x,
                    grid_y,
                    f"SRID=4326;{wkt}"
                ))

        transferred += len(rows)
        print(f"Transférés : {transferred:,}/{total:,}")

    cursor.close()

    target.commit()

    print("Transfert des polygones terminé.")
