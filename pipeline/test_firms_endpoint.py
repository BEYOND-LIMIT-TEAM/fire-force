
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

map_key = os.getenv("FIRMS_MAP_KEY")

if not map_key:
    raise SystemExit("ERREUR : FIRMS_MAP_KEY est absent du fichier .env")

source = "MODIS_SP"
area = "-20,-35,55,38"
day_range = 2
end_date = "2025-01-02"

url = (
    "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
    f"{map_key}/{source}/{area}/{day_range}/{end_date}"
)

print("Source testée :", source)
print("Période demandée : 2 jours se terminant le", end_date)
print("Zone : Afrique (boîte géographique approximative)")
print("Interrogation de NASA FIRMS...")

try:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "fire-data-pipeline/0.1"},
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read().decode("utf-8-sig")

    lines = content.splitlines()

    if not lines:
        print("Réponse vide.")
    else:
        print("Réponse reçue.")
        print("Nombre de lignes, en-tête inclus :", len(lines))
        print("\nEn-tête et premières lignes :")

        for line in lines[:4]:
            print(line)

except urllib.error.HTTPError as error:
    print("Erreur HTTP :", error.code)
    print(error.read().decode("utf-8", errors="replace")[:1000])

except Exception as error:
    print("Échec du test :", type(error).__name__, str(error))
