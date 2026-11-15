import os
import psycopg
from dotenv import load_dotenv

load_dotenv(".env")

csv_path = "/tmp/daily_fire_grid.csv"

if not os.path.isfile(csv_path):
    raise SystemExit(f"Fichier introuvable : {csv_path}")

with psycopg.connect(os.environ["NEON_DATABASE_URL"]) as conn:
    existing = conn.execute(
        "SELECT COUNT(*) FROM public.daily_fire_grid"
    ).fetchone()[0]

    if existing != 0:
        raise SystemExit(
            f"La table contient déjà {existing} lignes. Import annulé."
        )

    print("Début de l'importation vers Neon...", flush=True)

    with conn.cursor().copy("""
        COPY public.daily_fire_grid
        (grid_id, grid_x, grid_y, date, fire_count,
         frp_sum, frp_mean, frp_max, brightness_mean)
        FROM STDIN WITH (FORMAT CSV, HEADER true)
    """) as copy:
        with open(csv_path, "r", encoding="utf-8") as f:
            while chunk := f.read(1024 * 1024):
                copy.write(chunk)

    count = conn.execute(
        "SELECT COUNT(*) FROM public.daily_fire_grid"
    ).fetchone()[0]

    print(f"Import terminé : {count:,} observations.", flush=True)
