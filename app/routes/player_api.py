"""Public protocol metadata; execution belongs to miniworlds-editor."""
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends
from ..config import Settings
from ..deps import get_settings

router = APIRouter(tags=["compatibility"])
API_MANIFEST = json.loads((Path(__file__).resolve().parents[1] / "compatibility.json").read_text())


@router.get("/api/compatibility")
def compatibility():
    return {**API_MANIFEST, "revision": os.environ.get("BACKEND_REVISION", "development")}


@router.get("/api/player/config", include_in_schema=False)
def player_config(settings: Settings = Depends(get_settings)):
    return {"editor_url": settings.editor_url, "api_version": API_MANIFEST["api"]["max"]}
