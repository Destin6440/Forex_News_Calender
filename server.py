"""FastAPI server: serves the dashboard and proxies keyed market/news APIs."""
from __future__ import annotations

import os
import time
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


@app.get("/api/news")
def api_news() -> JSONResponse:
    now_ms = int(time.time() * 1000)
    return JSONResponse(load_dashboard_news(NEWS_DIR, now_ms))


def _passthrough(resp: requests.Response) -> JSONResponse:
    try:
        body = resp.json()
    except ValueError:
        body = {"error": "upstream returned non-JSON"}
    return JSONResponse(body, status_code=resp.status_code)


@app.get("/api/td/quote")
def td_quote(request: Request) -> JSONResponse:
    params = dict(request.query_params)
    params["apikey"] = TD_API_KEY
    resp = requests.get(f"{TD_BASE}/quote", params=params, timeout=15)
    return _passthrough(resp)


@app.get("/api/td/time_series")
def td_time_series(request: Request) -> JSONResponse:
    params = dict(request.query_params)
    params["apikey"] = TD_API_KEY
    resp = requests.get(f"{TD_BASE}/time_series", params=params, timeout=15)
    return _passthrough(resp)


@app.get("/api/cmc/quotes")
def cmc_quotes(request: Request) -> JSONResponse:
    params = dict(request.query_params)
    params.setdefault("convert", "USD")
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    resp = requests.get(CMC_QUOTES_URL, params=params, headers=headers, timeout=15)
    return _passthrough(resp)
