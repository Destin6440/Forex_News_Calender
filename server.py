"""FastAPI server: serves the dashboard and proxies keyed market/news APIs."""
from __future__ import annotations

import os
from pathlib import Path

import requests
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from ff_calendar_toolkit.news_api import load_dashboard_news
from ff_calendar_toolkit.runtime import load_env_file

load_env_file()

ROOT = Path(__file__).parent
TD_API_KEY = os.environ.get("TD_API_KEY", "")
CMC_API_KEY = os.environ.get("CMC_API_KEY", "")
NEWS_DIR = Path(os.environ.get("FF_OUTPUT_DIR", "news"))

TD_BASE = "https://api.twelvedata.com"
CMC_QUOTES_URL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"

app = FastAPI()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "index.html", media_type="text/html")
