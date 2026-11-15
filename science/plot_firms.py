"""
Agrégation + premiers graphiques à partir des CSV FIRMS (VIIRS et/ou MODIS).

Ce script fait DEUX choses :
  1) Il construit la table agrégée  (jour x cellule x capteur)  ->  agregat_jour_cellule.csv
     C'est la table à transmettre au rôle 1 (données) et au rôle 3 (API).
  2) Il dessine 3 graphiques d'exploration (PNG) à partir de cette table :
       - serie_journaliere.png   : nombre de feux et FRP total par jour
       - calendrier_AAAA.png     : calendrier des feux (mois x jour), une image par année
       - carte_densite.png       : nombre de détections par cellule de 0,25 degré

Les CSV mondiaux sont énormes : lecture par morceaux, jamais tout en mémoire.
Par défaut les détections de FAIBLE confiance sont exclues (--garder-faible pour les inclure).

Exemples :
  python plot_firms.py --viirs fire_nrt_J2V-C2_819212.csv --bbox 8.5 1.6 16.2 13.1
  python plot_firms.py --viirs a.csv b.csv --modis m.csv --bbox 8.5 1.6 16.2 13.1

Dépendances : pandas, numpy, matplotlib   (pip install pandas numpy matplotlib)
"""
import argparse
import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.colors import LinearSegmentedColormap, PowerNorm, LogNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

CHUNK = 500_000
CELL = 0.25  # taille de la cellule de grille, en degrés
USECOLS = {"latitude", "longitude", "acq_date", "confidence", "frp", "satellite"}

# --- Style (palette de référence : bleu = capteur 1, orange = capteur 2) -------------
SURFACE, INK, INK2 = "#fcfcfb", "#0b0b0b", "#52514e"
GRID, AXIS, NODATA = "#e4e3df", "#c9c8c3", "#dcdbd6"
SERIES = {"VIIRS": "#2a78d6", "MODIS": "#eb6834"}
RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SEQ = LinearSegmentedColormap.from_list("bleu_seq", RAMP)
SEQ.set_bad(NODATA)
MOIS = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]

plt.rcParams.update({
    "font.size": 10, "text.color": INK, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
})


def style_ax(ax, grid_axis="y"):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(length=3, color=AXIS)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, lw=0.8)
        ax.set_axisbelow(True)


# ------------------------------------------------------------------ 1) agrégation ----
def load(path, sensor, bbox, keep_low, parts):
    total = kept = n_low = 0
    for chunk in pd.read_csv(path, chunksize=CHUNK,
                             usecols=lambda c: c.strip().lower() in USECOLS):
        chunk.columns = [c.strip().lower() for c in chunk.columns]
        missing = [c for c in ("latitude", "longitude", "acq_date", "confidence", "frp")
                   if c not in chunk.columns]
        if missing:
            raise SystemExit(f"{path} : colonnes manquantes {missing}")
        total += len(chunk)
        if bbox:
            w, s, e, n = bbox
            chunk = chunk[chunk["longitude"].between(w, e) & chunk["latitude"].between(s, n)]
        if chunk.empty:
            continue
        conf = chunk["confidence"]
        if sensor == "MODIS":
            low = pd.to_numeric(conf, errors="coerce") < 30
        else:
            low = conf.astype(str).str.strip().str.lower().str[0].eq("l")
        n_low += int(low.sum())
        if not keep_low:
            chunk = chunk[~low]
        if chunk.empty:
            continue
        kept += len(chunk)
        sat = chunk["satellite"].astype(str) if "satellite" in chunk else sensor
        chunk = chunk.assign(
            satellite=sat, sensor=sensor,
            acq_date=chunk["acq_date"].astype(str).str[:10],
            cell_lat=(np.floor(chunk["latitude"] / CELL) * CELL).round(2),
            cell_lon=(np.floor(chunk["longitude"] / CELL) * CELL).round(2))
        parts.append(chunk.groupby(
            ["acq_date", "sensor", "satellite", "cell_lat", "cell_lon"])
            .agg(nb_feux=("frp", "size"), frp_total=("frp", "sum")).reset_index())
    print(f"[{sensor}] {os.path.basename(path)} : {total:,} lignes lues, "
          f"{kept:,} retenues ({n_low:,} de faible confiance dans la zone)")


