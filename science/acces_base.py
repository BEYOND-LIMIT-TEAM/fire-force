"""
Accès SQL pour le rôle 2 : lire la base PostgreSQL du projet depuis tes scripts d'analyse.

Tu donnes une ZONE (rectangle OU identifiant d'aoi) et une PÉRIODE ; PostgreSQL fait les
sommes et ne renvoie que le résultat, sous forme de tableau pandas. On ne rapatrie jamais
toute la base : c'est ce qui rend l'analyse rapide.

Dans un script :
    from acces_base import connexion, serie_zone, serie_observee, matrice_jour_annee, cellules_zone
    with connexion() as conn:
        s = serie_zone(conn, (8.5, 1.6, 16.2, 13.1), "2020-01-01", "2024-12-31")
        s = serie_zone(conn, None, "2020-01-01", "2024-12-31", aoi_id=3)

En ligne de commande (test) :
    python acces_base.py --bbox 8.5 1.6 16.2 13.1 --debut 2024-01-01 --fin 2024-12-31

Connexion : variable d'environnement DATABASE_URL (ex. l'adresse fournie par Neon, avec
?sslmode=require), sinon la base locale du projet.
Même règle de zone que l'API (cellules qui touchent la zone) : tes chiffres doivent donc
être identiques à ceux de /calendar.
"""
import argparse
import os

import pandas as pd
import psycopg

URL_PAR_DEFAUT = "postgresql://fireweb:fireweb@localhost:5432/fireweb"


def connexion(url=None):
    return psycopg.connect(url or os.environ.get("DATABASE_URL", URL_PAR_DEFAUT))


def lire(conn, sql, params=None):
    """Exécute une requête SQL et renvoie un DataFrame (pour tes requêtes à toi)."""
    cur = conn.execute(sql, params or {})
    return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def _zone(bbox, aoi_id):
    """Début de requête : la zone et ses cellules (même règle que l'API)."""
    if aoi_id is not None:
        z, p = "zone AS (SELECT geom FROM aoi WHERE id = %(aoi)s)", {"aoi": aoi_id}
    elif bbox is not None:
        w, s, e, n = bbox
        z = "zone AS (SELECT ST_MakeEnvelope(%(w)s, %(s)s, %(e)s, %(n)s, 4326) AS geom)"
        p = {"w": w, "s": s, "e": e, "n": n}
    else:
        raise ValueError("Donne une zone : bbox=(ouest, sud, est, nord) ou aoi_id=N")
    c = ("c AS (SELECT g.cell_id FROM grid_cells g JOIN zone z "
         "ON g.geom && z.geom AND ST_Intersects(g.geom, z.geom))")
    return f"WITH {z}, {c}", p


def cellules_zone(conn, bbox=None, aoi_id=None):
    """Cellules de la grille qui touchent la zone : cell_id, lat_centre, lon_centre."""
    w, p = _zone(bbox, aoi_id)
    return lire(conn, w + """
        SELECT g.cell_id, ST_Y(ST_Centroid(g.geom)) AS lat_centre, ST_X(ST_Centroid(g.geom)) AS lon_centre
        FROM grid_cells g JOIN c USING (cell_id) ORDER BY g.cell_id""", p)


def serie_observee(conn, debut, fin, bbox=None, aoi_id=None):
    """Somme de la zone par jour : day, observed (harmonisé), raw. Uniquement les jours qui ont des
    lignes : un jour absent = 0 feu OU trou de données (à trancher avec la couverture)."""
    w, p = _zone(bbox, aoi_id)
    return lire(conn, w + """
        SELECT a.day, SUM(a.count_harmonized) AS observed, SUM(a.count_raw) AS raw
        FROM daily_activity a JOIN c USING (cell_id)
        WHERE a.day BETWEEN %(d0)s AND %(d1)s GROUP BY a.day ORDER BY a.day""",
                {**p, "d0": debut, "d1": fin})


def serie_zone(conn, bbox, debut, fin, aoi_id=None):
    """Série journalière de la zone : day, observed (harmonisé), raw (brut), frp,
    expected (moyenne climatologique), p90. Mêmes colonnes que /calendar de l'API."""
    w, p = _zone(bbox, aoi_id)
    return lire(conn, w + """,
        obs AS (SELECT a.day, SUM(a.count_harmonized) AS observed, SUM(a.count_raw) AS raw,
                       SUM(a.frp_sum) AS frp
                FROM daily_activity a JOIN c USING (cell_id)
                WHERE a.day BETWEEN %(d0)s AND %(d1)s GROUP BY a.day),
        jours AS (SELECT generate_series(%(d0)s::date, %(d1)s::date, interval '1 day')::date AS day),
        att AS (SELECT j.day, SUM(cl.mean_count) AS expected, SUM(cl.p90_count) AS p90
                FROM jours j CROSS JOIN c
                LEFT JOIN climatology cl ON cl.cell_id = c.cell_id
                                        AND cl.doy = EXTRACT(DOY FROM j.day)::int
                GROUP BY j.day)
        SELECT j.day, COALESCE(obs.observed, 0) AS observed, COALESCE(obs.raw, 0) AS raw,
               obs.frp, att.expected, att.p90
        FROM jours j LEFT JOIN obs USING (day) LEFT JOIN att USING (day) ORDER BY j.day""",
                {**p, "d0": debut, "d1": fin})


def matrice_jour_annee(conn, bbox, debut, fin, colonne="count_harmonized", aoi_id=None):
    """Tableau jour de l'année (lignes) x année (colonnes) pour la zone : la matière du calendrier."""
    if colonne not in ("count_harmonized", "count_raw", "frp_sum"):
        raise ValueError("colonne : count_harmonized, count_raw ou frp_sum")
    w, p = _zone(bbox, aoi_id)
    return lire(conn, w + f"""
        SELECT EXTRACT(YEAR FROM a.day)::int AS annee, EXTRACT(DOY FROM a.day)::int AS doy,
               SUM(a.{colonne}) AS valeur
        FROM daily_activity a JOIN c USING (cell_id)
        WHERE a.day BETWEEN %(d0)s AND %(d1)s GROUP BY 1, 2""",
                {**p, "d0": debut, "d1": fin}).pivot(index="doy", columns="annee", values="valeur")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("OUEST", "SUD", "EST", "NORD"))
    ap.add_argument("--aoi-id", type=int)
    ap.add_argument("--debut", required=True)
    ap.add_argument("--fin", required=True)
    a = ap.parse_args()
    with connexion() as conn:
        print(f"{len(cellules_zone(conn, a.bbox, a.aoi_id))} cellule(s) dans la zone")
        s = serie_zone(conn, a.bbox, a.debut, a.fin, a.aoi_id)
        print(s.head(10).to_string(index=False))
        print(f"... {len(s)} jours ; total harmonisé = {s['observed'].sum():,.0f}")


if __name__ == "__main__":
    main()
