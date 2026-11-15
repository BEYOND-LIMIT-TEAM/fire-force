"""
Exploration des fichiers .parquet de la grille 30 km (remplace explore_firms.py).

Pour chaque série (MODIS, VIIRS S-NPP, ...) : volume, période, trous de données, cellules
persistantes (sources fixes possibles) ; puis la comparaison de chaque série à la série de
référence, sur la période et les jours communs.

Exemple :
  python explorer_grille.py --source MODIS=modis_daily_grid_30km.parquet \
      --source VIIRS_SNPP=viirs_snpp.parquet --reference VIIRS_SNPP --out sortie_exploration

Fichiers écrits dans --out :
  resume_series.csv          une ligne par série (période, lignes, cellules, détections, FRP)
  rapport_mensuel.csv        détections par mois et par série
  trous_de_donnees.csv       jours sans aucune ligne dans la période d'une série
  cellules_persistantes.csv  cellules actives >= N jours (série, grid_x, grid_y, jours_actifs, lon, lat)
  comparaison_mensuelle.csv  rapport entre séries par mois (période commune)
  comparaison_cellules.csv   rapport par cellule (quantiles) entre séries
"""
import argparse
import os

import numpy as np
import pandas as pd

from donnees_grille import ajouter_options, centre_lonlat, lire_toutes, parse_sources


