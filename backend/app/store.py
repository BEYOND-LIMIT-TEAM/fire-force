"""Accès à la base analytique (DuckDB) : ouverture, cellules, couverture, sélection de zone."""
import os
import threading
import duckdb
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon, box

PROJ = "+proj=aea +lat_1=20 +lat_2=-23 +lat_0=0 +lon_0=25 +x_0=0 +y_0=0 +ellps=WGS84 +units=m"
_to_albers = Transformer.from_crs(4326, PROJ, always_xy=True).transform


class Store:
    def __init__(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Base introuvable : {path}. Construis-la avec data/build_db.py")
        self.path = path
        self.con = duckdb.connect(path, read_only=True)
        self._lock = threading.Lock()
        self.meta = dict(self.con.execute("SELECT key, value FROM meta").fetchall())
        self.sensors = self.con.execute("SELECT sensor_id, name, role, first_day, last_day, n_rows FROM sensors ORDER BY sensor_id").df()
        self.cells = self.con.execute("SELECT * FROM cells ORDER BY cell_id").df()
        cov = self.con.execute("SELECT day, source, factor FROM coverage ORDER BY day").df()
        cov["day"] = pd.to_datetime(cov["day"])
        self.coverage = cov.set_index("day")
        sd = self.con.execute("SELECT sensor_id, day FROM sensor_daily GROUP BY 1,2").df()
        sd["day"] = pd.to_datetime(sd["day"])
        names = dict(zip(self.sensors.sensor_id, self.sensors.name))
        self.sensor_days = {names[s]: pd.DatetimeIndex(g["day"]) for s, g in sd.groupby("sensor_id")}
        self.first_day = pd.Timestamp(self.meta["first_day"])
        self.last_day = pd.Timestamp(self.meta["last_day"])
        self.grid_m = int(self.meta.get("grid_m", 30000))
        self._map_cache = {}

    def cursor(self):
        with self._lock:
            return self.con.cursor()

    # ---- sélection de zone -------------------------------------------------------------------
    def zone_polygon(self, zone):
        """Polygone lon/lat à partir de {'type':'bbox','bbox':[w,s,e,n]} ou {'type':'polygon','coordinates':[[lon,lat],...]}."""
        t = zone.get("type")
        if t == "bbox":
            w, s, e, n = [float(v) for v in zone["bbox"]]
            if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
                raise ValueError("Coordonnées invalides : il faut ouest < est et sud < nord.")
            return box(w, s, e, n)
        if t == "polygon":
            pts = [(float(a), float(b)) for a, b in zone["coordinates"]]
            if len(pts) < 3:
                raise ValueError("Un polygone demande au moins 3 points.")
            if len(pts) > 2000:
                raise ValueError("Polygone trop détaillé (2000 sommets au maximum).")
            p = Polygon(pts)
            if not p.is_valid:
                p = shapely.make_valid(p)
            if p.is_empty or p.area == 0:
                raise ValueError("Polygone vide ou dégénéré.")
            return p
        raise ValueError("Type de zone inconnu (bbox ou polygon).")

    def zone_cells(self, poly):
        """Cellules dont le centre est dans la zone ; si aucune, la cellule qui contient le centre de la zone."""
        c = self.cells
        mask = shapely.contains_xy(poly, c["lon"].values, c["lat"].values)
        ids = c.loc[mask, "cell_id"].values
        approx = False
        if len(ids) == 0:
            x, y = _to_albers(poly.centroid.x, poly.centroid.y)
            gx, gy = int(np.floor(x / self.grid_m)), int(np.floor(y / self.grid_m))
            m2 = (c["grid_x"].values == gx) & (c["grid_y"].values == gy)
            ids = c.loc[m2, "cell_id"].values
            approx = True
        return ids, approx

    @staticmethod
    def area_km2(poly):
        g = shapely.transform(poly, lambda c: np.column_stack(_to_albers(c[:, 0], c[:, 1])))
        return float(g.area / 1e6)

    def overview_map(self, start, end):
        """Totaux harmonisés par cellule sur une période (mis en cache) : tableau aligné sur self.cells."""
        key = (str(start), str(end))
        if key in self._map_cache:
            return self._map_cache[key]
        df = self.cursor().execute(
            "SELECT cell_id, sum(n_harm) AS v FROM daily WHERE day BETWEEN ? AND ? GROUP BY 1", [start, end]).df()
        v = pd.Series(df["v"].values, index=df["cell_id"].values).reindex(self.cells["cell_id"].values).fillna(0).values
        if len(self._map_cache) > 40:
            self._map_cache.clear()
        self._map_cache[key] = v
        return v
