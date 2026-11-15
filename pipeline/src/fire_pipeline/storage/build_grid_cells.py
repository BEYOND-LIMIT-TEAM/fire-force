"""Construire la table des cellules de la grille 30 km.

Remplace l'ancien /tmp/fire_grid_cells.csv, qui n'était produit par aucun
script. On recalcule ici, de façon reproductible, le polygone et le centre
de chaque cellule utilisée par MODIS ou VIIRS.

Entrées :
    data/aggregated/daily/modis_daily_grid_30km.parquet
    data/aggregated/daily/viirs_daily_grid_30km.parquet
Sortie :
    data/reference/grid_cells.parquet

Lancement (depuis la racine du projet) :
    python src/fire_pipeline/storage/build_grid_cells.py
"""

from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DAILY_DIR = PROJECT_ROOT / "data" / "aggregated" / "daily"
MODIS_FILE = DAILY_DIR / "modis_daily_grid_30km.parquet"
VIIRS_FILE = DAILY_DIR / "viirs_daily_grid_30km.parquet"
OUTPUT_FILE = PROJECT_ROOT / "data" / "reference" / "grid_cells.parquet"

# Doivent rester identiques à ceux de daily_grid.py et process_viirs.py.
GRID_SIZE = 30_000
GRID_CRS = (
    "+proj=aea +lat_1=20 +lat_2=-23 +lat_0=0 "
    "+lon_0=25 +datum=WGS84 +units=m +no_defs"
)

# cell_id = (grid_x + OFFSET) * 1000 + (grid_y + OFFSET)
# Valable tant que |grid_x| et |grid_y| restent < 500 (soit 15 000 km).
OFFSET = 500


def cell_id(grid_x, grid_y):
    return (grid_x + OFFSET) * 1000 + (grid_y + OFFSET)


def read_cells():
    """Lister toutes les cellules (grid_x, grid_y) présentes dans les deux capteurs."""
    for path in (MODIS_FILE, VIIRS_FILE):
        if not path.is_file():
            raise SystemExit(f"Fichier introuvable : {path}")

    con = duckdb.connect()
    try:
        rows = con.execute(f"""
            SELECT DISTINCT grid_x, grid_y
            FROM (
                SELECT grid_x, grid_y FROM read_parquet('{MODIS_FILE.as_posix()}')
                UNION ALL
                SELECT grid_x, grid_y FROM read_parquet('{VIIRS_FILE.as_posix()}')
            )
            ORDER BY grid_x, grid_y
        """).fetchall()   # fetchall() : obligatoire avec duckdb 2.0
    finally:
        con.close()

    for grid_x, grid_y in rows:
        if abs(grid_x) >= OFFSET or abs(grid_y) >= OFFSET:
            raise SystemExit(
                f"Cellule hors limites pour cell_id : {grid_x}_{grid_y}"
            )
    return rows


def build_table(cells):
    to_wgs84 = Transformer.from_crs(GRID_CRS, "EPSG:4326", always_xy=True)

    ids, xs, ys, grid_ids = [], [], [], []
    center_lons, center_lats, wkts = [], [], []

    for grid_x, grid_y in cells:
        x0, y0 = grid_x * GRID_SIZE, grid_y * GRID_SIZE
        x1, y1 = x0 + GRID_SIZE, y0 + GRID_SIZE

        # Le carré est défini dans la projection Albers, puis ses coins
        # sont convertis en longitude/latitude.
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        lons, lats = to_wgs84.transform(
            [c[0] for c in corners], [c[1] for c in corners]
        )
        ring = ", ".join(f"{lon:.6f} {lat:.6f}" for lon, lat in zip(lons, lats))

        center_lon, center_lat = to_wgs84.transform(
            x0 + GRID_SIZE / 2, y0 + GRID_SIZE / 2
        )

        ids.append(cell_id(grid_x, grid_y))
        xs.append(grid_x)
        ys.append(grid_y)
        grid_ids.append(f"{grid_x}_{grid_y}")
        center_lons.append(center_lon)
        center_lats.append(center_lat)
        wkts.append(f"SRID=4326;POLYGON(({ring}))")

    # Même ordre de colonnes que la table grid_cells dans schema.sql.
    return pa.table({
        "cell_id": pa.array(ids, pa.int32()),
        "grid_x": pa.array(xs, pa.int16()),
        "grid_y": pa.array(ys, pa.int16()),
        "grid_id": pa.array(grid_ids, pa.string()),
        "center_lon": pa.array(center_lons, pa.float32()),
        "center_lat": pa.array(center_lats, pa.float32()),
        "geom": pa.array(wkts, pa.string()),
    })


def main():
    print("Lecture des cellules MODIS et VIIRS...")
    cells = read_cells()
    print(f"Cellules distinctes : {len(cells):,}")

    table = build_table(cells)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_FILE.with_suffix(".parquet.tmp")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(OUTPUT_FILE)

    print(f"Grille enregistrée : {OUTPUT_FILE.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
