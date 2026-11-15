"""
Anomalies d'une zone : classe chaque semaine comme normale, élevée ou critique et l'écrit dans la
table `anomalies` (l'API la renvoie alors telle quelle pour cette aoi).

MÉTHODE
  - Série de la zone : somme de count_harmonized sur les cellules de la zone (même règle que l'API).
  - Périodes : 52 semaines par an (semaine 52 = jusqu'au 31 décembre). Une période n'est retenue
    que si TOUS ses jours sont couverts (couverture_jours.csv, sinon toute la plage des données).
  - Référence : les MÊMES semaines des AUTRES années (l'année évaluée est exclue, sinon un pic
    se compare à lui-même). Il faut au moins --min-annees années comparables, sinon la période
    n'est pas classée (et n'est pas écrite).
  - expected = moyenne ; seuil "élevé" = percentile --q-eleve ; seuil "critique" = percentile
    --q-critique. La climatologie est calculée sur la SOMME de la zone (et non en additionnant des
    p90 de cellules, ce qui serait faux).
  - Plancher : sous --plancher détections sur la semaine, la période reste 'normal' (évite de
    classer "critique" 3 détections dans une zone presque sans feu).
  Ces seuils sont des choix scientifiques : à discuter et à justifier dans le rapport.

ZONES (une des trois) :
  --aoi-id 3                  une zone déjà enregistrée (table aoi)
  --bbox O S E N --nom Nom    crée une zone rectangulaire
  --geojson zones.geojson     FeatureCollection de polygones (nom = properties.name ou NAME)

Exemples :
  python anomalies_zone.py --bbox 8.5 1.6 16.2 13.1 --nom Cameroun --dry-run
  python anomalies_zone.py --geojson pays.geojson --couverture sortie_harmonisation/couverture_jours.csv

Limite à connaître : une zone dessinée librement par un utilisateur n'a pas de ligne dans
`anomalies` ; l'API applique alors sa règle provisoire. Cette méthode est faite pour les zones
prédéfinies (pays, régions) et pour être reprise telle quelle par le backend.
"""
import argparse
import json

import numpy as np
import pandas as pd

from acces_base import connexion, serie_observee

NB_SEM = 52


