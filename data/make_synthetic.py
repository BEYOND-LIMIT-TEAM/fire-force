"""
Jeu de données SYNTHÉTIQUE (pour développer et tester sans les vrais fichiers FIRMS).

Il imite le format des parquet de l'équipe : grille Albers Afrique 30 km, une ligne par cellule et par
jour avec au moins une détection, colonnes grid_x, grid_y, date, fire_count, frp_sum.
Il contient des feux sur les terres d'Afrique uniquement, avec les deux grandes saisons de feux
(savanes de l'hémisphère nord de novembre à mars, hémisphère sud de juin à octobre), quatre capteurs
(MODIS, VIIRS SNPP, N20, N21 avec leurs dates de début réelles), des jours sans données, et deux
événements inhabituels PLANTÉS pour vérifier que la détection d'anomalies les retrouve :
   - sud de l'équateur, août à octobre 2019 (environ x2,3)
   - nord de l'équateur, décembre 2022 à février 2023 (environ x1,9)
Ce ne sont PAS de vraies observations : ne jamais les citer comme résultats.

Usage : python make_synthetic.py --sortie synth [--fin 2025-08-03] [--echelle 1.0]
"""
import argparse, json, os, time
import numpy as np, pandas as pd, shapely
from shapely.geometry import shape
from pyproj import Transformer

PROJ = "+proj=aea +lat_1=20 +lat_2=-23 +lat_0=0 +lon_0=25 +x_0=0 +y_0=0 +ellps=WGS84 +units=m"
T = 30000
DEBUTS = {"MODIS": "2012-01-01", "VIIRS_SNPP": "2012-01-20", "VIIRS_N20": "2018-04-01", "VIIRS_N21": "2024-01-20"}
# sensibilité relative d'un capteur (nombre de détections par rapport à une référence VIIRS 375 m)
SENS = {"MODIS": 0.28, "VIIRS_SNPP": 1.0, "VIIRS_N20": 0.96, "VIIRS_N21": 1.02}
FRP_MOY = {"MODIS": 14.0, "VIIRS_SNPP": 9.0, "VIIRS_N20": 9.0, "VIIRS_N21": 9.0}


def cellules_terre(chemin):
    g = json.load(open(chemin))
    terre = shapely.union_all([shape(f["geometry"]) for f in g["features"]])
    gx, gy = np.meshgrid(np.arange(-160, 160), np.arange(-150, 150))
    gx, gy = gx.ravel(), gy.ravel()
    inv = Transformer.from_crs(PROJ, 4326, always_xy=True)
    lon, lat = inv.transform((gx + 0.5) * T, (gy + 0.5) * T)
    dedans = shapely.contains_xy(terre, lon, lat)
    # cellules côtières : on garde aussi celles dont le centre est à moins de ~0,15° d'une terre
    proche = shapely.dwithin(shapely.points(lon, lat), terre, 0.15) & ~dedans
    k = dedans | proche
    return gx[k], gy[k], lon[k], lat[k]


