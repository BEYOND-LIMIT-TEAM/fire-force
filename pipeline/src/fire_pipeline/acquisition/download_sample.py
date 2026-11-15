import csv
import io
import os
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

MAP_KEY = os.getenv("FIRMS_MAP_KEY")
if not MAP_KEY:
    raise SystemExit("ERREUR : FIRMS_MAP_KEY est absent du fichier .env.")

SOURCE = "VIIRS_SNPP_SP"
REGION = "africa"
BBOX = "-20,-35,55,38"

# Période totale à télécharger
PERIODS = [
    (date(2025, 1, 1), date(2025, 1, 5)),
    (date(2025, 1, 6), date(2025, 1, 7)),
]

REQUIRED_COLUMNS = {
    "latitude",
    "longitude",
    "acq_date",
    "acq_time",
    "satellite",
    "instrument",
}

def fetch_with_retries(url, attempts=4):
    import time
    import http.client

    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "fire-data-pipeline/0.1"},
            )

            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read()

        except (
            urllib.error.URLError,
            http.client.IncompleteRead,
            TimeoutError,
            OSError,
        ) as error:
            last_error = error
            print(
                f"Transfert interrompu (tentative {attempt}/{attempts}) : "
                f"{error}"
            )

            if attempt < attempts:
                time.sleep(5 * attempt)

    raise RuntimeError(
        f"Échec après {attempts} tentatives."
    ) from last_error

def download_period(start_date, end_date):
    day_range = (end_date - start_date).days + 1

    if not 1 <= day_range <= 5:
        raise ValueError("Chaque requête doit couvrir entre 1 et 5 jours.")

    url = (
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"{MAP_KEY}/{SOURCE}/{BBOX}/{day_range}/{start_date.isoformat()}"
    )

    filename = (
        f"{SOURCE}_{REGION}_"
        f"{start_date.isoformat()}_{end_date.isoformat()}.csv"
    )

    output_dir = PROJECT_ROOT / "data" / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / filename

    print(f"\nPériode : {start_date} au {end_date}")
    print("Téléchargement en cours...")

   
    content = fetch_with_retries(url)

    text_content = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text_content))
    header = next(reader, None)

    if not header or not REQUIRED_COLUMNS.issubset(set(header)):
        raise ValueError(
            "La réponse ne contient pas les colonnes attendues. "
            "Le fichier ne sera pas enregistré."
        )

    observation_count = sum(1 for row in reader)

    # Écriture temporaire puis remplacement pour éviter un fichier incomplet.
    temporary_file = output_file.with_suffix(".csv.tmp")
    temporary_file.write_bytes(content)
    temporary_file.replace(output_file)

    print("Téléchargement réussi.")
    print(f"Observations : {observation_count:,}")
    print(f"Taille : {output_file.stat().st_size:,} octets")
    print(f"Fichier : {output_file.relative_to(PROJECT_ROOT)}")

    return observation_count


def main():
    total_observations = 0

    for start_date, end_date in PERIODS:
        try:
            total_observations += download_period(start_date, end_date)
        except urllib.error.HTTPError as error:
            print(f"\nErreur HTTP : {error.code}")
            print(error.read().decode("utf-8", errors="replace")[:500])
            raise SystemExit(1)
        except Exception as error:
            print(
                f"\nÉchec du téléchargement : "
                f"{type(error).__name__}: {error}"
            )
            raise SystemExit(1)

    print("\n=== Bilan du téléchargement ===")
    print("Période demandée : du 1er au 7 janvier 2025")
    print(f"Total des observations : {total_observations:,}")
    print("Les deux fichiers sont enregistrés dans data/raw/.")


if __name__ == "__main__":
    main()
