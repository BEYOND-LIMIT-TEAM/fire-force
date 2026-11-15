"""
Calculs de Fire Force : séries, climatologie, anomalies, épisodes critiques, confirmation multi-capteurs.

Principes (à citer tels quels dans le rapport) :
  - une SEMAINE = 7 jours à partir du 1er janvier, 52 semaines par an (la 52e absorbe les 8 ou 9 derniers jours) ;
  - une semaine n'est évaluée que si au moins 70 % de ses jours ont des données (un trou n'est jamais un zéro) ;
    sa valeur est ramenée à la durée complète de la semaine ;
  - la valeur « attendue » d'une semaine est la moyenne des MÊMES semaines des autres années (l'année évaluée est
    exclue du calcul : on ne compare pas une année à elle-même) ; il faut au moins `min_annees` autres années ;
  - niveau « élevé » : valeur > centile q_eleve des autres années ET >= ratio_eleve x attendu ET >= plancher ;
    niveau « critique » : valeur > centile q_critique ET >= ratio_critique x attendu ET >= plancher ;
  - une période à surveiller regroupe des semaines consécutives de MÊME niveau (élevé avec élevé, critique avec critique) ;
  - une anomalie est « confirmée » quand au moins deux capteurs indépendants la signalent chacun par rapport à
    leur propre historique.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
import numpy as np
import pandas as pd

LEVELS = ["normal", "eleve", "critique"]
LEVEL_RANK = {"normal": 0, "eleve": 1, "critique": 2}


@dataclass
class Params:
    q_eleve: float = 75.0
    q_critique: float = 90.0
    ratio_eleve: float = 1.25
    ratio_critique: float = 1.5
    plancher: float = 10.0
    min_annees: int = 5
    couverture_min: float = 0.7


def _nn(x, nd=2):
    """float -> valeur JSON propre (None pour NaN)."""
    if x is None:
        return None
    try:
        if isinstance(x, (float, np.floating)) and (math.isnan(x) or math.isinf(x)):
            return None
    except TypeError:
        pass
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return round(float(x), nd)
    return x


def week_of(days: pd.DatetimeIndex):
    return np.minimum((days.day_of_year.values - 1) // 7, 51)


def week_bounds(year: int, w: int):
    start = pd.Timestamp(year=year, month=1, day=1) + pd.Timedelta(days=7 * w)
    end = pd.Timestamp(year=year, month=12, day=31) if w == 51 else start + pd.Timedelta(days=6)
    return start, end


def calendar_frame(first: pd.Timestamp, last: pd.Timestamp, values: pd.Series, covered: pd.DatetimeIndex):
    """Un jour par ligne, de janvier de la première année à décembre de la dernière.
    val = valeur du jour, NaN si le jour n'est pas couvert (trou ou hors période des données)."""
    days = pd.date_range(pd.Timestamp(year=first.year, month=1, day=1), pd.Timestamp(year=last.year, month=12, day=31))
    f = pd.DataFrame(index=days)
    f["cov"] = days.isin(covered)
    v = values.reindex(days).fillna(0.0)
    f["val"] = np.where(f["cov"], v.values, np.nan)
    f["year"] = days.year
    f["week"] = week_of(days)
    return f


def weekly_totals(f: pd.DataFrame, p: Params) -> pd.DataFrame:
    g = f.groupby(["year", "week"])
    out = pd.DataFrame({
        "ndays": g.size(),
        "ncov": g["cov"].sum(),
        "sum": g["val"].sum(min_count=1),
    })
    ok = out["ncov"] >= np.ceil(p.couverture_min * out["ndays"])
    out["total"] = np.where(ok, out["sum"] * out["ndays"] / out["ncov"].where(out["ncov"] > 0), np.nan)
    return out.reset_index()


