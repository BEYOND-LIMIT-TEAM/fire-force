"""Préparer la table fire_daily (MODIS + VIIRS côte à côte) pour Neon.

Fusionne les deux fichiers quotidiens sur (cellule, jour), garde
uniquement les colonnes utiles à l'application et la période choisie,
puis écrit un Parquet prêt à être chargé par load_to_neon.py.

Entrées :
    data/aggregated/daily/modis_daily_grid_30km.parquet
    data/aggregated/daily/viirs_daily_grid_30km.parquet
Sortie :
    data/db/fire_daily_<début>_<fin>.parquet

Exemples (depuis la racine du projet) :
    # 1. Estimer la taille dans Neon, année par année, sans rien écrire
    python src/fire_pipeline/storage/build_daily_table.py --estimate

    # 2. Construire le fichier pour la période retenue
    python src/fire_pipeline/storage/build_daily_table.py \
        --start 2020-01-01 --end 2025-08-03
"""

import argparse
from datetime import date
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DAILY_DIR = PROJECT_ROOT / "data" / "aggregated" / "daily"
MODIS_FILE = DAILY_DIR / "modis_daily_grid_30km.parquet"
VIIRS_FILE = DAILY_DIR / "viirs_daily_grid_30km.parquet"
OUTPUT_DIR = PROJECT_ROOT / "data" / "db"

# Période commune MODIS / VIIRS (NOAA-20) par défaut.
DEFAULT_START = "2018-04-01"
DEFAULT_END = "2025-08-03"

# Place occupée par une ligne de fire_daily dans PostgreSQL, clé primaire
# comprise. Mesuré sur une vraie base PostGIS avec ce schéma.
BYTES_PER_ROW = 83

# Limite Neon gratuite : 1 Go. On garde de la marge pour la grille,
# les fonctions, et les futures tables de l'équipe.
NEON_BUDGET_MB = 800

# Même formule que build_grid_cells.py.
CELL_ID_SQL = "((grid_x + 500) * 1000 + (grid_y + 500))"


def merged_query(start, end):
    """Requête SQL qui fusionne MODIS et VIIRS sur (cellule, jour)."""
    return f"""
        WITH modis AS (
            SELECT
                {CELL_ID_SQL} AS cell_id,
                CAST(date AS DATE) AS date,      -- MODIS : date en texte
                fire_count, frp_sum, frp_max
            FROM read_parquet('{MODIS_FILE.as_posix()}')
            WHERE CAST(date AS DATE) BETWEEN DATE '{start}' AND DATE '{end}'
        ),
        viirs AS (
            SELECT
                {CELL_ID_SQL} AS cell_id,
                CAST(date AS DATE) AS date,
                fire_count, frp_sum, frp_max
            FROM read_parquet('{VIIRS_FILE.as_posix()}')
            WHERE CAST(date AS DATE) BETWEEN DATE '{start}' AND DATE '{end}'
        )
        SELECT
            CAST(COALESCE(m.cell_id, v.cell_id) AS INTEGER) AS cell_id,
            COALESCE(m.date, v.date)                        AS date,
            CAST(m.frp_sum AS FLOAT)                        AS modis_frp_sum,
            CAST(m.frp_max AS FLOAT)                        AS modis_frp_max,
            CAST(v.frp_sum AS FLOAT)                        AS viirs_frp_sum,
            CAST(v.frp_max AS FLOAT)                        AS viirs_frp_max,
            CAST(m.fire_count AS SMALLINT)                  AS modis_count,
            CAST(v.fire_count AS SMALLINT)                  AS viirs_count
        FROM modis m
        FULL OUTER JOIN viirs v
            ON m.cell_id = v.cell_id AND m.date = v.date
    """


def check_inputs(con):
    """Vérifier les fichiers avant de fusionner."""
    for name, path in (("MODIS", MODIS_FILE), ("VIIRS", VIIRS_FILE)):
        if not path.is_file():
            raise SystemExit(f"Fichier introuvable : {path}")

        duplicates, max_count, out_of_range = con.execute(f"""
            SELECT
                COUNT(*) - COUNT(DISTINCT (grid_x, grid_y, date)),
                MAX(fire_count),
                COUNT(*) FILTER (WHERE abs(grid_x) >= 500 OR abs(grid_y) >= 500)
            FROM read_parquet('{path.as_posix()}')
        """).fetchall()[0]

        if duplicates:
            raise SystemExit(f"{name} : {duplicates:,} doublons (cellule, jour).")
        if max_count > 32767:
            raise SystemExit(f"{name} : fire_count trop grand pour smallint ({max_count}).")
        if out_of_range:
            raise SystemExit(f"{name} : {out_of_range:,} cellules hors limites.")

        print(f"{name} vérifié : pas de doublon, fire_count max = {max_count}")


