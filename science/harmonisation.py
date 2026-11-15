"""
Harmonisation MODIS / VIIRS sur la grille 30 km : produit UNE valeur comparable par cellule et par
jour (count_harmonized), prête pour parquet_vers_postgres.py.

MÉTHODE PAR DÉFAUT (simple, documentée, modifiable) :
  1. Une série de RÉFÉRENCE (--reference, ex. VIIRS_SNPP) fait foi chaque jour où elle existe.
     Un jour est "couvert" par une série s'il contient au moins une ligne de cette série.
  2. Les jours non couverts par la référence sont remplis par les séries de SECOURS (--secours,
     dans l'ordre de priorité), multipliées par un facteur d'étalonnage.
  3. Ce facteur est calculé sur les jours où référence ET secours existent : somme(référence) /
     somme(secours), séparément pour chacun des 12 mois du calendrier (le rapport VIIRS/MODIS n'est
     pas constant dans l'année). Un facteur par mois, valable pour toutes les cellules.
  4. Un jour couvert par aucune série n'a pas de ligne et est marqué 'aucune' dans
     couverture_jours.csv : c'est un TROU, pas un jour à zéro feu.

LIMITE à écrire dans le rapport : un facteur unique par mois ignore les différences entre régions
(voir comparaison_cellules.csv de explorer_grille.py). Si le rapport par cellule est très dispersé,
l'étape suivante est un facteur par zone climatique.

Exemple :
  python harmonisation.py --source MODIS=modis.parquet --source VIIRS_SNPP=snpp.parquet \
      --source VIIRS_N20=n20.parquet --reference VIIRS_SNPP --secours VIIRS_N20 MODIS \
      --sortie sortie_harmonisation

Écrit dans --sortie :
  harmonise.parquet     grid_x, grid_y, date, count_harmonized, count_raw, frp_sum, source
                        count_raw = comptage de la source utilisée AVANT étalonnage ;
                        frp_sum = FRP de la source utilisée (non étalonné)
  couverture_jours.csv  day, source utilisée ('aucune' = trou), facteur
  facteurs.csv          secours, mois, facteur, jours_communs, detections_secours
"""
import argparse
import os

import numpy as np
import pandas as pd

from donnees_grille import ajouter_options, lire_toutes, parse_sources


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ajouter_options(ap)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--secours", nargs="*", default=[], help="séries de secours, par priorité")
    ap.add_argument("--min-detections-etalonnage", type=int, default=200,
                    help="sous ce nombre de détections de secours dans un mois, on utilise le "
                         "facteur global au lieu du facteur du mois")
    ap.add_argument("--sortie", default="sortie_harmonisation")
    a = ap.parse_args()
    os.makedirs(a.sortie, exist_ok=True)
    col = dict(x=a.col_x, y=a.col_y, date=a.col_date, count=a.col_count, frp=a.col_frp)
    series = lire_toutes(parse_sources(a.source), col)
    for lab in [a.reference, *a.secours]:
        if lab not in series:
            raise SystemExit(f"Série inconnue : {lab}. Séries : {list(series)}")
    ref = series[a.reference]
    couv = {lab: set(d["day"].unique()) for lab, d in series.items()}

    # facteurs d'étalonnage des séries de secours
    facteurs, lignes = {}, []
    for lab in a.secours:
        communs = sorted(couv[a.reference] & couv[lab])
        if not communs:
            raise SystemExit(f"{lab} n'a aucun jour commun avec {a.reference} : étalonnage impossible.")
        jr = ref[ref["day"].isin(communs)].groupby("day")["count"].sum().reindex(communs, fill_value=0)
        js = series[lab]
        js = js[js["day"].isin(communs)].groupby("day")["count"].sum().reindex(communs, fill_value=0)
        df = pd.DataFrame({"ref": jr, "sec": js})
        global_f = df["ref"].sum() / max(df["sec"].sum(), 1)
        for m in range(1, 13):
            sub = df[df.index.month == m]
            ok = sub["sec"].sum() >= a.min_detections_etalonnage
            f = sub["ref"].sum() / sub["sec"].sum() if ok else global_f
            facteurs[(lab, m)] = f
            lignes.append(dict(secours=lab, mois=m, facteur=f, jours_communs=len(sub),
                               detections_secours=sub["sec"].sum(), facteur_global_utilise=not ok))
    pd.DataFrame(lignes).to_csv(os.path.join(a.sortie, "facteurs.csv"), index=False)
    if lignes:
        print("=== Facteurs d'étalonnage (référence / secours) par mois ===")
        print(pd.DataFrame(lignes).pivot(index="mois", columns="secours", values="facteur").round(3).to_string())

    # choix de la source de chaque jour
    tous = pd.DatetimeIndex(sorted(set().union(*couv.values())))
    plage = pd.date_range(tous.min(), tous.max())
    source_jour = {}
    for j in plage:
        for lab in [a.reference, *a.secours]:
            if j in couv[lab]:
                source_jour[j] = lab
                break
        else:
            source_jour[j] = "aucune"
    cov = pd.DataFrame({"day": plage, "source": [source_jour[j] for j in plage]})
    cov["facteur"] = [1.0 if s in (a.reference, "aucune") else facteurs[(s, j.month)]
                      for s, j in zip(cov["source"], plage)]
    cov.to_csv(os.path.join(a.sortie, "couverture_jours.csv"), index=False)
    print("\n=== Couverture : jours par source utilisée ===")
    print(cov["source"].value_counts().to_string())

    # assemblage cellule x jour
    morceaux = []
    for lab in [a.reference, *a.secours]:
        d = series[lab]
        jours_lab = cov.loc[cov["source"] == lab, "day"]
        d = d[d["day"].isin(jours_lab)].copy()
        if lab == a.reference:
            d["count_harmonized"] = d["count"]
        else:
            f = cov.set_index("day")["facteur"]
            d["count_harmonized"] = d["count"] * d["day"].map(f).to_numpy()
        d["count_raw"] = d["count"]
        d["source"] = lab
        morceaux.append(d[["grid_x", "grid_y", "day", "count_harmonized", "count_raw", "frp_sum", "source"]])
    out = pd.concat(morceaux, ignore_index=True)
    out["date"] = out["day"].dt.strftime("%Y-%m-%d")
    out = out.drop(columns="day")[["grid_x", "grid_y", "date", "count_harmonized", "count_raw", "frp_sum", "source"]]
    out.to_parquet(os.path.join(a.sortie, "harmonise.parquet"), index=False)
    print(f"\n{len(out):,} lignes écrites dans {a.sortie}/harmonise.parquet")
    trous = int((cov["source"] == "aucune").sum())
    if trous:
        print(f"!! {trous} jour(s) sans aucune source (trous) : à passer au chargeur avec "
              f"--jours-couverts {a.sortie}/couverture_jours.csv")


if __name__ == "__main__":
    main()
