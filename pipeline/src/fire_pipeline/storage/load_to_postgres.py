from pathlib import Path
from datetime import date
from getpass import getpass

import pyarrow.parquet as pq
import psycopg


PROJECT_DIR = Path(__file__).resolve().parents[3]
PARQUET_FILE = PROJECT_DIR / "data/aggregated/daily/modis_daily_grid_30km.parquet"
BATCH_SIZE = 50_000

COLUMNS = [
    "grid_id", "grid_x", "grid_y", "date", "fire_count",
    "frp_sum", "frp_mean", "frp_max", "brightness_mean",
    "longitude", "latitude"
]


def main():
    if not PARQUET_FILE.exists():
        raise FileNotFoundError(f"Fichier introuvable : {PARQUET_FILE}")

    password = getpass("Mot de passe PostgreSQL fire_app : ")

    parquet = pq.ParquetFile(PARQUET_FILE)
    total_rows = parquet.metadata.num_rows
    loaded_rows = 0

    print(f"Fichier : {PARQUET_FILE}")
    print(f"Lignes à importer : {total_rows:,}")

    with psycopg.connect(
        host="localhost",
        dbname="fire_monitoring",
        user="fire_app",
        password=password,
    ) as conn:

        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE daily_fire_grid_staging")

        for batch in parquet.iter_batches(batch_size=BATCH_SIZE):
            rows = batch.to_pylist()

            with conn.transaction():
                with conn.cursor() as cur:
                    with cur.copy(
                        """
                        COPY daily_fire_grid_staging (
                            grid_id, grid_x, grid_y, date, fire_count,
                            frp_sum, frp_mean, frp_max, brightness_mean,
                            longitude, latitude
                        ) FROM STDIN
                        """
                    ) as copy:
                        for row in rows:
                            row["date"] = date.fromisoformat(row["date"])
                            copy.write_row(tuple(row[col] for col in COLUMNS))

            loaded_rows += len(rows)
            print(f"Importées : {loaded_rows:,} / {total_rows:,}")

    print("\nIMPORTATION TERMINÉE")
    print(f"Total importé : {loaded_rows:,} lignes")


if __name__ == "__main__":
    main()
