#!/usr/bin/env python3
"""Helpbar: barra de referencia Markdown estilo Office (puerto 8001)."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="PurpleMD Helpbar", description="Barra de referencia Markdown")

BASE = Path(__file__).parent
STATIC = BASE / "static"

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", media_type="text/html")


@app.get("/health")
def health() -> dict:
    return {"estado": "ok"}
