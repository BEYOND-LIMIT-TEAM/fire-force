"""
Exporte les données de la base Neon (tables grid_cells et fire_daily) vers des fichiers parquet
que build_db.py sait lire. L'URL de connexion n'est jamais écrite : elle vient de la variable
d'environnement NEON_DATABASE_URL, ou est demandée en saisie masquée.

  pip install "psycopg[binary]" pyarrow
  python export_neon.py --sortie neon_export
  python build_db.py --source MODIS=neon_export/MODIS.parquet --source VIIRS=neon_export/VIIRS.parquet \\
      --reference VIIRS --secours MODIS --cellules neon_export/cells.parquet \\
      --sortie fireforce.duckdb --jeu firms --remplacer
"""
import argparse, getpass, os, time
import pyarrow as pa, pyarrow.parquet as pq

SQL_CELLS = """
SELECT grid_x, grid_y, center_lon, center_lat,
  ST_X(ST_PointN(ST_ExteriorRing(geom),1)), ST_Y(ST_PointN(ST_ExteriorRing(geom),1)),
  ST_X(ST_PointN(ST_ExteriorRing(geom),2)), ST_Y(ST_PointN(ST_ExteriorRing(geom),2)),
  ST_X(ST_PointN(ST_ExteriorRing(geom),3)), ST_Y(ST_PointN(ST_ExteriorRing(geom),3)),
  ST_X(ST_PointN(ST_ExteriorRing(geom),4)), ST_Y(ST_PointN(ST_ExteriorRing(geom),4))
FROM public.grid_cells ORDER BY cell_id"""
CELL_COLS = ["grid_x", "grid_y", "lon", "lat", "lon0", "lat0", "lon1", "lat1", "lon2", "lat2", "lon3", "lat3"]

SQL_DAILY = """
SELECT c.grid_x, c.grid_y, d.date, d.modis_count, d.modis_frp_sum, d.viirs_count, d.viirs_frp_sum
FROM public.fire_daily d JOIN public.grid_cells c USING (cell_id)"""
# Pas de ORDER BY : build_db.py trie déjà, et trier 8,5 M de lignes coûterait du calcul Neon.


def table(cols, rows):
    return pa.table({c: [r[i] for r in rows] for i, c in enumerate(cols)})


def export(con, sortie, lot=500_000, log=print):
    os.makedirs(sortie, exist_ok=True)
    t0 = time.time()
    cur = con.cursor(); cur.execute(SQL_CELLS)
    rows = cur.fetchall()
    pq.write_table(table(CELL_COLS, rows), f"{sortie}/cells.parquet")
    log(f"cells.parquet : {len(rows)} cellules")
    schema = pa.schema([("grid_x", pa.int16()), ("grid_y", pa.int16()), ("date", pa.date32()),
                        ("fire_count", pa.int32()), ("frp_sum", pa.float32())])
    w = {s: pq.ParquetWriter(f"{sortie}/{s}.parquet", schema) for s in ("MODIS", "VIIRS")}
    n = {"MODIS": 0, "VIIRS": 0}
    cur = con.cursor(name="export_fire_daily") if hasattr(con, "cursor") and _server_side(con) else con.cursor()
    cur.execute(SQL_DAILY)
    while True:
        rows = cur.fetchmany(lot)
        if not rows:
            break
        for lab, ic, ifrp in (("MODIS", 3, 4), ("VIIRS", 5, 6)):
            sel = [r for r in rows if r[ic] is not None and r[ic] > 0]
            if sel:
                w[lab].write_table(pa.table({"grid_x": [r[0] for r in sel], "grid_y": [r[1] for r in sel],
                    "date": [r[2] for r in sel], "fire_count": [int(r[ic]) for r in sel],
                    "frp_sum": [float(r[ifrp] or 0) for r in sel]}, schema=schema))
                n[lab] += len(sel)
        log(f"  {n['MODIS']} lignes MODIS, {n['VIIRS']} lignes VIIRS ({time.time()-t0:.0f}s)")
    for x in w.values():
        x.close()
    return n


def _server_side(con):
    return type(con).__module__.startswith("psycopg")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--sortie", default="neon_export")
    a = ap.parse_args()
    import psycopg
    url = os.environ.get("NEON_DATABASE_URL") or getpass.getpass("URL Neon (saisie masquée) : ").strip()
    with psycopg.connect(url) as con:
        n = export(con, a.sortie)
    print("Terminé :", n)


if __name__ == "__main__":
    main()
