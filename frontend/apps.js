"""FastAPI app: JSON API under /api and the farmer web app served from /."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend import config, service
from backend.engine import llm
from backend.fetchers import builder, cache, gibs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fieldwise")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    builder.ensure_demo_caches()   # only does anything when FIELDWISE_DEMO=1 (development)
    log.info("FieldWise started. Data dir: %s. Development data: %s. Earth Engine: %s. ECOSTRESS: %s",
             config.CACHE_DIR, "ON" if config.DEMO_MODE else "off",
             "ready" if builder.gee_ready() else "not configured",
             "ready" if config.EARTHDATA_USERNAME else "not configured")
    yield


app = FastAPI(title="FieldWise API", version="2.0", lifespan=lifespan,
              description="NASA Earth observations -> crop-rotation decision support")
app.add_middleware(GZipMiddleware, minimum_size=1000)
if config.ALLOWED_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"])

CSP = ("default-src 'self'; img-src 'self' data: blob: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; script-src 'self'; "
       "connect-src 'self' https://nominatim.openstreetmap.org; worker-src 'self'; manifest-src 'self'; "
       "frame-ancestors 'self'; base-uri 'self'; form-action 'self'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
        response.headers.setdefault("Content-Security-Policy", CSP)
    if request.url.path.startswith("/static/vendor/"):
        response.headers.setdefault("Cache-Control", "public, max-age=604800")
    return response


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception):
    log.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side. Please try again."})


# ---------------------------------------------------------------- request models (validated input)
Lang = Literal["en", "fr", "tw", "ha"]


class Planting(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    crop: str = Field(max_length=40)
    year: int = Field(1, ge=1, le=2)
    sow_month: int = Field(ge=1, le=12)
    duration_m: int | None = Field(None, ge=1, le=12)
    with_crop: str | None = Field(None, alias="with", max_length=40)   # intercropped companion


class SoilTest(BaseModel):
    ph: float | None = Field(None, ge=3, le=10)
    soc: float | None = Field(None, ge=0, le=200)
    clay: float | None = Field(None, ge=0, le=100)
    sand: float | None = Field(None, ge=0, le=100)
    silt: float | None = Field(None, ge=0, le=100)


class Constraints(BaseModel):
    water: Literal["none", "little", "some", "full"] = "none"
    equipment: Literal["hand", "animal", "tractor"] | None = None
    keep_staple: bool = True
    staple: str | None = Field(None, max_length=40)
    avoid: list[str] = Field(default_factory=list, max_length=30)
    market: dict[str, Literal["good", "low", "no", "unsure"]] = Field(default_factory=dict)
    soil_test: SoilTest | None = None

    @field_validator("market")
    @classmethod
    def _limit_market(cls, v):
        if len(v) > 40:
            raise ValueError("too many crops")
        return v


class Scenario(BaseModel):
    rain_pct: float = Field(0, ge=-60, le=60)
    temp_c: float = Field(0, ge=-2, le=6)
    storm_pct: float = Field(0, ge=0, le=100)


class Priorities(BaseModel):
    water: float = Field(3, ge=0, le=5)
    nitrogen: float = Field(3, ge=0, le=5)
    organic_matter: float = Field(3, ge=0, le=5)
    erosion: float = Field(3, ge=0, le=5)
    infiltration: float = Field(2, ge=0, le=5)
    pest_break: float = Field(2, ge=0, le=5)
    income: float = Field(4, ge=0, le=5)
    forage: float = Field(1, ge=0, le=5)
    climate_fit: float = Field(3, ge=0, le=5)


class StrategyRequest(BaseModel):
    current: list[Planting] = Field(default_factory=list, max_length=12)
    priorities: Priorities = Field(default_factory=Priorities)
    constraints: Constraints = Field(default_factory=Constraints)
    scenario: Scenario | None = None
    lang: Lang = "en"


class ScoreRequest(StrategyRequest):
    plan: list[Planting] = Field(default_factory=list, max_length=12)


class WhatIfStrategy(BaseModel):
    id: str | None = Field(None, max_length=40)
    name: str | None = Field(None, max_length=80)
    plantings: list[Planting] = Field(default_factory=list, max_length=12)


class WhatIfRequest(BaseModel):
    strategies: list[WhatIfStrategy] = Field(max_length=8)
    scenario: Scenario = Field(default_factory=Scenario)
    priorities: Priorities = Field(default_factory=Priorities)
    constraints: Constraints = Field(default_factory=Constraints)


class FetchRequest(BaseModel):
    lat: float = Field(ge=-60, le=75)
    lon: float = Field(ge=-180, le=180)
    name: str = Field("My field", min_length=1, max_length=60)


class ExplainRequest(BaseModel):
    strategy: dict
    site_name: str = Field("", max_length=80)
    language: str = Field("English", max_length=30)


def _dump(model: BaseModel) -> dict:
    return model.model_dump(exclude_none=True, by_alias=True)


# ---------------------------------------------------------------- read endpoints
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "earth_engine": builder.gee_ready(), "ecostress": bool(config.EARTHDATA_USERNAME),
            "llm_enabled": llm.available(), "development_data": config.DEMO_MODE,
            "record": f"{config.START_YEAR}-{config.END_YEAR}"}


@app.get("/api/reference-sites")
def reference_sites() -> list[dict]:
    return service.reference_sites()


@app.get("/api/crops")
def crops() -> list[dict]:
    return service.crops_public()


@app.get("/api/imagery")
def imagery() -> dict:
    try:
        return gibs.themes()
    except Exception as err:  # noqa: BLE001
        log.warning("GIBS capabilities unavailable: %s", err)
        raise HTTPException(503, "NASA satellite imagery service is not reachable right now") from err


def _site(site_id: str):
    if not cache.exists(site_id):
        raise HTTPException(404, "Field not found. It may still be downloading.")
    try:
        return service.get_site(site_id)
    except FileNotFoundError as err:
        raise HTTPException(404, "Field not found") from err


@app.get("/api/sites/{site_id}")
def site_status(site_id: str) -> dict:
    if not cache.exists(site_id):
        raise HTTPException(404, "Field not found")
    return service.site_summary(site_id)


@app.get("/api/sites/{site_id}/profile")
def profile(site_id: str, rain_pct: float = 0, temp_c: float = 0, storm_pct: float = 0, lang: Lang = "en") -> dict:
    sc = _dump(Scenario(rain_pct=rain_pct, temp_c=temp_c, storm_pct=storm_pct))
    return _site(site_id).profile(sc, lang)


@app.post("/api/sites/{site_id}/strategies")
def strategies(site_id: str, body: StrategyRequest) -> dict:
    return _site(site_id).strategies(_dump(body))


@app.post("/api/sites/{site_id}/score")
def score(site_id: str, body: ScoreRequest) -> dict:
    return _site(site_id).score(_dump(body))


@app.post("/api/sites/{site_id}/whatif")
def whatif(site_id: str, body: WhatIfRequest) -> dict:
    return _site(site_id).whatif(_dump(body))


@app.post("/api/sites/{site_id}/gauge")
async def gauge(site_id: str, file: UploadFile = File(...)) -> dict:
    raw = await file.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(413, "File too large (max 2 MB)")
    try:
        return _site(site_id).fuse_gauge(raw.decode("utf-8", errors="replace"))
    except ValueError as err:
        raise HTTPException(400, str(err)) from err


@app.post("/api/explain")
def explain_plain(body: ExplainRequest) -> dict:
    return llm.explain_plain(body.strategy, body.site_name, body.language)


# ---------------------------------------------------------------- new field download (rate limited, phased)
_jobs: dict[str, dict] = {}
_recent: dict[str, deque] = defaultdict(deque)
_slots = threading.Semaphore(config.MAX_CONCURRENT_FETCHES)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _cleanup_jobs() -> None:
    cutoff = time.time() - 6 * 3600
    for jid in [j for j, v in _jobs.items() if v["started"] < cutoff]:
        _jobs.pop(jid, None)


def _run_fetch(job_id: str, req: FetchRequest) -> None:
    job = _jobs[job_id]

    def progress(ev: dict) -> None:
        job["stage"] = ev.get("stage")
        job["message"] = ev.get("message")
        if "done" in ev:
            job["done"], job["total"] = ev["done"], ev["total"]
        if ev.get("stage") == "ready":
            job["site_id"] = ev["site_id"]
            job["status"] = "ready"

    with _slots:
        try:
            site_id = builder.build_live(req.lat, req.lon, req.name, log=lambda m: job["log"].append(m),
                                         progress=progress)
            service.forget_site(site_id)
            job.update(status="done", site_id=site_id)
        except Exception as err:  # noqa: BLE001
            log.exception("Fetch failed")
            job.update(status="error" if not job.get("site_id") else "done",
                       error="Could not download NASA data for this place. Please check the internet connection and try again."
                       if not job.get("site_id") else None)
            job["log"].append(f"ERROR: {err}")


@app.post("/api/fields")
def create_field(req: FetchRequest, request: Request) -> dict:
    ip = _client_ip(request)
    now = time.time()
    q = _recent[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= config.FETCH_LIMIT_PER_HOUR:
        raise HTTPException(429, "Too many new fields from this connection. Please try again in an hour.")
    q.append(now)
    _cleanup_jobs()
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "running", "stage": "queued", "message": "Waiting for a free slot", "log": [],
                     "site_id": None, "started": now}
    threading.Thread(target=_run_fetch, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Unknown job")
    return {k: v for k, v in j.items() if k != "log"} | {"log_tail": j["log"][-6:]}


# ---------------------------------------------------------------- frontend
app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-cache"})

