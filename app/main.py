from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import structlog
import time
from app.heatmap import router as heatmap_router
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.ingestion import router as ingest_router
from app.metrics   import router as metrics_router
from app.funnel    import router as funnel_router
from app.anomalies import router as anomaly_router
from app.health    import router as health_router

from app.dashboard.live import router as dashboard_router


log = structlog.get_logger()


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup.begin")
    await init_db()
    log.info("startup.db_ready")
    yield
    log.info("shutdown")


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Storelytics API",
    description="Real-time retail analytics from CCTV event streams",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Middleware — request logging ───────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=latency_ms,
    )
    return response

# ── Error handlers ─────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", error=str(exc), path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": "An unexpected error occurred"},
    )


# ── Routers ────────────────────────────────────────────────────────────────────


app.include_router(ingest_router)
app.include_router(metrics_router)
app.include_router(funnel_router)
app.include_router(anomaly_router)
app.include_router(health_router)
app.include_router(heatmap_router)
app.include_router(dashboard_router)



# ── Root ───────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"service": "store-intelligence", "status": "running"}