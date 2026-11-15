"""
Charge la sortie du rôle 2 dans la base PostGIS du rôle 3 (projet Fire Force).

Entrée : agregat_jour_cellule.csv, produit par plot_firms.py
         (colonnes : acq_date, sensor, satellite, cell_lat, cell_lon, nb_feux, frp_total)

Sortie : les tables que le rôle 3 attend du rôle 2
  - grid_cells      la grille (une cellule = un carré de RESOLUTION degrés)
  - daily_activity  une ligne par cellule et par jour (count_raw, count_harmonized, frp_sum)
  - climatology     l'habitude par cellule et par jour de l'année (moyenne, médiane, p90)
  - import_log      une ligne par table chargée, puis rafraîchissement des mois

>>> ATTENTION : la fonction harmoniser() ci-dessous est un PLACEHOLDER. <<<
La vraie harmonisation MODIS/VIIRS est le travail scientifique du rôle 2. Ici, par défaut, on
prend UN capteur de référence (VIIRS) comme chiffre "comparable". C'est cohérent dans le temps
tant qu'on reste sur ce capteur, mais ça ne dit rien des jours où il n'existe pas : ces jours
sont exclus (ou remplacés par MODIS x un facteur si vous le demandez avec --facteur-secours).
Remplacez le corps de harmoniser() par votre méthode quand elle sera prête.

Exemples :
  # voir ce qui serait écrit, sans toucher à la base
  python charger_role2.py --agregat sortie_graphiques/agregat_jour_cellule.csv --dry-run

  # charger (la base doit tourner : docker compose up -d db)
  python charger_role2.py --agregat sortie_graphiques/agregat_jour_cellule.csv --remplacer

Dépendances : pandas, numpy, psycopg[binary]   (pip install pandas numpy "psycopg[binary]")
"""
import argparse
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

COLONNES = {"acq_date", "sensor", "satellite", "cell_lat", "cell_lon", "nb_feux", "frp_total"}


def cell_id(lat, lon, res):
    """Identifiant entier stable d'une cellule, calculé depuis son coin sud-ouest.
    Même cellule -> même identifiant, à chaque chargement et pour toute l'équipe."""
    i_lat = np.round((np.asarray(lat) + 90.0) / res).astype(np.int64)
    i_lon = np.round((np.asarray(lon) + 180.0) / res).astype(np.int64)
    return i_lat * 100_000 + i_lon


def harmoniser(df, capteur_ref, satellite_ref, facteur_secours):
    """PLACEHOLDER de l'harmonisation. Voir l'avertissement en tête de fichier.

    Entrée  : df avec cell_id, day, sensor, satellite, nb_feux, frp_total (un enregistrement
              par cellule, jour, capteur et satellite).
    Sortie  : (table, debut, fin)
              table = index (cell_id, day), colonnes count_raw, count_harmonized, frp_sum
              debut, fin = période où count_harmonized est fiable (sert à la climatologie).
    """
    ref = df[df["sensor"] == capteur_ref]
    if satellite_ref:
        ref = ref[ref["satellite"] == satellite_ref]
    if ref.empty:
        sys.exit(f"Aucune ligne pour la référence {capteur_ref}"
                 + (f"/{satellite_ref}" if satellite_ref else "") + " dans le fichier.")
    d0, d1 = ref["day"].min(), ref["day"].max()

    brut = df.groupby(["cell_id", "day"]).agg(count_raw=("nb_feux", "sum"))
    reference = ref.groupby(["cell_id", "day"]).agg(
        count_harmonized=("nb_feux", "sum"), frp_sum=("frp_total", "sum"))
    out = brut.join(reference, how="left")

    jours = out.index.get_level_values("day")
    dans_ref = (jours >= d0) & (jours <= d1)
    # Dans la période couverte par la référence, "pas de ligne" = vraiment 0 détection.
    out.loc[dans_ref, "count_harmonized"] = out.loc[dans_ref, "count_harmonized"].fillna(0)

    hors = ~dans_ref
    if hors.any():
        j = pd.Series(jours[hors]).drop_duplicates().sort_values()
        print(f"\n!! {j.nunique()} jour(s) hors de la période de la référence "
              f"({d0} -> {d1}) : du {j.iloc[0]} au {j.iloc[-1]}")
        if facteur_secours is not None:
            out.loc[hors, "count_harmonized"] = out.loc[hors, "count_raw"] * facteur_secours
            print(f"   remplacés par (détections brutes) x {facteur_secours}  <- À JUSTIFIER")
            d0, d1 = min(d0, j.iloc[0]), max(d1, j.iloc[-1])
        else:
            out = out[dans_ref]
            print("   exclus (aucune valeur comparable). Option : --facteur-secours")
    return out, d0, d1


