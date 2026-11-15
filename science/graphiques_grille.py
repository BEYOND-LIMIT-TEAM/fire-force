"""
Graphiques à partir des fichiers .parquet de la grille 30 km (remplace plot_firms.py).
Réutilise le style et les fonctions de plot_firms.py (garde les deux fichiers dans le même dossier).

Écrit dans --out :
  serie_journaliere.png            détections et FRP par jour, une courbe par série
  calendrier_SERIE_AAAA.png        calendrier mois x jour, une image par série et par année
  carte_densite_SERIE.png          détections par cellule de 30 km (échelle log), cellules
                                   persistantes entourées
  agregat_jour_serie.csv           la table qui a servi aux graphiques (acq_date, sensor, nb_feux, frp_total)

Exemple :
  python graphiques_grille.py --source MODIS=modis_daily_grid_30km.parquet --out sortie_graphiques
"""
import argparse
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import plot_firms as pf
from donnees_grille import ajouter_options, lire_toutes, parse_sources

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#eda100", "#e87ba4"]


def carte(d, label, jours_persistants, out, taille_km=30):
    cel = d.groupby(["grid_x", "grid_y"]).agg(total=("count", "sum"), jours=("day", "nunique")).reset_index()
    x0, x1, y0, y1 = cel.grid_x.min(), cel.grid_x.max(), cel.grid_y.min(), cel.grid_y.max()
    img = np.full((y1 - y0 + 1, x1 - x0 + 1), np.nan)
    img[cel.grid_y - y0, cel.grid_x - x0] = cel["total"]
    fig, ax = plt.subplots(figsize=(8.5, 8.5 * (y1 - y0 + 1) / (x1 - x0 + 1) + 0.6))
    im = ax.imshow(np.ma.masked_invalid(img), cmap=pf.SEQ, origin="lower",
                   extent=[x0 * taille_km, (x1 + 1) * taille_km, y0 * taille_km, (y1 + 1) * taille_km],
                   norm=pf.LogNorm(vmin=1, vmax=max(float(cel["total"].max()), 2.0)), interpolation="nearest")
    pers = cel[cel["jours"] >= jours_persistants]
    if len(pers):
        ax.scatter((pers.grid_x + .5) * taille_km, (pers.grid_y + .5) * taille_km, s=40, facecolors="none",
                   edgecolors="#eb6834", linewidths=1.3, zorder=4)
        ax.legend(handles=[Line2D([], [], marker="o", ls="", markerfacecolor="none", markeredgecolor="#eb6834",
                                  markeredgewidth=1.4, markersize=8,
                                  label=f"Active ≥ {jours_persistants} jours (source fixe possible)")],
                  frameon=False, loc="lower left", fontsize=9)
    ax.set_xlabel("km est-ouest (projection Africa Albers, surfaces égales)")
    ax.set_ylabel("km nord-sud")
    pf.style_ax(ax, grid_axis=None)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("Détections sur la période (échelle logarithmique)", color=pf.INK2)
    cb.outline.set_visible(False)
    fig.suptitle(f"Densité des feux actifs par cellule de {taille_km} km ({label})", x=0.08, ha="left",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return len(pers)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ajouter_options(ap)
    ap.add_argument("--jours-persistants", type=int, default=150)
    ap.add_argument("--out", default="sortie_graphiques")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    col = dict(x=a.col_x, y=a.col_y, date=a.col_date, count=a.col_count, frp=a.col_frp)
    series = lire_toutes(parse_sources(a.source), col)

    for i, lab in enumerate(series):                 # une couleur par série
        pf.SERIES[lab] = PALETTE[i % len(PALETTE)]
    agg = pd.concat([
        d.groupby("day").agg(nb_feux=("count", "sum"), frp_total=("frp_sum", "sum")).reset_index()
         .assign(sensor=lab, acq_date=lambda t: t["day"].dt.strftime("%Y-%m-%d"))
        [["acq_date", "sensor", "nb_feux", "frp_total"]] for lab, d in series.items()])
    agg.to_csv(os.path.join(a.out, "agregat_jour_serie.csv"), index=False)

    jour = pf.plot_series(agg, os.path.join(a.out, "serie_journaliere.png"), fill=np.nan)  # trou = vide, pas 0
    for lab, s in jour.items():                       # une série à la fois : jamais de somme non harmonisée
        for annee in sorted(s.index.year.unique()):
            if (s.index.year == annee).sum() < 28:
                print(f"Calendrier {annee} ({lab}) ignoré : moins de 28 jours de données.")
                continue
            pf.plot_calendar(s["nb_feux"], lab, annee, os.path.join(a.out, f"calendrier_{lab}_{annee}.png"))
    for lab, d in series.items():
        n = carte(d, lab, a.jours_persistants, os.path.join(a.out, f"carte_densite_{lab}.png"))
        print(f"{lab} : {n} cellule(s) active(s) >= {a.jours_persistants} jours")
    print(f"\nFichiers écrits dans : {a.out}/")


if __name__ == "__main__":
    main()
