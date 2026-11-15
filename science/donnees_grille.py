"""
Lecture commune des fichiers .parquet de la grille 30 km (un fichier par capteur/satellite).

Format attendu (celui de modis_daily_grid_30km.parquet) : une ligne par cellule et par jour avec
grid_x, grid_y (indices entiers de la grille Africa Albers 30 km), date, fire_count, frp_sum.
Si le parquet VIIRS a d'autres noms de colonnes, change les valeurs par défaut ci-dessous
ou utilise les options --col-* des scripts.

Les sources se donnent sous la forme  ETIQUETTE=fichier.parquet, par exemple :
    --source MODIS=modis_daily_grid_30km.parquet --source VIIRS_SNPP=viirs_snpp.parquet
Chaque étiquette est traitée comme UNE série (un capteur ou un satellite). Les étiquettes VIIRS
ne sont jamais additionnées entre elles sans le demander : le nombre de satellites actifs change
dans le temps et créerait une fausse tendance.
"""
import argparse

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from parquet_vers_postgres import BASE, DEC, PROJ_AFRIQUE  # mêmes constantes que le chargeur

COLS = dict(x="grid_x", y="grid_y", date="date", count="fire_count", frp="frp_sum")


def ajouter_options(ap):
    ap.add_argument("--source", action="append", required=True, metavar="ETIQUETTE=FICHIER",
                    help="une série par option (répéter l'option)")
    for k, v in COLS.items():
        ap.add_argument(f"--col-{k}", default=v)


def parse_sources(valeurs):
    out = []
    for v in valeurs:
        if "=" not in v:
            raise SystemExit(f"--source attend ETIQUETTE=FICHIER, reçu : {v}")
        lab, path = v.split("=", 1)
        out.append((lab.strip(), path.strip()))
    return out


def cell_id_grille(gx, gy):
    return (np.asarray(gy, dtype="int64") + DEC) * BASE + (np.asarray(gx, dtype="int64") + DEC)


def lire(label, path, col=None):
    """Renvoie un DataFrame : grid_x, grid_y, day (datetime), count, frp_sum, label."""
    c = {**COLS, **(col or {})}
    pf = pq.ParquetFile(path)
    manque = [v for k, v in c.items() if k in ("x", "y", "date", "count") and v not in pf.schema_arrow.names]
    if manque:
        raise SystemExit(f"{path} : colonnes introuvables {manque}. Colonnes : {pf.schema_arrow.names}")
    cols = [c["x"], c["y"], c["date"], c["count"]] + ([c["frp"]] if c["frp"] in pf.schema_arrow.names else [])
    d = pf.read(columns=cols).to_pandas()
    out = pd.DataFrame({
        "grid_x": d[c["x"]].astype("int32"), "grid_y": d[c["y"]].astype("int32"),
        "day": pd.to_datetime(d[c["date"]]),
        "count": d[c["count"]].astype("float64"),
        "frp_sum": d[c["frp"]].astype("float64") if c["frp"] in d else np.nan})
    out["label"] = pd.Categorical([label] * len(out))
    # sécurité : une seule ligne par cellule et par jour dans une même source
    cles = ["grid_x", "grid_y", "day"]
    if out.duplicated(cles).any():
        out = out.groupby(cles, as_index=False).agg(count=("count", "sum"), frp_sum=("frp_sum", "sum"))
        out["label"] = pd.Categorical([label] * len(out))
    return out


def lire_toutes(sources, col=None):
    return {lab: lire(lab, p, col) for lab, p in sources}


def centre_lonlat(gx, gy, taille=30000.0):
    """Centre (lon, lat) d'une cellule, via pyproj. Renvoie (None, None) si pyproj est absent."""
    try:
        from pyproj import Transformer
    except ImportError:
        return None, None
    t = Transformer.from_crs(PROJ_AFRIQUE, "EPSG:4326", always_xy=True)
    lon, lat = t.transform((np.asarray(gx) + 0.5) * taille, (np.asarray(gy) + 0.5) * taille)
    return lon, lat
