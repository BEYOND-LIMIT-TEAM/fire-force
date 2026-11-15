"""
Construit la base analytique de Fire Force (un seul fichier DuckDB, interrogé en SQL).

Entrée : les parquet par capteur sur la grille 30 km (colonnes grid_x, grid_y, date, fire_count, frp_sum).
Sortie : fireforce.duckdb avec les tables
  sensors       capteurs, ordre de priorité, période, nombre de lignes
  cells         une ligne par cellule : centre et 4 coins en lon/lat
  sensor_daily  détections brutes par capteur, cellule et jour
  coverage      pour chaque jour : capteur retenu (ou 'aucune' = trou), facteur d'étalonnage
  daily         série HARMONISÉE : count_harmonized par cellule et jour
  calibration   facteurs d'étalonnage par capteur de secours et par mois
  meta          informations générales (jeu de données, période, méthode)

HARMONISATION (même méthode que science/harmonisation.py) :
  - le capteur de RÉFÉRENCE fait foi tous les jours où il a au moins une ligne ;
  - les jours manquants sont remplis par les capteurs de SECOURS, dans l'ordre, multipliés par un
    facteur mensuel = somme(référence) / somme(secours) sur les jours où les deux existent ;
    sous --min-detections-etalonnage détections dans un mois, on prend le facteur global ;
  - un jour sans aucun capteur est un TROU ('aucune'), jamais un jour à zéro feu.

Exemple :
  python build_db.py --source MODIS=synth/MODIS.parquet --source VIIRS_SNPP=synth/VIIRS_SNPP.parquet \\
      --source VIIRS_N20=synth/VIIRS_N20.parquet --source VIIRS_N21=synth/VIIRS_N21.parquet \\
      --reference VIIRS_SNPP --secours VIIRS_N20 VIIRS_N21 MODIS --sortie fireforce.duckdb --jeu demo
"""
import argparse, json, os, time
import duckdb, numpy as np, pandas as pd
from pyproj import Transformer