def periodes(jours_couverts, d0, d1):
    """Table (annee, sem, debut, fin, nb_attendus) et jours couverts de chaque période."""
    idx = pd.date_range(d0, d1)
    t = pd.DataFrame({"day": idx})
    t["annee"] = t["day"].dt.year
    t["doy"] = t["day"].dt.day_of_year
    t["sem"] = np.minimum((t["doy"] - 1) // 7, NB_SEM - 1)
    t["couvert"] = t["day"].isin(jours_couverts)
    return t


def calculer(serie, jours_couverts, d0, d1, min_annees, q_eleve, q_crit, plancher):
    serie = serie.assign(day=pd.to_datetime(serie["day"]))
    t = periodes(jours_couverts, d0, d1)
    s = serie.set_index("day")["observed"].reindex(pd.DatetimeIndex(t["day"]), fill_value=0.0)
    t["observed"] = s.to_numpy(dtype=float)
    g = t.groupby(["annee", "sem"]).agg(debut=("day", "min"), fin=("day", "max"), n=("day", "size"),
                                         couverts=("couvert", "sum"), observed=("observed", "sum"))
    # une période est complète si tous ses jours attendus existent ET sont couverts
    an = g.index.get_level_values("annee")
    attendu = np.where(g.index.get_level_values("sem") < NB_SEM - 1, 7,
                       np.where(pd.DatetimeIndex(an.map(lambda y: pd.Timestamp(y, 12, 31))).is_leap_year, 366, 365)
                       - 7 * (NB_SEM - 1))
    g["complete"] = (g["n"] == attendu) & (g["couverts"] == g["n"])
    obs = g[g["complete"]]["observed"].unstack("annee")     # lignes = semaines, colonnes = années
    rows = []
    for (annee, sem), r in g[g["complete"]].iterrows():
        hist = obs.loc[sem].drop(labels=[annee], errors="ignore").dropna().to_numpy()
        if len(hist) < min_annees:
            continue
        attendu_m, s_el, p90 = hist.mean(), np.percentile(hist, q_eleve), np.percentile(hist, q_crit)
        o = float(r["observed"])
        if o < plancher:
            niveau = "normal"
        elif o > p90:
            niveau = "critique"
        elif o > s_el:
            niveau = "eleve"
        else:
            niveau = "normal"
        rows.append(dict(period_start=r["debut"].date(), period_end=r["fin"].date(), observed=o,
                         expected=float(attendu_m), p90=float(p90), level=niveau,
                         note=f"semaine {sem + 1} ; {len(hist)} années comparables (année évaluée exclue) ; "
                              f"seuil élevé = p{q_eleve:g}, critique = p{q_crit:g} ; plancher {plancher:g}"))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--aoi-id", type=int)
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("OUEST", "SUD", "EST", "NORD"))
    ap.add_argument("--nom", default="zone")
    ap.add_argument("--geojson")
    ap.add_argument("--couverture", default=None, help="couverture_jours.csv de harmonisation.py")
    ap.add_argument("--min-annees", type=int, default=5)
    ap.add_argument("--q-eleve", type=float, default=75)
    ap.add_argument("--q-critique", type=float, default=90)
    ap.add_argument("--plancher", type=float, default=10)
    ap.add_argument("--csv", default=None, help="écrit aussi le résultat dans ce CSV")
    ap.add_argument("--dry-run", action="store_true", help="calcule et affiche, n'écrit pas dans la base")
    a = ap.parse_args()
    if sum(x is not None for x in (a.aoi_id, a.bbox, a.geojson)) != 1:
        ap.error("donne exactement une zone : --aoi-id, --bbox ou --geojson")

    with connexion() as conn:
        d0, d1 = conn.execute("SELECT MIN(day), MAX(day) FROM daily_activity").fetchone()
        if d0 is None:
            raise SystemExit("daily_activity est vide : charge d'abord les données.")
        if a.couverture:
            cov = pd.read_csv(a.couverture)
            jours = set(pd.to_datetime(cov.loc[cov["source"] != "aucune", "day"]))
        else:
            jours = set(pd.date_range(d0, d1))
            print("Pas de --couverture : tous les jours entre le premier et le dernier jour de la base "
                  "sont supposés couverts.")

        zones = []                      # (aoi_id ou None, nom, bbox, geojson)
        if a.aoi_id:
            zones.append((a.aoi_id, f"aoi {a.aoi_id}", None, None))
        elif a.bbox:
            zones.append((None, a.nom, tuple(a.bbox), None))
        else:
            for f in json.load(open(a.geojson))["features"]:
                nom = (f.get("properties") or {}).get("name") or (f.get("properties") or {}).get("NAME") or "zone"
                zones.append((None, nom, None, json.dumps(f["geometry"])))

        for aoi_id, nom, bbox, gj in zones:
            if aoi_id is None and not a.dry_run:
                if bbox:
                    aoi_id = conn.execute("INSERT INTO aoi (name, geom) VALUES (%s, ST_MakeEnvelope(%s,%s,%s,%s,4326)) "
                                          "RETURNING id", (nom, *bbox)).fetchone()[0]
                else:
                    aoi_id = conn.execute("INSERT INTO aoi (name, geom) VALUES (%s, ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)) "
                                          "RETURNING id", (nom, gj)).fetchone()[0]
            if aoi_id is not None:
                serie = serie_observee(conn, d0, d1, aoi_id=aoi_id)
            elif bbox:
                serie = serie_observee(conn, d0, d1, bbox=bbox)
            else:
                print(f"{nom} : --dry-run avec --geojson non supporté (la zone doit exister) ; ignorée.")
                continue
            res = calculer(serie, jours, pd.Timestamp(d0), pd.Timestamp(d1),
                           a.min_annees, a.q_eleve, a.q_critique, a.plancher)
            print(f"\n=== {nom}{'' if aoi_id is None else f' (aoi {aoi_id})'} ===")
            if res.empty:
                print("Aucune période classable (historique insuffisant ou zone sans données).")
                continue
            print(res["level"].value_counts().to_string())
            top = res[res["level"] == "critique"].assign(
                exces=lambda t: t["observed"] / t["expected"].where(t["expected"] > 0)).nlargest(8, "exces")
            print("Périodes critiques les plus marquées :")
            print(top[["period_start", "period_end", "observed", "expected", "p90"]].round(1).to_string(index=False))
            if a.csv:
                res.to_csv(a.csv if len(zones) == 1 else f"{a.csv}.{nom}.csv", index=False)
            if a.dry_run:
                continue
            conn.execute("DELETE FROM anomalies WHERE aoi_id = %s", (aoi_id,))
            with conn.cursor().copy("COPY anomalies (aoi_id, period_start, period_end, observed, expected, p90, level, note) FROM STDIN") as cp:
                for r in res.itertuples(index=False):
                    cp.write_row((aoi_id, r.period_start, r.period_end, r.observed, r.expected, r.p90, r.level, r.note))
            conn.execute("INSERT INTO import_log (dataset, row_count, note) VALUES ('anomalies', %s, %s)",
                         (len(res), f"anomalies_zone.py ({nom})"))
        conn.commit()
    print("\nTerminé." if not a.dry_run else "\n--dry-run : rien n'a été écrit.")


if __name__ == "__main__":
    main()