# ------------------------------------------------------------------ 2) graphiques ----
def plot_series(agg, out, fill=0):
    daily = agg.groupby(["acq_date", "sensor"]).agg(
        nb_feux=("nb_feux", "sum"), frp_total=("frp_total", "sum")).reset_index()
    daily["acq_date"] = pd.to_datetime(daily["acq_date"])
    sensors = sorted(daily["sensor"].unique())
    series = {}
    for s in sensors:  # jours sans détection = 0, mais seulement DANS la période du capteur
        d = daily[daily["sensor"] == s].set_index("acq_date")[["nb_feux", "frp_total"]]
        series[s] = d.reindex(pd.date_range(d.index.min(), d.index.max()), fill_value=fill)

    fig, axes = plt.subplots(2, 1, figsize=(11, 6.8), sharex=True)
    specs = [("nb_feux", "Détections par jour"), ("frp_total", "FRP total par jour (MW)")]
    for ax, (col, ylabel) in zip(axes, specs):
        for s in sensors:
            d = series[s][col]
            ax.plot(d.index, d.values, color=SERIES.get(s, INK2), lw=0.7, alpha=0.35)
            ax.plot(d.index, d.rolling(7, center=True, min_periods=4).mean(),
                    color=SERIES.get(s, INK2), lw=2)
        ax.set_ylabel(ylabel)
        ax.set_ylim(bottom=0)
        ax.ticklabel_format(axis="y", style="plain")
        style_ax(ax)
    if len(sensors) > 1:
        axes[0].legend(handles=[Line2D([], [], color=SERIES.get(s, INK2), lw=2, label=s)
                                for s in sensors], frameon=False, loc="upper center",
                       ncol=len(sensors))
    span = (max(d.index.max() for d in series.values())
            - min(d.index.min() for d in series.values())).days
    if span <= 400:   # une année : un repère par mois, en français
        axes[1].xaxis.set_major_locator(mdates.MonthLocator())
        axes[1].xaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: MOIS[mdates.num2date(x).month - 1]))
    else:             # plusieurs années : un repère par année
        axes[1].xaxis.set_major_locator(mdates.YearLocator(base=max(1, span // 365 // 10 + 1)))
        axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    if len(sensors) > 1:
        titre = "Feux actifs détectés par jour"
    else:
        titre = f"Feux actifs détectés par jour ({sensors[0]})"
    fig.suptitle(titre, x=0.07, ha="left", fontsize=13, fontweight="bold")
    fig.text(0.07, 0.925, "Trait fin : valeur journalière  ·  trait épais : moyenne sur 7 jours",
             fontsize=9, color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return series


def plot_calendar(count, sensor, year, out):
    s = count[count.index.year == year]
    grid = np.full((12, 31), np.nan)
    for d, v in s.items():
        grid[d.month - 1, d.day - 1] = v
    vmax = max(float(np.nanmax(grid)), 1.0)

    fig, ax = plt.subplots(figsize=(11, 5.4))
    im = ax.imshow(np.ma.masked_invalid(grid), cmap=SEQ, aspect="auto",
                   norm=PowerNorm(0.5, vmin=0, vmax=vmax), interpolation="nearest")
    # jours qui n'existent pas (30 fév., 31 avr., ...) : on les efface
    for m in range(12):
        for d in range(31):
            try:
                pd.Timestamp(year, m + 1, d + 1)
            except ValueError:
                ax.add_patch(Rectangle((d - .5, m - .5), 1, 1, color=SURFACE, lw=0, zorder=3))
    ax.set_xticks(range(31), [str(i) for i in range(1, 32)], fontsize=8)
    ax.set_yticks(range(12), MOIS)
    ax.set_xticks(np.arange(-.5, 31, 1), minor=True)
    ax.set_yticks(np.arange(-.5, 12, 1), minor=True)
    ax.grid(which="minor", color=SURFACE, lw=1.6)
    ax.tick_params(which="both", length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_xlabel("Jour du mois")
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cands = [0, 10, 50, 100, 500, 1000, 2000, 3000, 5000, 10000, 20000, 50000]
    cb.set_ticks([t for t in cands if t <= vmax])
    cb.set_label("Détections par jour (échelle en racine carrée)", color=INK2)
    cb.outline.set_visible(False)
    fig.suptitle(f"Calendrier des feux actifs {year} ({sensor})", x=0.07, ha="left",
                 fontsize=13, fontweight="bold")
    fig.text(0.07, 0.915, "Gris : pas de données pour ce jour", fontsize=9, color=INK2)
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    fig.savefig(out, dpi=150)
    plt.close(fig)


def plot_map(agg, persist_days, out):
    cells = agg.groupby(["cell_lat", "cell_lon"]).agg(
        total=("nb_feux", "sum"), jours=("acq_date", "nunique")).reset_index()
    lat0, lat1 = cells["cell_lat"].min(), cells["cell_lat"].max()
    lon0, lon1 = cells["cell_lon"].min(), cells["cell_lon"].max()
    ny, nx = int(round((lat1 - lat0) / CELL)) + 1, int(round((lon1 - lon0) / CELL)) + 1
    img = np.full((ny, nx), np.nan)
    iy = np.round((cells["cell_lat"] - lat0) / CELL).astype(int)
    ix = np.round((cells["cell_lon"] - lon0) / CELL).astype(int)
    img[iy, ix] = cells["total"]

    # largeur de la figure adaptée à la forme de la zone (évite les grands vides)
    r = ((lon1 + CELL - lon0) * np.cos(np.radians((lat0 + lat1) / 2))
         / max(lat1 + CELL - lat0, CELL))
    fig, ax = plt.subplots(figsize=(float(np.clip(2.8 + 6.4 * r, 6.0, 14.0)), 7.5))
    im = ax.imshow(np.ma.masked_invalid(img), cmap=SEQ, origin="lower",
                   extent=[lon0, lon1 + CELL, lat0, lat1 + CELL],
                   norm=LogNorm(vmin=1, vmax=max(float(cells["total"].max()), 2.0)),
                   interpolation="nearest")
    ax.set_aspect(1 / np.cos(np.radians((lat0 + lat1) / 2)))
    pers = cells[cells["jours"] >= persist_days]
    handles = []
    if len(pers):
        ax.scatter(pers["cell_lon"] + CELL / 2, pers["cell_lat"] + CELL / 2, s=70,
                   facecolors="none", edgecolors="#eb6834", linewidths=1.6, zorder=4)
        handles.append(Line2D([], [], marker="o", ls="", markerfacecolor="none",
                              markeredgecolor="#eb6834", markeredgewidth=1.6, markersize=8,
                              label=f"Active ≥ {persist_days} jours (source fixe possible)"))
        ax.legend(handles=handles, frameon=False, loc="lower left", fontsize=9)
    ax.set_xlabel("Longitude (°)")
    ax.set_ylabel("Latitude (°)")
    style_ax(ax, grid_axis=None)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("Détections sur la période (échelle logarithmique)", color=INK2)
    cb.outline.set_visible(False)
    fig.suptitle(f"Densité des feux actifs par cellule de {CELL}°", x=0.08, ha="left",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return len(pers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--viirs", nargs="+", default=[], help="un ou plusieurs CSV VIIRS")
    ap.add_argument("--modis", nargs="+", default=[], help="un ou plusieurs CSV MODIS")
    ap.add_argument("--bbox", nargs=4, type=float, default=None,
                    metavar=("OUEST", "SUD", "EST", "NORD"))
    ap.add_argument("--garder-faible", action="store_true",
                    help="inclure les détections de faible confiance")
    ap.add_argument("--jours-persistants", type=int, default=150,
                    help="seuil d'alerte 'source fixe' pour la carte (défaut 150)")
    ap.add_argument("--out", default="sortie_graphiques")
    a = ap.parse_args()
    if not (a.viirs or a.modis):
        raise SystemExit("Donnez au moins un fichier avec --viirs ou --modis.")
    os.makedirs(a.out, exist_ok=True)

    parts = []
    for p in a.viirs:
        load(p, "VIIRS", a.bbox, a.garder_faible, parts)
    for p in a.modis:
        load(p, "MODIS", a.bbox, a.garder_faible, parts)
    if not parts:
        raise SystemExit("Aucune détection retenue (zone trop petite ou fichiers vides).")

    keys = ["acq_date", "sensor", "satellite", "cell_lat", "cell_lon"]
    agg = pd.concat(parts).groupby(keys, as_index=False).sum()
    agg.to_csv(os.path.join(a.out, "agregat_jour_cellule.csv"), index=False)
    print(f"\nTable agrégée : {len(agg):,} lignes (jour x cellule x capteur x satellite)")

    series = plot_series(agg, os.path.join(a.out, "serie_journaliere.png"))

    # Le calendrier n'additionne jamais deux capteurs (non harmonisés) : un capteur à la fois.
    for sensor, d in series.items():
        for year in sorted(d.index.year.unique()):
            if (d.index.year == year).sum() < 28:
                print(f"Calendrier {year} ({sensor}) ignoré : moins de 28 jours de données.")
                continue
            name = f"calendrier_{year}.png" if len(series) == 1 else f"calendrier_{sensor}_{year}.png"
            plot_calendar(d["nb_feux"], sensor, year, os.path.join(a.out, name))

    n_p = plot_map(agg, a.jours_persistants, os.path.join(a.out, "carte_densite.png"))
    print(f"Cellules actives >= {a.jours_persistants} jours : {n_p}")
    print(f"\nFichiers écrits dans : {a.out}/")


if __name__ == "__main__":
    main()
