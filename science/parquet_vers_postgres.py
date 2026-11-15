"""
Charge un fichier .parquet (déjà agrégé par cellule et par jour) dans la base PostgreSQL/PostGIS
du projet Fire Force, puis calcule la climatologie.

Tables remplies : grid_cells, daily_activity, climatology, import_log (+ vue monthly_activity).

Étapes (une transaction : tout ou rien) :
  1. lecture du parquet par morceaux  ->  table temporaire "stg" dans Postgres (COPY)
  2. Postgres fait lui-même les sommes (GROUP BY) et remplit daily_activity
  3. grid_cells : un carré par cellule, construit par PostGIS
  4. climatology : calculée cellule par cellule (par blocs, pour ménager la mémoire)

DEUX FAÇONS DE DÉCRIRE LA GRILLE
  --grille geo        le fichier donne la latitude/longitude de chaque cellule (cellules de 0,25°)
  --grille projetee   le fichier donne des indices entiers grid_x / grid_y dans une projection en
                      mètres (cas de modis_daily_grid_30km.parquet : Africa Albers, cellules de
                      30 000 m). Le script reconstruit alors chaque carré de 30 km et PostGIS le
                      convertit en polygone lat/lon.

Exemple pour modis_daily_grid_30km.parquet :
  python parquet_vers_postgres.py --parquet modis_daily_grid_30km.parquet --grille projetee \
      --col-x grid_x --col-y grid_y --col-date date --col-count fire_count --col-frp frp_sum \
      --dry-run

Exemple en grille lat/lon (adapte les noms de colonnes à TON fichier : voir inspecter_parquet.py) :
  python parquet_vers_postgres.py --parquet donnees.parquet \
      --col-date date --col-lat lat --col-lon lon --col-count nb_harmonise \
      --col-raw nb_brut --col-frp frp --coin sud-ouest --dry-run

  puis, sans --dry-run, avec --db "postgresql://utilisateur:motdepasse@hote/base?sslmode=require"
  (ou la variable d'environnement DATABASE_URL).

Important :
 - --coin : les lat/lon du fichier sont-elles le coin SUD-OUEST de la cellule (comme plot_firms.py)
   ou son CENTRE ? Un mauvais choix décale toute la carte d'une demi-cellule.
 - Si le fichier a plusieurs lignes pour la même (cellule, jour) (ex. une par capteur), elles sont
   ADDITIONNÉES. Si ce n'est pas voulu, harmonise avant.
 - La climatologie suppose que le fichier couvre TOUS les jours de la période : un jour sans ligne
   compte pour 0 feu.

Dépendances : pandas, numpy, pyarrow, psycopg[binary]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from charger_role2 import cell_id, climatologie

# Projection du fichier 30 km : Africa Albers Equal Area (centre 25°E). Vérifiée : floor(x/30000),
# floor(y/30000) des centroïdes retrouve exactement grid_x / grid_y.
PROJ_AFRIQUE = ("+proj=aea +lat_1=20 +lat_2=-23 +lat_0=0 +lon_0=25 +x_0=0 +y_0=0 "
                "+ellps=WGS84 +units=m")
DEC = 1000       # décalage pour que les indices négatifs donnent un identifiant positif
BASE = 10000     # cell_id = (grid_y + DEC) * BASE + (grid_x + DEC)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--db", default=os.environ.get(
        "DATABASE_URL", "postgresql://fireweb:fireweb@localhost:5432/fireweb"))
    ap.add_argument("--col-date", required=True)
    ap.add_argument("--grille", choices=["geo", "projetee"], default="geo")
    ap.add_argument("--col-lat", default=None, help="(grille geo)")
    ap.add_argument("--col-lon", default=None, help="(grille geo)")
    ap.add_argument("--col-x", default=None, help="(grille projetee) indice de colonne, ex. grid_x")
    ap.add_argument("--col-y", default=None, help="(grille projetee) indice de ligne, ex. grid_y")
    ap.add_argument("--taille-m", type=float, default=30000.0, help="(grille projetee) côté en mètres")
    ap.add_argument("--proj", default=PROJ_AFRIQUE, help="(grille projetee) définition proj4")
    ap.add_argument("--col-count", required=True, help="nombre de feux harmonisé -> count_harmonized")
    ap.add_argument("--col-raw", default=None, help="nombre brut -> count_raw (sinon = col-count)")
    ap.add_argument("--col-frp", default=None, help="FRP total (facultatif)")
    ap.add_argument("--coin", choices=["sud-ouest", "centre"], default="sud-ouest")
    ap.add_argument("--resolution", type=float, default=0.25)
    ap.add_argument("--min-annees", type=int, default=3)
    ap.add_argument("--sans-climatologie", action="store_true")
    ap.add_argument("--jours-couverts", default=None,
                    help="couverture_jours.csv (produit par harmonisation.py) : les jours marqués "
                         "'aucune' sont des trous de données, pas des jours à 0 feu")
    ap.add_argument("--remplacer", action="store_true",
                    help="autorise à vider daily_activity et climatology avant de recharger")
    ap.add_argument("--dry-run", action="store_true", help="lit et vérifie, n'écrit rien")
    ap.add_argument("--lot", type=int, default=500_000, help="lignes lues par morceau")
    a = ap.parse_args()
    res = a.resolution

    pf = pq.ParquetFile(a.parquet)
    geo = a.grille == "geo"
    cols_pos = [a.col_lat, a.col_lon] if geo else [a.col_x, a.col_y]
    if not all(cols_pos):
        sys.exit("Grille geo : --col-lat et --col-lon requis.\n"
                 "Grille projetee : --col-x et --col-y requis.")
    wanted = [a.col_date, *cols_pos, a.col_count] + [c for c in (a.col_raw, a.col_frp) if c]
    absent = [c for c in wanted if c not in pf.schema_arrow.names]
    if absent:
        sys.exit(f"Colonnes introuvables : {absent}\nColonnes du fichier : {pf.schema_arrow.names}")

    def morceaux():
        for lot in pf.iter_batches(batch_size=a.lot, columns=wanted):
            d = lot.to_pandas()
            if geo:
                lat, lon = d[a.col_lat].astype(float), d[a.col_lon].astype(float)
                if a.coin == "centre":
                    lat, lon = lat - res / 2, lon - res / 2
                ids = cell_id(lat, lon, res)
            else:
                ids = ((d[a.col_y].astype("int64") + DEC) * BASE
                       + (d[a.col_x].astype("int64") + DEC)).to_numpy()
            out = pd.DataFrame({
                "cell_id": ids,
                "day": pd.to_datetime(d[a.col_date]).dt.date,
                "cnt": d[a.col_count].astype(float),
                "raw": (d[a.col_raw] if a.col_raw else d[a.col_count]).astype(float),
                "frp": d[a.col_frp].astype(float) if a.col_frp else np.nan})
            yield out

    if a.dry_run:
        n = 0
        cells, d0, d1 = set(), None, None
        for m in morceaux():
            n += len(m)
            cells.update(m["cell_id"].unique().tolist())
            lo, hi = m["day"].min(), m["day"].max()
            d0 = lo if d0 is None else min(d0, lo)
            d1 = hi if d1 is None else max(d1, hi)
        print(f"{n:,} lignes lues ; {len(cells):,} cellules ; du {d0} au {d1}")
        print(f"Estimation de la taille de daily_activity : environ {n * 80 / 1e6:,.0f} Mo "
              "(~80 octets/ligne, index compris) ; compare au quota de ton hébergeur.")
        print("--dry-run : rien n'a été écrit.")
        return

    import psycopg
    with psycopg.connect(a.db) as conn:
        cur = conn.cursor()
        existe = cur.execute("SELECT (SELECT COUNT(*) FROM daily_activity) + "
                             "(SELECT COUNT(*) FROM climatology)").fetchone()[0]
        if existe and not a.remplacer:
            sys.exit(f"daily_activity/climatology contiennent déjà {existe:,} lignes. "
                     "Relancez avec --remplacer.")
        cur.execute("DELETE FROM daily_activity")
        cur.execute("DELETE FROM climatology")

        # 1) parquet -> table temporaire
        cur.execute("CREATE TEMP TABLE stg (cell_id integer, day date, cnt float8, raw float8, "
                    "frp float8) ON COMMIT DROP")
        n = 0
        with cur.copy("COPY stg FROM STDIN") as cp:
            for m in morceaux():
                for r in m.itertuples(index=False):
                    cp.write_row((int(r.cell_id), r.day, r.cnt, r.raw,
                                  None if pd.isna(r.frp) else r.frp))
                n += len(m)
        print(f"{n:,} lignes copiées dans la zone temporaire.")

        # 2) grille (PostGIS construit les carrés à partir de l'identifiant)
        if geo:
            cur.execute("""
                INSERT INTO grid_cells (cell_id, geom, resolution_deg)
                SELECT cell_id,
                       ST_MakeEnvelope(lon, lat, lon + %(r)s, lat + %(r)s, 4326), %(r)s
                FROM (SELECT DISTINCT cell_id,
                             (cell_id %% 100000) * %(r)s - 180.0 AS lon,
                             (cell_id / 100000) * %(r)s - 90.0  AS lat FROM stg) s
                ON CONFLICT (cell_id) DO UPDATE SET geom = EXCLUDED.geom,
                                                   resolution_deg = EXCLUDED.resolution_deg""",
                        {"r": res})
        else:
            # carré de taille_m dans la projection, découpé en petits segments (les côtés sont
            # légèrement courbes en lat/lon), puis converti en WGS84
            cur.execute("""
                INSERT INTO grid_cells (cell_id, geom, resolution_deg)
                SELECT cell_id,
                       ST_Transform(ST_Segmentize(ST_MakeEnvelope(gx * %(t)s, gy * %(t)s,
                                    (gx + 1) * %(t)s, (gy + 1) * %(t)s), %(t)s / 2),
                                    %(proj)s, 4326),
                       %(t)s / 111320.0
                FROM (SELECT DISTINCT cell_id,
                             (cell_id %% %(b)s) - %(dec)s AS gx,
                             (cell_id / %(b)s) - %(dec)s AS gy FROM stg) s
                ON CONFLICT (cell_id) DO UPDATE SET geom = EXCLUDED.geom,
                                                   resolution_deg = EXCLUDED.resolution_deg""",
                        {"t": a.taille_m, "proj": a.proj, "b": BASE, "dec": DEC})
        nb_cellules = cur.rowcount

        # 3) activité journalière : Postgres additionne
        cur.execute("""
            INSERT INTO daily_activity (cell_id, day, count_raw, count_harmonized, frp_sum)
            SELECT cell_id, day, SUM(raw)::int, SUM(cnt), SUM(frp) FROM stg GROUP BY cell_id, day""")
        nb_jours = cur.rowcount
        print(f"grid_cells : {nb_cellules:,} ; daily_activity : {nb_jours:,} lignes")

        # 4) climatologie, par blocs de cellules
        nb_clim = 0
        d0, d1 = cur.execute("SELECT MIN(day), MAX(day) FROM daily_activity").fetchone()
        jours = None
        if a.jours_couverts:
            cov = pd.read_csv(a.jours_couverts)
            jours = pd.to_datetime(cov.loc[cov["source"] != "aucune", "day"])
            print(f"couverture : {len(jours):,} jours couverts, "
                  f"{(cov['source'] == 'aucune').sum():,} jour(s) sans donnée (exclus de la climatologie)")
        if not a.sans_climatologie:
            ids = [r[0] for r in cur.execute(
                "SELECT DISTINCT cell_id FROM daily_activity ORDER BY 1").fetchall()]
            for i in range(0, len(ids), 2000):
                bloc = ids[i:i + 2000]
                rows = cur.execute("SELECT cell_id, day, count_harmonized FROM daily_activity "
                                   "WHERE cell_id = ANY(%s)", (bloc,)).fetchall()
                act = pd.DataFrame(rows, columns=["cell_id", "day", "count_harmonized"])
                act["day"] = pd.to_datetime(act["day"])
                act = act.set_index(["cell_id", "day"]).sort_index()
                clim, annees = climatologie(act, pd.Timestamp(d0), pd.Timestamp(d1), a.min_annees, jours)
                if clim is None:
                    print(f"Climatologie NON écrite : {annees} année(s), minimum {a.min_annees}.")
                    break
                with cur.copy("COPY climatology (cell_id, doy, mean_count, median_count, p90_count,"
                              " years_used) FROM STDIN") as cp:
                    for r in clim.itertuples(index=False):
                        cp.write_row((int(r.cell_id), int(r.doy), float(r.mean_count),
                                      float(r.median_count), float(r.p90_count), int(r.years_used)))
                nb_clim += len(clim)
            print(f"climatology : {nb_clim:,} lignes")

        for table, k in (("grid_cells", nb_cellules), ("daily_activity", nb_jours),
                         ("climatology", nb_clim)):
            cur.execute("INSERT INTO import_log (dataset, row_count, note) VALUES (%s, %s, %s)",
                        (table, k, f"import parquet ({os.path.basename(a.parquet)})"))
        cur.execute("SELECT refresh_fire_aggregates()")
        conn.commit()
    print("Terminé. Vérifie : /meta puis /calendar sur une zone.")


if __name__ == "__main__":
    main()
