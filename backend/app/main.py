"""FastAPI application. Serves the JSON API under /api and the built React app at /."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .db import Base, engine
from .routers import ai, core, ops, orders
from .services.stock import StockError

app = FastAPI(title="Stockpilot", version="1.0.0", description="Multi-site warehouse & inventory management")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(StockError)
def stock_error(_: Request, exc: StockError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.on_event("startup")
def _create_tables():
    Base.metadata.create_all(engine)


@app.get("/api/health")
def health():
    return {"ok": True}


app.include_router(core.router)
app.include_router(orders.router)
app.include_router(ops.router)
app.include_router(ai.router)

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