def assess(wk: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Ajoute expected, p_eleve, p_critique, n_ref, ratio, level, record, rank à chaque semaine."""
    years = sorted(wk["year"].unique())
    mat = wk.pivot(index="year", columns="week", values="total").reindex(index=years, columns=range(52))
    M = mat.values
    n = M.shape[0]
    exp = np.full(M.shape, np.nan); ph = exp.copy(); pc = exp.copy(); mx = exp.copy(); nref = np.zeros(M.shape, int)
    for i in range(n):
        others = np.delete(M, i, axis=0)
        for w in range(52):
            col = others[:, w]
            col = col[~np.isnan(col)]
            nref[i, w] = len(col)
            if len(col) >= p.min_annees:
                exp[i, w] = col.mean(); ph[i, w] = np.percentile(col, p.q_eleve)
                pc[i, w] = np.percentile(col, p.q_critique); mx[i, w] = col.max()
    idx = {y: i for i, y in enumerate(years)}
    ii = wk["year"].map(idx).values; ww = wk["week"].values
    wk = wk.copy()
    wk["expected"] = exp[ii, ww]; wk["p_eleve"] = ph[ii, ww]; wk["p_critique"] = pc[ii, ww]
    wk["n_ref"] = nref[ii, ww]; wk["max_others"] = mx[ii, ww]
    obs = wk["total"].values
    ratio = np.where(wk["expected"] > 0, obs / wk["expected"], np.nan)
    wk["ratio"] = ratio
    crit = (obs > wk["p_critique"]) & (ratio >= p.ratio_critique) & (obs >= p.plancher)
    haut = (obs > wk["p_eleve"]) & (ratio >= p.ratio_eleve) & (obs >= p.plancher)
    lvl = np.where(crit, "critique", np.where(haut, "eleve", "normal"))
    lvl = np.where(np.isnan(obs) | np.isnan(wk["expected"].values), "indetermine", lvl)
    wk["level"] = lvl
    wk["record"] = (obs > wk["max_others"]) & (ratio >= p.ratio_eleve) & (obs >= p.plancher)
    return wk


def episodes(wk: pd.DataFrame, level_key="level"):
    """Regroupe les semaines consécutives ET de même niveau (élevé avec élevé, critique avec critique)."""
    w = wk.sort_values(["year", "week"]).copy()
    w["g"] = w["year"] * 52 + w["week"]
    sel = w[w[level_key].isin(["eleve", "critique"])]
    out, cur = [], []
    for _, r in sel.iterrows():
        if cur and r["g"] == cur[-1]["g"] + 1 and r[level_key] == cur[-1][level_key]:
            cur.append(r)
        else:
            if cur: out.append(cur)
            cur = [r]
    if cur: out.append(cur)
    return out


# ------------------------------------------------------------------------------------------------
def series_from_rows(df: pd.DataFrame, col="n"):
    s = df.groupby("day")[col].sum()
    s.index = pd.to_datetime(s.index)
    return s


def same_window_totals(daily: pd.Series, covered: pd.DatetimeIndex, first, last, start, end):
    """Total de la fenêtre [start,end] et des fenêtres homologues (mêmes jour/mois) des autres années."""
    res = []
    for Y in range(first.year - (end.year - start.year) - 1, last.year + 2):
        off = Y - start.year
        try:
            s = start.replace(year=start.year + off)
        except ValueError:
            s = start.replace(year=start.year + off, day=28)
        try:
            e = end.replace(year=end.year + off)
        except ValueError:
            e = end.replace(year=end.year + off, day=28)
        if s < first or e > last:
            continue
        days = pd.date_range(s, e)
        cov = days.isin(covered)
        if cov.mean() < 0.8:
            continue
        v = daily.reindex(days).fillna(0.0).values
        tot = float(v[cov].sum() * len(days) / cov.sum())
        res.append({"year": Y, "start": s.date().isoformat(), "end": e.date().isoformat(),
                    "total": tot, "selected": off == 0})
    return res


def analyze(store, zone: dict, start: str, end: str, p: Params):
    """Analyse complète d'une zone et d'une période. Retourne un dict prêt pour le JSON."""
    t_start, t_end = pd.Timestamp(start), pd.Timestamp(end)
    if t_end < t_start:
        raise ValueError("La date de fin précède la date de début.")
    first, last = store.first_day, store.last_day
    if t_end < first or t_start > last:
        raise ValueError(f"Période hors des données ({first.date()} à {last.date()}).")
    t_start, t_end = max(t_start, first), min(t_end, last)

    poly = store.zone_polygon(zone)
    ids, approx = store.zone_cells(poly)
    area = store.area_km2(poly)
    info = {"n_cells": int(len(ids)), "area_km2": _nn(area, 0), "cells_area_km2": int(len(ids) * (store.grid_m / 1000) ** 2),
            "approximate": bool(approx), "centroid": [_nn(poly.centroid.x, 4), _nn(poly.centroid.y, 4)],
            "bounds": [_nn(v, 4) for v in poly.bounds]}
    if len(ids) == 0:
        return {"zone": info, "empty": True,
                "period": {"start": t_start.date().isoformat(), "end": t_end.date().isoformat()}}

    cur = store.cursor()
    cur.register("zone_ids", pd.DataFrame({"cell_id": ids.astype("int32")}))
    h = cur.execute("""SELECT d.day, sum(d.n_harm) AS n, sum(d.frp) AS frp, count(*) AS cells
                       FROM daily d JOIN zone_ids z USING (cell_id) GROUP BY d.day""").df()
    sraw = cur.execute("""SELECT d.sensor_id, d.day, sum(d.n) AS n FROM sensor_daily d JOIN zone_ids z USING (cell_id)
                          GROUP BY 1,2""").df()
    cur.unregister("zone_ids")

    cov_days = store.coverage.index[store.coverage["source"] != "aucune"]
    gap_days = store.coverage.index[store.coverage["source"] == "aucune"]
    daily = series_from_rows(h, "n"); frp = series_from_rows(h, "frp")

    # --- série harmonisée -> semaines -> anomalies
    f = calendar_frame(first, last, daily, cov_days)
    wk = assess(weekly_totals(f, p), p)
    bounds = [week_bounds(int(y), int(w)) for y, w in zip(wk["year"], wk["week"])]
    wk["start"] = [b[0] for b in bounds]; wk["end"] = [b[1] for b in bounds]

    # --- capteurs indépendants : même méthode sur chaque capteur
    sens_wk = {}
    names = dict(zip(store.sensors.sensor_id, store.sensors.name))
    roles = dict(zip(store.sensors.name, store.sensors.role))
    for sid, g in sraw.groupby("sensor_id"):
        nm = names[sid]
        s = series_from_rows(g, "n")
        fs = calendar_frame(first, last, s, store.sensor_days[nm])
        sens_wk[nm] = assess(weekly_totals(fs, p), p)
    # sensors with no row in zone still count as zero-fire sensors: handle those absent from sraw
    for sid, nm in names.items():
        if nm not in sens_wk:
            fs = calendar_frame(first, last, pd.Series(dtype=float), store.sensor_days[nm])
            sens_wk[nm] = assess(weekly_totals(fs, p), p)

    key = wk["year"].values * 52 + wk["week"].values
    n_eval = np.zeros(len(wk), int); n_flag = np.zeros(len(wk), int)
    for nm, sw in sens_wk.items():
        sk = dict(zip(sw["year"].values * 52 + sw["week"].values, sw["level"].values))
        for i, k in enumerate(key):
            lv = sk.get(k, "indetermine")
            if lv != "indetermine":
                n_eval[i] += 1
                if lv in ("eleve", "critique"):
                    n_flag[i] += 1
    wk["n_eval"] = n_eval; wk["n_flag"] = n_flag
    status = np.where(n_eval < 2, "non_verifiable",
                      np.where((n_flag >= 2) & (n_flag / np.maximum(n_eval, 1) >= 0.5), "confirmee",
                               np.where(n_flag >= 1, "isolee", "aucune")))
    wk["status"] = status

    # --- période demandée
    inwin = (wk["end"] >= t_start) & (wk["start"] <= t_end)
    wp = wk[inwin].copy()
    days = pd.date_range(t_start, t_end)
    covp = days.isin(cov_days)
    vals = daily.reindex(days).fillna(0.0).values
    lvl_by_week = {(int(r.year), int(r.week)): r.level for r in wk.itertuples()}
    stat_by_week = {(int(r.year), int(r.week)): r.status for r in wk.itertuples()}
    wkd = week_of(days)
    cal = []
    for d, v, c, w in zip(days, vals, covp, wkd):
        key_ = (d.year, int(w))
        cal.append([d.date().isoformat(), _nn(v, 2) if c else None, lvl_by_week.get(key_, "indetermine"), stat_by_week.get(key_, "non_verifiable")])
    frp_p = frp.reindex(days).fillna(0.0).values

    # --- fenêtre homologue : comparer la période avec les mêmes dates des autres années
    sw = same_window_totals(daily, cov_days, first, last, t_start, t_end)
    sel = [x for x in sw if x["selected"]]
    others = [x["total"] for x in sw if not x["selected"]]
    obs_total = float(vals[covp].sum() * len(days) / covp.sum()) if covp.any() else None
    kp = {"total": _nn(obs_total, 0), "frp_total": _nn(frp_p[covp].sum(), 0) if covp.any() else None,
          "days": int(len(days)), "days_covered": int(covp.sum()), "days_gap": int((~covp).sum()),
          "days_with_fire": int((vals[covp] > 0).sum()),
          "density_per_1000km2": _nn(obs_total / max(area, 1) * 1000, 2) if obs_total is not None else None,
          "expected": _nn(np.mean(others), 0) if len(others) >= p.min_annees else None,
          "n_years_ref": len(others)}
    kp["ratio"] = _nn(obs_total / np.mean(others), 2) if (obs_total is not None and len(others) >= p.min_annees and np.mean(others) > 0) else None
    if obs_total is not None and others:
        kp["rank"] = int(1 + sum(1 for o in others if o > obs_total)); kp["rank_of"] = len(others) + 1
    pk = int(np.argmax(np.where(covp, vals, -1))) if covp.any() else None
    kp["peak_day"] = days[pk].date().isoformat() if pk is not None else None
    kp["peak_value"] = _nn(vals[pk], 1) if pk is not None else None
    kp["weeks_critical"] = int((wp["level"] == "critique").sum()); kp["weeks_high"] = int((wp["level"] == "eleve").sum())
    kp["weeks_assessed"] = int((wp["level"] != "indetermine").sum()); kp["weeks_total"] = int(len(wp))

    # --- épisodes dans la période
    eps = []
    for ep in episodes(wp):
        df = pd.DataFrame(ep)
        crit = df["level"].iloc[0] == "critique"   # toutes les semaines d'un épisode ont le même niveau
        peak = df.loc[df["total"].idxmax()]
        exp_sum = float(df["expected"].sum()); tot_sum = float(df["total"].sum())
        stt = list(df["status"])
        conf = "confirmee" if stt.count("confirmee") >= max(1, len(stt) / 2) else ("isolee" if "isolee" in stt and "confirmee" not in stt else ("non_verifiable" if all(s == "non_verifiable" for s in stt) else "partielle"))
        eps.append({"start": df["start"].min().date().isoformat(), "end": df["end"].max().date().isoformat(),
                    "weeks": int(len(df)), "level": "critique" if crit else "eleve",
                    "observed": _nn(tot_sum, 0), "expected": _nn(exp_sum, 0), "ratio": _nn(tot_sum / exp_sum if exp_sum > 0 else None, 2),
                    "peak_week_start": peak["start"].date().isoformat(), "peak_ratio": _nn(peak["ratio"], 2),
                    "record": bool(df["record"].any()), "status": conf,
                    "sensors_flagging": int(df["n_flag"].max()), "sensors_evaluated": int(df["n_eval"].max())})
    eps.sort(key=lambda e: (-LEVEL_RANK[e["level"]], -((e["observed"] or 0) - (e["expected"] or 0))))

    weeks_out = [{"year": int(r.year), "week": int(r.week), "start": r.start.date().isoformat(), "end": r.end.date().isoformat(),
                  "total": _nn(r.total, 1), "expected": _nn(r.expected, 1), "p_eleve": _nn(r.p_eleve, 1), "p_critique": _nn(r.p_critique, 1),
                  "ratio": _nn(r.ratio, 2), "level": r.level, "record": bool(r.record), "status": r.status,
                  "n_flag": int(r.n_flag), "n_eval": int(r.n_eval)} for r in wp.itertuples()]

    # --- profil saisonnier complet (toutes années) : bande et courbes par année
    mat = wk.pivot(index="year", columns="week", values="total").reindex(columns=range(52))
    full_years = [int(y) for y in mat.index]
    seas = {"weeks": list(range(1, 53)),
            "mean": [_nn(v, 1) for v in np.nanmean(mat.values, axis=0)] if mat.notna().any().any() else [],
            "p_eleve": [_nn(v, 1) for v in np.nanpercentile(mat.values, p.q_eleve, axis=0)],
            "p_critique": [_nn(v, 1) for v in np.nanpercentile(mat.values, p.q_critique, axis=0)],
            "max": [_nn(v, 1) for v in np.nanmax(mat.values, axis=0)],
            "years": {str(y): [_nn(v, 1) for v in mat.loc[y].values] for y in full_years}}

    # --- capteurs : rapport observé/attendu par semaine de la période
    sensors_out = {}
    for nm, sw_ in sens_wk.items():
        pw = sw_[(pd.to_datetime([week_bounds(int(y), int(w))[1] for y, w in zip(sw_["year"], sw_["week"])]) >= t_start) &
                 (pd.to_datetime([week_bounds(int(y), int(w))[0] for y, w in zip(sw_["year"], sw_["week"])]) <= t_end)]
        sensors_out[nm] = {"role": roles[nm],
                           "years": int(sw_["total"].notna().groupby(sw_["year"]).any().sum()),
                           "weeks": [{"year": int(r.year), "week": int(r.week), "ratio": _nn(r.ratio, 2), "level": r.level,
                                      "total": _nn(r.total, 1)} for r in pw.itertuples()]}

    # --- état actuel : dernière semaine évaluée de l'ensemble des données
    ev = wk[wk["level"] != "indetermine"].sort_values(["year", "week"])
    current = None
    if len(ev):
        r = ev.iloc[-1]
        current = {"start": r["start"].date().isoformat(), "end": r["end"].date().isoformat(), "level": r["level"],
                   "ratio": _nn(r["ratio"], 2), "total": _nn(r["total"], 0), "expected": _nn(r["expected"], 0), "status": r["status"]}

    # --- échelle des couleurs du calendrier (comparable d'une période à l'autre)
    nz = daily[(daily > 0) & daily.index.isin(cov_days)]
    scale = {"p50": _nn(nz.quantile(0.5), 1), "p90": _nn(nz.quantile(0.9), 1), "p98": _nn(nz.quantile(0.98), 1), "max": _nn(nz.max(), 1)} if len(nz) else {}

    # --- carte de la zone : total par cellule sur la période
    cur2 = store.cursor()
    cur2.register("zone_ids2", pd.DataFrame({"cell_id": ids.astype("int32")}))
    cm = cur2.execute("""SELECT d.cell_id, sum(d.n_harm) AS v FROM daily d JOIN zone_ids2 z USING (cell_id)
                         WHERE d.day BETWEEN ? AND ? GROUP BY 1""", [t_start.date(), t_end.date()]).df()
    cur2.unregister("zone_ids2")
    cell_map = {"ids": [int(v) for v in ids], "values": None}
    s_ = pd.Series(cm["v"].values, index=cm["cell_id"].values).reindex(ids).fillna(0.0).values
    cell_map["values"] = [round(float(v), 1) for v in s_]

    return {
        "empty": False,
        "zone": info,
        "period": {"start": t_start.date().isoformat(), "end": t_end.date().isoformat()},
        "params": p.__dict__,
        "kpi": kp,
        "calendar": cal,
        "calendar_scale": scale,
        "weeks": weeks_out,
        "episodes": eps,
        "same_window": [{**x, "total": _nn(x["total"], 0)} for x in sw],
        "seasonal": seas,
        "sensors": sensors_out,
        "current": current,
        "cell_map": cell_map,
        "gaps_global": [d.date().isoformat() for d in gap_days if t_start <= d <= t_end],
        "dataset": store.meta.get("dataset"),
    }
