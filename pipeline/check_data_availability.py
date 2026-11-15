import csv
import io
import os
import urllib.request

from dotenv import load_dotenv

load_dotenv()

map_key = os.getenv("FIRMS_MAP_KEY")

if not map_key:
    raise SystemExit(
        "ERREUR : FIRMS_MAP_KEY est absent du fichier .env"
    )

url = (
    "https://firms.modaps.eosdis.nasa.gov/"
    f"api/data_availability/csv/{map_key}/all"
)

request = urllib.request.Request(
    url,
    headers={"User-Agent": "fire-data-pipeline/0.1"},
)

try:
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read().decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(content))

    print("Périodes disponibles auprès de NASA FIRMS :\n")

    for row in reader:
        print(
            f"Produit : {row.get('data_id')} | "
            f"Début : {row.get('min_date')} | "
            f"Fin : {row.get('max_date')}"
        )

except Exception as error:
    raise SystemExit(
        f"Échec de la consultation : "
        f"{type(error).__name__}: {error}"
    )