PROJ = "+proj=aea +lat_1=20 +lat_2=-23 +lat_0=0 +lon_0=25 +x_0=0 +y_0=0 +ellps=WGS84 +units=m"
DEC, BASE = 1000, 10000


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--source", action="append", required=True, help="LABEL=fichier.parquet (répétable)")
    ap.add_argument("--reference", required=True)
    ap.add_argument("--secours", nargs="*", default=[])
    ap.add_argument("--sortie", default="fireforce.duckdb")
    ap.add_argument("--taille-m", type=int, default=30000)
    ap.add_argument("--min-detections-etalonnage", type=int, default=200)
    ap.add_argument("--col-x", default="grid_x"); ap.add_argument("--col-y", default="grid_y")
    ap.add_argument("--col-date", default="date"); ap.add_argument("--col-count", default="fire_count")
    ap.add_argument("--col-frp", default="frp_sum")
    ap.add_argument("--cellules", help="parquet des cellules (grid_x, grid_y, lon, lat, lon0..3, lat0..3) : utilise la géométrie fournie au lieu de la projection")
    ap.add_argument("--jeu", default="firms", help="'demo' pour le jeu synthétique, sinon 'firms'")
    ap.add_argument("--remplacer", action="store_true")
    a = ap.parse_args()
    src = [s.split("=", 1) for s in a.source]
    labels = [l for l, _ in src]
    for l in [a.reference, *a.secours]:
        if l not in labels:
            raise SystemExit(f"Capteur inconnu : {l}. Capteurs : {labels}")
    if os.path.exists(a.sortie):
        if not a.remplacer:
            raise SystemExit(f"{a.sortie} existe déjà (utilise --remplacer)")
        os.remove(a.sortie)
    t0 = time.time()
    con = duckdb.connect(a.sortie)
    con.execute("SET memory_limit='5GB'; SET threads=2;")
    # ordre : référence, secours, puis les autres capteurs (utilisés seulement pour la confirmation)
    ordre = [a.reference, *a.secours, *[l for l in labels if l != a.reference and l not in a.secours]]
    chemin = dict(src)
    con.execute("CREATE TABLE stg(sensor_id TINYINT, cell_id INTEGER, day DATE, n INTEGER, frp FLOAT)")
    for sid, lab in enumerate(ordre):
        con.execute(f"""INSERT INTO stg SELECT {sid},
            (CAST({a.col_y} AS INTEGER)+{DEC})*{BASE}+(CAST({a.col_x} AS INTEGER)+{DEC}),
            CAST({a.col_date} AS DATE), CAST({a.col_count} AS INTEGER), CAST({a.col_frp} AS FLOAT)
            FROM read_parquet('{chemin[lab]}') WHERE {a.col_count} > 0""")
        print(f"{lab}: lu ({time.time()-t0:.0f}s)", flush=True)
    con.execute("CREATE TABLE sensor_daily AS SELECT * FROM stg ORDER BY cell_id, day, sensor_id")
    con.execute("DROP TABLE stg")
    con.execute("CREATE TABLE sensors(sensor_id TINYINT, name VARCHAR, role VARCHAR, first_day DATE, last_day DATE, n_rows BIGINT)")
    for sid, lab in enumerate(ordre):
        role = "référence" if lab == a.reference else ("secours" if lab in a.secours else "confirmation")
        con.execute(f"""INSERT INTO sensors SELECT {sid}, '{lab}', '{role}', min(day), max(day), count(*)
                        FROM sensor_daily WHERE sensor_id={sid}""")

    # --- cellules et géométrie
    ids = con.execute("SELECT DISTINCT cell_id FROM sensor_daily ORDER BY 1").fetchnumpy()["cell_id"].astype(np.int64)
    gx = ids % BASE - DEC; gy = ids // BASE - DEC
    T = a.taille_m
    inv = Transformer.from_crs(PROJ, 4326, always_xy=True)
    cx, cy = inv.transform((gx + 0.5) * T, (gy + 0.5) * T)
    cols = {"cell_id": ids.astype("int32"), "grid_x": gx.astype("int32"), "grid_y": gy.astype("int32"),
            "lon": np.round(cx, 4), "lat": np.round(cy, 4)}
    for k, (dx, dy) in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        lo, la = inv.transform((gx + dx) * T, (gy + dy) * T)
        cols[f"lon{k}"] = np.round(lo, 3); cols[f"lat{k}"] = np.round(la, 3)
    cells = pd.DataFrame(cols)
    if a.cellules:   # géométrie fournie (ex. export Neon) : elle remplace celle de la projection
        ext = pd.read_parquet(a.cellules).drop_duplicates(["grid_x", "grid_y"]).set_index(["grid_x", "grid_y"])
        key = pd.MultiIndex.from_arrays([cells["grid_x"], cells["grid_y"]])
        ok = key.isin(ext.index)
        for c in ["lon", "lat", *[f"lon{k}" for k in range(4)], *[f"lat{k}" for k in range(4)]]:
            cells.loc[ok, c] = ext.loc[key[ok], c].to_numpy()
        print(f"géométrie fournie pour {int(ok.sum())} cellules sur {len(cells)}", flush=True)
    con.register("cells_df", cells)
    con.execute("CREATE TABLE cells AS SELECT * FROM cells_df ORDER BY cell_id")
    print(f"{len(cells)} cellules ({time.time()-t0:.0f}s)", flush=True)

    # --- couverture et étalonnage (calculés sur ~5000 lignes, en pandas)
    tot = con.execute("SELECT sensor_id, day, sum(n) AS n FROM sensor_daily GROUP BY 1,2").df()
    tot["day"] = pd.to_datetime(tot["day"])
    piv = {ordre[s]: g.set_index("day")["n"] for s, g in tot.groupby("sensor_id")}
    jours = pd.date_range(tot["day"].min(), tot["day"].max())
    ref = piv[a.reference]
    rows_cal = []
    facteur = {a.reference: pd.Series(1.0, index=range(1, 13))}
    for s in a.secours:
        cs = piv[s]
        com = ref.index.intersection(cs.index)
        d = pd.DataFrame({"r": ref.loc[com], "s": cs.loc[com]})
        d["m"] = d.index.month
        g = d.groupby("m").agg(r=("r", "sum"), s=("s", "sum"), j=("r", "size"))
        glob = d["r"].sum() / d["s"].sum() if d["s"].sum() > 0 else 1.0
        f = {}
        for m in range(1, 13):
            if m in g.index and g.loc[m, "s"] >= a.min_detections_etalonnage:
                f[m] = g.loc[m, "r"] / g.loc[m, "s"]
            else:
                f[m] = glob
            rows_cal.append((s, m, float(f[m]), int(g.loc[m, "j"]) if m in g.index else 0,
                             int(g.loc[m, "s"]) if m in g.index else 0))
        facteur[s] = pd.Series(f)
        print(f"facteur {s}: " + " ".join(f"{f[m]:.2f}" for m in range(1, 13)))
    cal = pd.DataFrame(rows_cal, columns=["sensor", "month", "factor", "common_days", "secours_detections"])
    con.register("cal_df", cal)
    con.execute("CREATE TABLE calibration AS SELECT * FROM cal_df")
    prior = [a.reference, *a.secours]
    srcs, facs = [], []
    for j in jours:
        choix, fac = "aucune", np.nan
        for lab in prior:
            if j in piv[lab].index:
                choix, fac = lab, float(facteur[lab][j.month]); break
        srcs.append(choix); facs.append(fac)
    cov = pd.DataFrame({"day": jours.date, "source": srcs, "factor": facs})
    con.register("cov_df", cov)
    con.execute("CREATE TABLE coverage AS SELECT CAST(day AS DATE) AS day, source, factor FROM cov_df")
    n_trous = int((cov.source == "aucune").sum())
    print(f"{len(jours)} jours, {n_trous} sans donnée ({time.time()-t0:.0f}s)", flush=True)

    # --- série harmonisée
    con.execute("""CREATE TABLE daily AS
        SELECT d.cell_id, d.day, CAST(d.n * c.factor AS FLOAT) AS n_harm, d.frp AS frp, d.n AS n_raw, d.sensor_id AS sensor_id
        FROM sensor_daily d
        JOIN coverage c ON c.day = d.day
        JOIN sensors s ON s.sensor_id = d.sensor_id AND s.name = c.source
        ORDER BY d.cell_id, d.day""")
    nd = con.execute("SELECT count(*) FROM daily").fetchone()[0]
    meta = {"dataset": a.jeu, "first_day": str(jours[0].date()), "last_day": str(jours[-1].date()),
            "reference": a.reference, "secours": ",".join(a.secours), "grid_m": str(T), "proj": PROJ,
            "n_cells": str(len(cells)), "gap_days": str(n_trous), "built_at": pd.Timestamp.now().isoformat(timespec="seconds"),
            "schema_version": "1"}
    con.execute("CREATE TABLE meta(key VARCHAR, value VARCHAR)")
    con.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))
    con.execute("CHECKPOINT")
    print(f"daily: {nd} lignes. Terminé en {time.time()-t0:.0f}s. Taille : {os.path.getsize(a.sortie)/1e6:.0f} Mo")


if __name__ == "__main__":
    main()