def climatologie(act, debut, fin, min_annees, jours=None):
    """Habitude par cellule et par jour de l'année, à partir de count_harmonized.
    Un jour couvert mais sans ligne compte 0 ; un jour hors période compte pour rien.
    jours : (facultatif) liste des jours réellement couverts par une source. Si fournie, seuls
    ces jours comptent (un trou de données n'est pas confondu avec "0 feu")."""
    annees = np.arange(debut.year, fin.year + 1)
    dates = pd.DatetimeIndex(jours) if jours is not None else pd.date_range(debut, fin)
    cellules = np.sort(act.index.get_level_values("cell_id").unique().to_numpy())
    arr = np.full((len(cellules), len(annees), 366), np.nan, dtype=np.float32)
    arr[:, dates.year - annees[0], dates.day_of_year - 1] = 0.0

    ci = np.searchsorted(cellules, act.index.get_level_values("cell_id").to_numpy())
    jr = pd.DatetimeIndex(act.index.get_level_values("day"))
    arr[ci, jr.year - annees[0], jr.day_of_year - 1] = act["count_harmonized"].to_numpy()

    annees_dispo = (~np.isnan(arr)).sum(axis=1)            # (cellules, 366)
    if annees_dispo.max() < min_annees:
        return None, int(annees_dispo.max())
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            moy = np.nanmean(arr, axis=1)
            med = np.nanmedian(arr, axis=1)
            p90 = np.nanpercentile(arr, 90, axis=1)
    c, d = np.nonzero(annees_dispo > 0)
    return pd.DataFrame({
        "cell_id": cellules[c], "doy": d + 1, "mean_count": moy[c, d],
        "median_count": med[c, d], "p90_count": p90[c, d],
        "years_used": annees_dispo[c, d]}), int(annees_dispo.max())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--agregat", required=True, help="agregat_jour_cellule.csv")
    ap.add_argument("--db", default=os.environ.get(
        "DATABASE_URL", "postgresql://fireweb:fireweb@localhost:5432/fireweb"))
    ap.add_argument("--resolution", type=float, default=0.25,
                    help="taille des cellules en degrés (doit être celle de plot_firms.py)")
    ap.add_argument("--reference-sensor", default="VIIRS", help="capteur de référence (défaut VIIRS)")
    ap.add_argument("--reference-satellite", default=None,
                    help="un seul satellite de référence (ex. N pour Suomi-NPP). "
                         "Sinon tous les satellites du capteur sont additionnés.")
    ap.add_argument("--facteur-secours", type=float, default=None,
                    help="si fourni : jours sans référence = détections brutes x ce facteur")
    ap.add_argument("--min-annees", type=int, default=3,
                    help="années minimum pour écrire la climatologie (défaut 3)")
    ap.add_argument("--remplacer", action="store_true",
                    help="autorise à vider daily_activity et climatology avant de recharger")
    ap.add_argument("--dry-run", action="store_true", help="calcule et affiche, sans écrire")
    a = ap.parse_args()

    df = pd.read_csv(a.agregat)
    manque = COLONNES - set(df.columns)
    if manque:
        sys.exit(f"Colonnes manquantes dans {a.agregat} : {sorted(manque)}")
    df["day"] = pd.to_datetime(df["acq_date"]).dt.date
    df["cell_id"] = cell_id(df["cell_lat"], df["cell_lon"], a.resolution)
    print(f"{len(df):,} lignes lues ; capteurs : "
          + ", ".join(f"{s}/{t}" for s, t in df[['sensor', 'satellite']].drop_duplicates().itertuples(index=False)))
    if a.reference_satellite is None and df[df["sensor"] == a.reference_sensor]["satellite"].nunique() > 1:
        print(f"!! Plusieurs satellites {a.reference_sensor} sont additionnés : le nombre de satellites "
              "actifs change dans le temps (fausse tendance possible). Voir --reference-satellite.")

    act, d0, d1 = harmoniser(df, a.reference_sensor, a.reference_satellite, a.facteur_secours)
    act = act.reset_index()
    act["day"] = pd.to_datetime(act["day"])
    act["frp_sum"] = act["frp_sum"].astype(float)
    act = act.set_index(["cell_id", "day"]).sort_index()

    cells = df[["cell_id", "cell_lat", "cell_lon"]].drop_duplicates("cell_id")
    cells = cells[cells["cell_id"].isin(act.index.get_level_values("cell_id"))]
    clim, annees_max = climatologie(act, pd.Timestamp(d0), pd.Timestamp(d1), a.min_annees)

    print(f"\ngrid_cells     : {len(cells):,} cellules de {a.resolution}°")
    print(f"daily_activity : {len(act):,} lignes, du {act.index.get_level_values('day').min().date()} "
          f"au {act.index.get_level_values('day').max().date()}")
    if clim is None:
        print(f"climatology    : NON ÉCRITE ({annees_max} année(s) de données, minimum {a.min_annees}). "
              "Sans climatologie, /calendar renvoie expected = null et /anomalies ne classe rien.")
    else:
        print(f"climatology    : {len(clim):,} lignes ({annees_max} années au maximum)")
    if a.dry_run:
        print("\n--dry-run : rien n'a été écrit.")
        return

    import psycopg
    with psycopg.connect(a.db) as conn:
        cur = conn.cursor()
        existe = cur.execute("SELECT (SELECT COUNT(*) FROM daily_activity) + "
                             "(SELECT COUNT(*) FROM climatology)").fetchone()[0]
        if existe and not a.remplacer:
            sys.exit(f"\ndaily_activity/climatology contiennent déjà {existe:,} lignes. "
                     "Relancez avec --remplacer pour les vider d'abord.")
        cur.execute("DELETE FROM daily_activity")
        cur.execute("DELETE FROM climatology")
        res = a.resolution
        cur.executemany(
            "INSERT INTO grid_cells (cell_id, geom, resolution_deg) "
            "VALUES (%s, ST_MakeEnvelope(%s, %s, %s, %s, 4326), %s) "
            "ON CONFLICT (cell_id) DO UPDATE SET geom = EXCLUDED.geom, "
            "resolution_deg = EXCLUDED.resolution_deg",
            [(int(r.cell_id), float(r.cell_lon), float(r.cell_lat),
              float(r.cell_lon) + res, float(r.cell_lat) + res, res)
             for r in cells.itertuples(index=False)])
        with cur.copy("COPY daily_activity (cell_id, day, count_raw, count_harmonized, frp_sum) "
                      "FROM STDIN") as cp:
            for (cid, jour), r in act.iterrows():
                cp.write_row((int(cid), jour.date(), int(r.count_raw), float(r.count_harmonized),
                              None if pd.isna(r.frp_sum) else float(r.frp_sum)))
        if clim is not None:
            with cur.copy("COPY climatology (cell_id, doy, mean_count, median_count, p90_count, "
                          "years_used) FROM STDIN") as cp:
                for r in clim.itertuples(index=False):
                    cp.write_row((int(r.cell_id), int(r.doy), float(r.mean_count),
                                  float(r.median_count), float(r.p90_count), int(r.years_used)))
        for table, n in (("grid_cells", len(cells)), ("daily_activity", len(act)),
                         ("climatology", 0 if clim is None else len(clim))):
            cur.execute("INSERT INTO import_log (dataset, row_count, note) VALUES (%s, %s, %s)",
                        (table, n, "import rôle 2 (charger_role2.py)"))
        cur.execute("SELECT refresh_fire_aggregates()")
        conn.commit()
    print("\nChargement terminé, mois rafraîchis, cache invalidé (import_log).")


if __name__ == "__main__":
    main()
