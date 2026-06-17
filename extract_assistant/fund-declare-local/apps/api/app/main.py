from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes_cases import router as cases_router
from app.api.routes_debug import router as debug_router
from app.api.routes_files import router as files_router

app = FastAPI(title="Fund Declare Local API")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(cases_router)
app.include_router(debug_router)
app.include_router(files_router)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "api": "running",
    }
