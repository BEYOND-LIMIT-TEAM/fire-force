import os
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.analytics import Params, calendar_frame, weekly_totals, assess, week_of, week_bounds, episodes

P = Params()


def fabrique(valeurs_par_annee, trous=()):
    """Série journalière où chaque année vaut le niveau donné (par jour), avec jours sans données optionnels."""
    jours, vals = [], {}
    for y, v in valeurs_par_annee.items():
        for d in pd.date_range(f"{y}-01-01", f"{y}-12-31"):
            vals[d] = v
    s = pd.Series(vals)
    cov = s.index.difference(pd.DatetimeIndex(trous))
    return s, cov


def test_semaines_52_par_an():
    d = pd.date_range("2020-01-01", "2020-12-31")
    w = week_of(d)
    assert w.min() == 0 and w.max() == 51
    assert (w == 51).sum() == 9  # année bissextile : 358 -> 366
    s, e = week_bounds(2020, 51)
    assert e == pd.Timestamp("2020-12-31")


def test_trou_n_est_pas_un_zero():
    s, cov = fabrique({y: 5.0 for y in range(2012, 2021)}, trous=pd.date_range("2016-03-05", "2016-03-18"))
    f = calendar_frame(pd.Timestamp("2012-01-01"), pd.Timestamp("2020-12-31"), s, cov)
    wk = weekly_totals(f, P)
    sem = wk[(wk.year == 2016) & (wk.week.isin([9, 10]))]
    # semaine 9 (5-11 mars) et 10 (12-18 mars) sont entièrement dans le trou -> non évaluées
    assert sem["total"].isna().all()
    # une semaine normale vaut 7 x 5 = 35
    assert wk[(wk.year == 2014) & (wk.week == 20)]["total"].iloc[0] == pytest.approx(35.0)


def test_anomalie_plantee_detectee_et_hors_hors_plancher():
    vals = {y: 20.0 for y in range(2012, 2024)}
    s, cov = fabrique(vals)
    # semaine 30 de 2019 multipliée par 3
    d0, d1 = week_bounds(2019, 30)
    s.loc[d0:d1] = 60.0
    f = calendar_frame(pd.Timestamp("2012-01-01"), pd.Timestamp("2023-12-31"), s, cov)
    wk = assess(weekly_totals(f, P), P)
    r = wk[(wk.year == 2019) & (wk.week == 30)].iloc[0]
    assert r.level == "critique" and r.record
    assert r.expected == pytest.approx(7 * 20.0, rel=1e-6)  # l'année évaluée est exclue de l'attendu
    # les autres semaines restent normales
    assert (wk[(wk.year == 2019) & (wk.week != 30)]["level"] == "normal").all()


def test_plancher_evite_les_faux_positifs_sur_petits_nombres():
    vals = {y: 0.1 for y in range(2012, 2024)}
    s, cov = fabrique(vals)
    d0, d1 = week_bounds(2019, 10)
    s.loc[d0:d1] = 0.5  # x5 mais 3,5 détections par semaine < plancher 10
    f = calendar_frame(pd.Timestamp("2012-01-01"), pd.Timestamp("2023-12-31"), s, cov)
    wk = assess(weekly_totals(f, P), P)
    assert wk[(wk.year == 2019) & (wk.week == 10)]["level"].iloc[0] == "normal"


def test_pas_assez_d_annees_donne_indetermine():
    s, cov = fabrique({y: 20.0 for y in range(2020, 2023)})
    f = calendar_frame(pd.Timestamp("2020-01-01"), pd.Timestamp("2022-12-31"), s, cov)
    wk = assess(weekly_totals(f, P), P)
    assert (wk["level"] == "indetermine").all()


def test_periodes_regroupees_seulement_si_consecutives_et_meme_niveau():
    niveaux = ["eleve", "critique", "critique", "eleve", "eleve", "normal", "eleve", "critique"]
    wk = pd.DataFrame({"year": 2020, "week": range(10, 10 + len(niveaux)), "level": niveaux})
    eps = episodes(wk)
    forme = [(e[0]["level"], len(e), int(e[0]["week"])) for e in eps]
    assert forme == [("eleve", 1, 10), ("critique", 2, 11), ("eleve", 2, 13), ("eleve", 1, 16), ("critique", 1, 17)]


