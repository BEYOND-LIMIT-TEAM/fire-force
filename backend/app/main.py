"""API Fire Force (FastAPI). Lance : uvicorn app.main:app --reload   (FIREFORCE_DB=chemin/fireforce.duckdb)"""
import os
import time
import numpy as np
import pandas as pd
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal, Optional

from .analytics import Params, analyze, _nn
from .store import Store

DB = os.environ.get("FIREFORCE_DB", str(Path(__file__).resolve().parents[2] / "data" / "fireforce.duckdb"))
FRONT = Path(os.environ.get("FIREFORCE_FRONT", Path(__file__).resolve().parents[2] / "frontend"))

app = FastAPI(title="Fire Force API", version="1.0",
              description="Calendrier des feux actifs harmonisés (MODIS / VIIRS) pour l'Afrique.")
app.add_middleware(GZipMiddleware, minimum_size=1000)
_store: Optional[Store] = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store(DB)
    return _store


class Zone(BaseModel):
    type: Literal["bbox", "polygon"]
    bbox: Optional[list[float]] = Field(None, description="[ouest, sud, est, nord] en degrés")
    coordinates: Optional[list[list[float]]] = Field(None, description="[[lon, lat], ...] anneau du polygone")


class AnalyzeIn(BaseModel):
    zone: Zone
    start: str = Field(..., description="AAAA-MM-JJ")
    end: str
    q_eleve: float = Field(75, ge=50, le=99)
    q_critique: float = Field(90, ge=50, le=99.9)
    ratio_eleve: float = Field(1.25, ge=1, le=10)
    ratio_critique: float = Field(1.5, ge=1, le=10)
    plancher: float = Field(10, ge=0, le=1e6)
    min_annees: int = Field(4, ge=2, le=30)


@app.get("/api/health")
def health():
    s = store()
    n = s.cursor().execute("SELECT 1").fetchone()[0]
    return {"status": "ok" if n == 1 else "erreur", "db": os.path.basename(DB), "dataset": s.meta.get("dataset")}


@app.get("/api/meta")
def meta():
    s = store()
    return {
        "dataset": s.meta.get("dataset"), "first_day": s.meta["first_day"], "last_day": s.meta["last_day"],
        "grid_km": s.grid_m // 1000, "n_cells": int(len(s.cells)), "reference": s.meta.get("reference"),
        "gap_days": int(s.meta.get("gap_days", 0)), "built_at": s.meta.get("built_at"),
        "sensors": [{"name": r.name, "role": r.role, "first_day": str(r.first_day), "last_day": str(r.last_day), "rows": int(r.n_rows)}
                    for r in s.sensors.itertuples()],
        "defaults": Params().__dict__,
    }


@app.get("/api/cells")
def cells():
    """Géométrie de la grille (une seule fois par session) : identifiants + 4 coins lon/lat par cellule."""
    s = store()
    c = s.cells
    corners = []
    for k in range(4):
        corners.append(c[f"lon{k}"].round(3).tolist()); corners.append(c[f"lat{k}"].round(3).tolist())
    return JSONResponse({"ids": c["cell_id"].tolist(), "lon": c["lon"].tolist(), "lat": c["lat"].tolist(),
                         "corners": corners}, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/map")
def map_totals(start: str, end: str):
    """Total harmonisé par cellule sur la période, dans l'ordre de /api/cells."""
    s = store()
    v = s.overview_map(start, end)
    return {"values": [round(float(x), 1) for x in v], "start": start, "end": end}


@app.get("/api/hotspots")
def hotspots(n: int = 450):
    """Quelques centaines de cellules parmi les plus actives des 12 derniers mois de données (page d'accueil)."""
    n = max(10, min(n, 1500))
    s = store()
    end = pd.Timestamp(s.meta["last_day"]); start = (end - pd.Timedelta(days=364)).date().isoformat()
    v = np.asarray(s.overview_map(start, str(end.date())), dtype=float)
    top = np.argsort(v)[::-1][: n * 3]
    top = top[v[top] > 0][::3]
    if len(top) == 0:
        return JSONResponse({"lon": [], "lat": [], "v": []})
    c = s.cells
    return JSONResponse({"lon": c["lon"].values[top].round(2).tolist(), "lat": c["lat"].values[top].round(2).tolist(),
                         "v": (v[top] / v[top].max()).round(3).tolist(), "start": start, "end": str(end.date())},
                        headers={"Cache-Control": "public, max-age=3600"})


@app.post("/api/analyze")
def do_analyze(body: AnalyzeIn):
    s = store()
    z = body.zone.model_dump()
    p = Params(q_eleve=body.q_eleve, q_critique=body.q_critique, ratio_eleve=body.ratio_eleve,
               ratio_critique=body.ratio_critique, plancher=body.plancher, min_annees=body.min_annees)
    t0 = time.time()
    try:
        out = analyze(s, z, body.start, body.end, p)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    out["elapsed_ms"] = int((time.time() - t0) * 1000)
    return out


if FRONT.exists():
    app.mount("/static", StaticFiles(directory=str(FRONT)), name="static")

    @app.get("/")
    @app.get("/about")
    @app.get("/app")
    def index():
        return FileResponse(FRONT / "index.html")
