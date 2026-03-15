"""
api/index.py
-------------
Vercel serverless endpoint. Vercel detects FastAPI (ASGI) and handles
serving automatically — no uvicorn or mangum needed in production.

Routes:
  GET /api/snapshot            -> full snapshot + all 3 timeframe scores + planet positions
  GET /api/snapshot?date=YYYY-MM-DD -> snapshot for specific date at noon UTC
  GET /api/year                -> array of daily scores for a year
  GET /api/year?year=2026      -> scores for specified year
  GET /api/health              -> liveness check
"""

import os
import sys

# Make root-level modules (scoring_model, astro_data) importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataclasses import asdict
from datetime import datetime, timezone, date as date_type
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from astro_data import build_snapshot, build_chart, snapshot_from_chart, build_planet_data
from scoring_model import score, score_all

app = FastAPI(title="AstroMarket API", docs_url=None, redoc_url=None)

# ---------------------------------------------------------------------------
# CORS — allow any origin for now; lock down to your GoDaddy domain later
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return RedirectResponse(url="/index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/api/snapshot")
def get_snapshot(
    tf: Literal["short", "mid", "long"] | None = Query(
        default=None,
        description="Timeframe filter. Omit to get all three."
    ),
    date: str | None = Query(
        default=None,
        description="Date in YYYY-MM-DD format. Defaults to now. Uses noon UTC of that date."
    ),
):
    """
    Returns astrological snapshot + sentiment scores + planet positions.

    Query params:
      tf   = short | mid | long   (optional — returns all if omitted)
      date = YYYY-MM-DD           (optional — defaults to now)
    """
    dt = None
    if date is not None:
        try:
            parsed = datetime.strptime(date, "%Y-%m-%d")
            dt = datetime(parsed.year, parsed.month, parsed.day, 12, 0, 0, tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    chart = build_chart(dt)
    snapshot = snapshot_from_chart(chart)
    snapshot_dict = asdict(snapshot)
    planets = build_planet_data(chart)

    if tf:
        scores = {tf: score(snapshot, tf)}
    else:
        scores = score_all(snapshot)

    timestamp = dt.isoformat() if dt else datetime.now(timezone.utc).isoformat()

    return {
        "timestamp": timestamp,
        "snapshot":  snapshot_dict,
        "scores":    scores,
        "planets":   planets,
    }


@app.get("/api/year")
def get_year(
    year: int = Query(
        default=None,
        description="Year to fetch scores for. Defaults to current year."
    ),
):
    """
    Returns an array of daily sentiment scores for each day of the given year.

    Query params:
      year = int  (optional — defaults to current year)

    Response:
      { "year": 2026, "days": [{ "date": "2026-01-01", "short": 0.3, "mid": -0.1, "long": 0.5 }, ...] }
    """
    if year is None:
        year = datetime.now(timezone.utc).year

    # Validate year is reasonable
    if year < 1900 or year > 2100:
        raise HTTPException(status_code=400, detail="Year must be between 1900 and 2100.")

    days = []
    # Iterate over every day of the year
    import calendar
    num_days = 366 if calendar.isleap(year) else 365

    for day_num in range(num_days):
        # Build datetime for noon UTC of each day
        dt = datetime(year, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # Add day_num days
        from datetime import timedelta
        dt = dt + timedelta(days=day_num)

        chart = build_chart(dt)
        snapshot = snapshot_from_chart(chart)

        short_result = score(snapshot, "short")
        mid_result   = score(snapshot, "mid")
        long_result  = score(snapshot, "long")

        days.append({
            "date":  dt.strftime("%Y-%m-%d"),
            "short": short_result["total"],
            "mid":   mid_result["total"],
            "long":  long_result["total"],
        })

    return {
        "year": year,
        "days": days,
    }