def test_periode_a_cheval_sur_deux_annees_reste_continue():
    wk = pd.DataFrame({"year": [2020, 2020, 2021, 2021], "week": [50, 51, 0, 1], "level": ["critique"] * 4})
    assert [len(e) for e in episodes(wk)] == [4]


DB = os.path.join(os.path.dirname(__file__), "..", "..", "data", "fireforce.duckdb")


def _est_demo(path):
    """Ces tests vérifient les épisodes plantés dans les données synthétiques (make demo-data)."""
    if not os.path.exists(path):
        return False
    import duckdb
    con = duckdb.connect(path, read_only=True)
    try:
        rows = con.execute("SELECT value FROM meta WHERE key = 'dataset'").fetchall()
    finally:
        con.close()
    return bool(rows) and rows[0][0] == "demo"


@pytest.mark.skipif(not _est_demo(DB), reason="base de démonstration absente (make demo-data)")
class TestAPI:
    @classmethod
    def setup_class(cls):
        os.environ["FIREFORCE_DB"] = os.path.abspath(DB)
        from app.main import app
        cls.c = TestClient(app)

    def test_health_meta(self):
        assert self.c.get("/api/health").json()["status"] == "ok"
        m = self.c.get("/api/meta").json()
        assert m["first_day"] < m["last_day"] and len(m["sensors"]) >= 2

    def test_zone_et_totaux_coherents(self):
        body = {"zone": {"type": "bbox", "bbox": [18, -18, 30, -8]}, "start": "2019-06-01", "end": "2019-11-30"}
        r = self.c.post("/api/analyze", json=body).json()
        cal_total = sum(v for _, v, _, _ in r["calendar"] if v is not None)
        assert cal_total == pytest.approx(sum(r["cell_map"]["values"]), rel=1e-3)
        assert r["episodes"][0]["level"] == "critique" and r["episodes"][0]["status"] == "confirmee"

    def test_polygone_equivaut_au_rectangle(self):
        rect = {"type": "bbox", "bbox": [8, 6, 15, 12]}
        poly = {"type": "polygon", "coordinates": [[8, 6], [15, 6], [15, 12], [8, 12]]}
        a = self.c.post("/api/analyze", json={"zone": rect, "start": "2022-10-01", "end": "2023-03-31"}).json()
        b = self.c.post("/api/analyze", json={"zone": poly, "start": "2022-10-01", "end": "2023-03-31"}).json()
        assert a["zone"]["n_cells"] == b["zone"]["n_cells"] and a["kpi"]["total"] == b["kpi"]["total"]

    def test_entrees_invalides(self):
        z = {"type": "bbox", "bbox": [10, 5, 5, 8]}
        assert self.c.post("/api/analyze", json={"zone": z, "start": "2019-01-01", "end": "2019-02-01"}).status_code == 422
        z = {"type": "bbox", "bbox": [5, 5, 8, 8]}
        assert self.c.post("/api/analyze", json={"zone": z, "start": "2019-03-01", "end": "2019-02-01"}).status_code == 422
        assert self.c.post("/api/analyze", json={"zone": z, "start": "1990-01-01", "end": "1991-01-01"}).status_code == 422

    def test_zone_dans_la_mer_est_vide_sans_erreur(self):
        z = {"type": "bbox", "bbox": [-40, -10, -35, -5]}
        r = self.c.post("/api/analyze", json={"zone": z, "start": "2019-01-01", "end": "2019-02-01"}).json()
        assert r["empty"] is True

    def test_trou_global_marque_dans_le_calendrier(self):
        z = {"type": "bbox", "bbox": [8, 6, 15, 12]}
        r = self.c.post("/api/analyze", json={"zone": z, "start": "2016-03-01", "end": "2016-03-31"}).json()
        gaps = [d for d, v, _, _ in r["calendar"] if v is None]
        assert "2016-03-10" in gaps and r["kpi"]["days_gap"] >= 14