def gauss_circ(doy, pic, sigma):
    d = np.abs(doy - pic)
    d = np.minimum(d, 365 - d)
    return np.exp(-0.5 * (d / sigma) ** 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default="synth")
    ap.add_argument("--geo", default=os.path.join(os.path.dirname(__file__), "africa.geojson"))
    ap.add_argument("--debut", default="2012-01-01")
    ap.add_argument("--fin", default="2025-08-03")
    ap.add_argument("--echelle", type=float, default=1.0)
    ap.add_argument("--graine", type=int, default=7)
    a = ap.parse_args()
    os.makedirs(a.sortie, exist_ok=True)
    rng = np.random.default_rng(a.graine)
    gx, gy, lon, lat = cellules_terre(a.geo)
    n = len(gx)
    print(f"{n} cellules terrestres")

    # propension de la cellule à brûler
    nord = np.exp(-0.5 * ((lat - 9.0) / 4.5) ** 2)
    sud = np.exp(-0.5 * ((lat + 12.0) / 5.0) ** 2)
    foret_eq = np.where((np.abs(lat) < 4) & (lon > 8) & (lon < 30), 0.25, 1.0)
    desert = np.where((lat > 17) | ((lat < -20) & (lon < 22)) | ((lat > 12) & (lon > 33) & (lon < 45)), 0.03, 1.0)
    cote_m = np.where((lat > 30), 0.12, 1.0)
    base = (np.maximum(nord, sud) * foret_eq * desert * cote_m) * rng.lognormal(0, 0.75, n)
    base = np.maximum(base, 0.003)
    w_n = 1 / (1 + np.exp(-(lat - 1.0) / 1.6))
    w_s = 1 - w_n
    pic_n = 10 + (13 - np.clip(lat, 0, 18)) * 4.0
    pic_s = 190 + (-8 - np.clip(lat, -30, -3)) * 5.5

    jours = pd.date_range(a.debut, a.fin)
    annees = sorted(set(jours.year))
    f_n = {y: rng.lognormal(0, 0.22) for y in range(annees[0] - 1, annees[-1] + 2)}
    f_s = {y: rng.lognormal(0, 0.22) for y in range(annees[0] - 1, annees[-1] + 2)}
    bande = ((lat + 40) // 6).astype(int)
    nb = bande.max() + 1
    nsem = (len(jours) // 7) + 3
    bruit = rng.lognormal(0, 0.22, (nsem, nb))

    # jours sans aucune donnée (trou global) et pannes propres à un capteur
    trou = pd.date_range("2016-03-05", "2016-03-18")
    pannes = {s: set(pd.to_datetime(rng.choice(jours, 14, replace=False))) for s in DEBUTS}
    for s in DEBUTS:
        pannes[s] |= set(pd.date_range("2017-08-02", "2017-08-09")) if s == "MODIS" else set()

    sorties = {s: [] for s in DEBUTS}
    t0 = time.time()
    doy_all = jours.dayofyear.values
    for i, j in enumerate(jours):
        if j in trou:
            continue
        doy = doy_all[i]
        sem = i // 7
        seas = w_n * gauss_circ(doy, pic_n, 28) + w_s * gauss_circ(doy, pic_s, 32) + 0.015
        fy = np.where(lat > 1.0, f_n[j.year], f_s[j.year])
        # la saison nord s'étend sur deux années civiles : on prend l'année du pic
        ev = np.ones(n)
        if j.year == 2019 and 213 <= doy <= 290:
            ev = np.where(lat < 0, 2.3, 1.0)
        if (j.year == 2022 and doy >= 335) or (j.year == 2023 and doy <= 55):
            ev = np.where(lat > 1.0, 1.9, 1.0)
        lam = 2.2 * a.echelle * base * seas * fy * ev * bruit[sem, bande]
        mois_ratio = 1 + 0.25 * np.cos(2 * np.pi * (doy - 30) / 365)  # MODIS / VIIRS varie dans l'année
        for s, d0 in DEBUTS.items():
            if j < pd.Timestamp(d0) or j in pannes[s]:
                continue
            m = SENS[s] * (mois_ratio if s == "MODIS" else 1.0)
            c = rng.poisson(lam * m)
            idx = np.nonzero(c)[0]
            if idx.size:
                fc = c[idx]
                frp = fc * FRP_MOY[s] * rng.lognormal(0, 0.25, idx.size)
                sorties[s].append(pd.DataFrame({"grid_x": gx[idx].astype("int32"), "grid_y": gy[idx].astype("int32"),
                                                "date": j.date(), "fire_count": fc.astype("int32"),
                                                "frp_sum": frp.round(1)}))
        if i % 500 == 0:
            print(i, len(jours), f"{time.time()-t0:.0f}s", flush=True)
    for s, L in sorties.items():
        if not L:
            print(s, "aucune ligne sur la période, ignoré"); continue
        df = pd.concat(L, ignore_index=True)
        df["date"] = pd.to_datetime(df["date"])
        df.to_parquet(os.path.join(a.sortie, f"{s}.parquet"), index=False)
        print(s, len(df), "lignes", df.date.min().date(), df.date.max().date())


if __name__ == "__main__":
    main()
