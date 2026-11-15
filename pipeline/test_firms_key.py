import json
import os
import urllib.parse
import urllib.request
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("FIRMS_MAP_KEY")

if not key:
    print("ERREUR : clé absente du fichier .env")
else:
    url = (
        "https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/?"
        + urllib.parse.urlencode({"MAP_KEY": key})
    )

    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = json.load(response)

        print("Réponse NASA FIRMS reçue :")
        print(json.dumps(data, indent=2))

    except Exception as error:
        print("Échec du test :", type(error).__name__, str(error))