def estimate(con, start, end):
    rows = con.execute(f"""
        SELECT year(date) AS annee, COUNT(*) AS lignes
        FROM ({merged_query(start, end)})
        GROUP BY annee
        ORDER BY annee
    """).fetchall()

    print(f"\nEstimation pour Neon ({BYTES_PER_ROW} octets par ligne) :\n")
    print(f"{'Année':<8}{'Lignes':>12}{'Mo':>10}{'Cumul depuis la fin (Mo)':>28}")

    # Cumul à rebours : « si je commence à cette année-là, combien ça fait ? »
    cumulative = 0
    lines = []
    for year, count in reversed(rows):
        mb = count * BYTES_PER_ROW / 1e6
        cumulative += mb
        lines.append((year, count, mb, cumulative))

    for year, count, mb, cumul in reversed(lines):
        marker = "" if cumul <= NEON_BUDGET_MB else "  ← dépasse le budget"
        print(f"{year:<8}{count:>12,}{mb:>10.0f}{cumul:>28.0f}{marker}")

    total = sum(count for _, count in rows)
    total_mb = total * BYTES_PER_ROW / 1e6
    print(f"\nTotal {start} → {end} : {total:,} lignes ≈ {total_mb:.0f} Mo")
    print(f"Budget conseillé : {NEON_BUDGET_MB} Mo (limite Neon gratuite : 1 000 Mo)")


def build(con, start, end):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"fire_daily_{start}_{end}.parquet"
    temporary = output.with_suffix(".parquet.tmp")

    print("\nFusion de MODIS et VIIRS...")
    # Tri par (cell_id, date) : les lignes d'une même cellule seront
    # rangées ensemble dans PostgreSQL, ce qui accélère les requêtes par zone.
    con.execute(f"""
        COPY (
            {merged_query(start, end)}
            ORDER BY cell_id, date
        )
        TO '{temporary.as_posix()}'
        (FORMAT PARQUET, COMPRESSION ZSTD)
    """).fetchall()
    temporary.replace(output)

    total, modis_days, viirs_days, both, first, last = con.execute(f"""
        SELECT
            COUNT(*),
            COUNT(modis_count),
            COUNT(viirs_count),
            COUNT(*) FILTER (WHERE modis_count IS NOT NULL AND viirs_count IS NOT NULL),
            MIN(date),
            MAX(date)
        FROM read_parquet('{output.as_posix()}')
    """).fetchall()[0]

    print("\nFICHIER PRÊT")
    print(f"Fichier : {output.relative_to(PROJECT_ROOT)}")
    print(f"Période : {first} → {last}")
    print(f"Lignes (cellule-jours) : {total:,}")
    print(f"  avec MODIS : {modis_days:,}")
    print(f"  avec VIIRS : {viirs_days:,}")
    print(f"  avec les deux : {both:,}")
    print(f"Taille estimée dans Neon : {total * BYTES_PER_ROW / 1e6:.0f} Mo")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--start", default=DEFAULT_START, help="AAAA-MM-JJ")
    parser.add_argument("--end", default=DEFAULT_END, help="AAAA-MM-JJ")
    parser.add_argument(
        "--estimate", action="store_true",
        help="Afficher la taille estimée par année sans écrire de fichier.",
    )
    args = parser.parse_args()

    start = date.fromisoformat(args.start).isoformat()
    end = date.fromisoformat(args.end).isoformat()
    if start > end:
        raise SystemExit("--start doit être avant --end.")

    con = duckdb.connect()
    try:
        con.execute("SET preserve_insertion_order = false").fetchall()
        check_inputs(con)
        if args.estimate:
            estimate(con, start, end)
        else:
            build(con, start, end)
    finally:
        con.close()


if __name__ == "__main__":
    main()
