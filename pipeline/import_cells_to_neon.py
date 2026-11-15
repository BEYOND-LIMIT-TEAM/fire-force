import os
import psycopg
from dotenv import load_dotenv

load_dotenv(".env")

conninfo = os.environ["NEON_DATABASE_URL"]
csv_path = "/tmp/fire_grid_cells.csv"

with psycopg.connect(conninfo) as conn:

    with conn.cursor().copy("""
        COPY public.fire_grid_cells
            (grid_id, grid_x, grid_y, geom)
        FROM STDIN WITH (FORMAT CSV, HEADER true)
    """) as copy:
        with open(csv_path, "r", encoding="utf-8") as f:
            while chunk := f.read(1024 * 1024):
                copy.write(chunk)

    count = conn.execute(
        "SELECT COUNT(*) FROM public.fire_grid_cells"
    ).fetchone()[0]

    print(f"Polygones importés dans Neon : {count:,}")
