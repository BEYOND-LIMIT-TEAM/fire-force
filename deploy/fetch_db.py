"""Télécharger la base de l'application et vérifier qu'elle est utilisable.

Utilisé par le Dockerfile pendant la construction de l'image :
    python deploy/fetch_db.py URL /data/fireforce.duckdb

La construction échoue (et l'ancienne version reste en ligne) si le fichier
est introuvable, tronqué, ou n'est pas une base Fire Force.
"""

import os
import sys
import time
import urllib.request

import duckdb


def download(url, target, attempts=3):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temporary = target + ".part"
    for attempt in range(1, attempts + 1):
        try:
            print(f"Téléchargement de la base (essai {attempt}/{attempts}) : {url}", flush=True)
            request = urllib.request.Request(url, headers={"User-Agent": "fire-force-build"})
            with urllib.request.urlopen(request, timeout=120) as response, \
                 open(temporary, "wb") as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
            os.replace(temporary, target)
            return
        except OSError as error:
            print(f"  échec : {error}", flush=True)
            if attempt == attempts:
                raise SystemExit(f"Impossible de télécharger la base depuis {url}")
            time.sleep(5 * attempt)


def check(target):
    size_mb = os.path.getsize(target) / 1e6
    try:
        con = duckdb.connect(target, read_only=True)
        try:
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
            rows = con.execute("SELECT COUNT(*) FROM daily").fetchall()[0][0]
        finally:
            con.close()
    except duckdb.Error as error:
        raise SystemExit(f"Le fichier n'est pas une base Fire Force valide : {error}")
    print(
        f"Base OK : {size_mb:.0f} Mo, jeu « {meta.get('dataset')} », "
        f"{meta.get('first_day')} → {meta.get('last_day')}, {rows:,} lignes",
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage : python fetch_db.py URL FICHIER_DE_SORTIE")
    download(sys.argv[1], sys.argv[2])
    check(sys.argv[2])