def trous(jours, label):
    """Plages de jours sans aucune ligne entre le premier et le dernier jour de la série."""
    tous = pd.date_range(jours.min(), jours.max())
    manq = tous.difference(pd.DatetimeIndex(jours.unique()))
    if len(manq) == 0:
        return []
    grp = (manq.to_series().diff().dt.days != 1).cumsum()
    return [(label, g.index.min().date(), g.index.max().date(), len(g))
            for _, g in manq.to_series().groupby(grp.values)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ajouter_options(ap)
    ap.add_argument("--reference", default=None, help="étiquette de la série de référence")
    ap.add_argument("--jours-persistants", type=int, default=150)
    ap.add_argument("--min-detections-cellule", type=int, default=30,
                    help="comparaison par cellule : minimum de détections dans les deux séries")
    ap.add_argument("--out", default="sortie_exploration")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    col = dict(x=a.col_x, y=a.col_y, date=a.col_date, count=a.col_count, frp=a.col_frp)
    series = lire_toutes(parse_sources(a.source), col)
    ref = a.reference or next(iter(series))
    if ref not in series:
        raise SystemExit(f"--reference {ref} inconnue. Séries : {list(series)}")

    # 1) résumé
    lignes, tr, mens, pers = [], [], {}, []
    for lab, d in series.items():
        lignes.append(dict(serie=lab, premier_jour=d["day"].min().date(), dernier_jour=d["day"].max().date(),
                           lignes=len(d), cellules=d[["grid_x", "grid_y"]].drop_duplicates().shape[0],
                           detections=d["count"].sum(), frp_total=d["frp_sum"].sum(),
                           frp_par_detection=d["frp_sum"].sum() / max(d["count"].sum(), 1)))
        tr += trous(d["day"], lab)
        mens[lab] = d.groupby(d["day"].dt.to_period("M"))["count"].sum()
        act = d.groupby(["grid_x", "grid_y"])["day"].nunique().rename("jours_actifs").reset_index()
        act = act[act["jours_actifs"] >= a.jours_persistants].assign(serie=lab)
        pers.append(act)
    resume = pd.DataFrame(lignes)
    print("=== Séries ===")
    print(resume.round(2).to_string(index=False))
    resume.to_csv(os.path.join(a.out, "resume_series.csv"), index=False)

    rapport = pd.DataFrame(mens).fillna(0)
    rapport.index = rapport.index.astype(str)
    rapport.to_csv(os.path.join(a.out, "rapport_mensuel.csv"), index_label="mois")
    print("\n=== Détections par mois (repérer les trous) ===")
    print(rapport.astype(int).to_string())

    t = pd.DataFrame(tr, columns=["serie", "debut", "fin", "nb_jours"])
    t.to_csv(os.path.join(a.out, "trous_de_donnees.csv"), index=False)
    print(f"\n=== Trous de données : {len(t)} plage(s) sans aucune ligne ===")
    if len(t):
        print(t.head(15).to_string(index=False))

    p = pd.concat(pers) if pers else pd.DataFrame()
    if len(p):
        lon, lat = centre_lonlat(p["grid_x"], p["grid_y"])
        p["lon_centre"], p["lat_centre"] = lon, lat
    p.to_csv(os.path.join(a.out, "cellules_persistantes.csv"), index=False)
    print(f"\n=== Cellules actives >= {a.jours_persistants} jours : {len(p)} "
          "(candidates : torchères, industries, volcans) ===")

    # 2) comparaison avec la référence
    rd = series[ref]
    cm, cc = [], []
    for lab, d in series.items():
        if lab == ref:
            continue
        deb, fin = max(rd["day"].min(), d["day"].min()), min(rd["day"].max(), d["day"].max())
        if deb > fin:
            print(f"\n{lab} / {ref} : aucune période commune.")
            continue
        r, o = rd[rd["day"].between(deb, fin)], d[d["day"].between(deb, fin)]
        jr = r.groupby("day")[["count", "frp_sum"]].sum().reindex(pd.date_range(deb, fin), fill_value=0)
        jo = o.groupby("day")[["count", "frp_sum"]].sum().reindex(pd.date_range(deb, fin), fill_value=0)
        print(f"\n=== {lab} comparée à {ref} ({deb.date()} -> {fin.date()}, {len(jr)} jours) ===")
        print(f"Corrélation des comptes journaliers   : {jr['count'].corr(jo['count']):.3f}")
        print(f"Corrélation des comptes hebdomadaires : "
              f"{jr['count'].resample('W').sum().corr(jo['count'].resample('W').sum()):.3f}")
        print(f"Corrélation du FRP total journalier   : {jr['frp_sum'].corr(jo['frp_sum']):.3f}")
        print(f"Rapport des comptes {lab}/{ref} : {jo['count'].sum() / max(jr['count'].sum(), 1):.2f}   "
              f"rapport des FRP : {jo['frp_sum'].sum() / max(jr['frp_sum'].sum(), 1):.2f}")
        m = pd.DataFrame({ref: jr["count"].groupby(jr.index.to_period("M")).sum(),
                          lab: jo["count"].groupby(jo.index.to_period("M")).sum()})
        m["rapport"] = (m[lab] / m[ref].where(m[ref] > 0)).round(2)
        m.index = m.index.astype(str)
        cm.append(m.reset_index().rename(columns={"index": "mois"}).assign(ref=ref, autre=lab)
                  [["ref", "autre", "mois", ref, lab, "rapport"]].rename(columns={ref: "n_ref", lab: "n_autre"}))
        print("Rapport par mois :\n" + m["rapport"].describe().round(2).to_string())
        # par cellule
        cr = r.groupby(["grid_x", "grid_y"])["count"].sum().rename("n_ref")
        co = o.groupby(["grid_x", "grid_y"])["count"].sum().rename("n_autre")
        c = pd.concat([cr, co], axis=1).fillna(0)
        c = c[(c["n_ref"] >= a.min_detections_cellule) & (c["n_autre"] >= a.min_detections_cellule)]
        if len(c):
            q = (c["n_autre"] / c["n_ref"]).quantile([.1, .25, .5, .75, .9])
            cc.append(pd.DataFrame({"ref": ref, "autre": lab, "cellules": len(c),
                                    **{f"q{int(k * 100)}": [v] for k, v in q.items()}}))
            print(f"Rapport par cellule ({len(c)} cellules) : médiane {q[.5]:.2f}, "
                  f"de {q[.1]:.2f} (10 %) à {q[.9]:.2f} (90 %)  -> un rapport très dispersé = "
                  "facteur unique insuffisant")
    if cm:
        pd.concat(cm).to_csv(os.path.join(a.out, "comparaison_mensuelle.csv"), index=False)
    if cc:
        pd.concat(cc).to_csv(os.path.join(a.out, "comparaison_cellules.csv"), index=False)
    print(f"\nFichiers écrits dans : {a.out}/")


if __name__ == "__main__":
    main()
