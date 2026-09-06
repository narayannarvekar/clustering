from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api_clusters import router as clusters_router
from app.api_map import router as map_router
from app.schemas import HealthResponse

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(title="Delivery Friction Clustering Service")
app.include_router(clusters_router)
app.include_router(map_router)


@app.get("/api/health", response_model=HealthResponse, tags=["system"], summary="Liveness check")
def health():
    """Trivial liveness check — returns `{"status": "ok"}` if the process is up."""
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


@app.middleware("http")
async def no_store_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response
