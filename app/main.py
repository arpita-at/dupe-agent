"""FastAPI wrapper. Returns a claim file for a person to work. Recovers nothing."""
from __future__ import annotations

import csv
import hmac
import io
import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from .io import load, row_to_payment
from .pipeline import run

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
MAX_BYTES = int(os.environ.get("DUPE_MAX_BYTES", 8 * 1024 * 1024))
MAX_ROWS = int(os.environ.get("DUPE_MAX_ROWS", 100_000))
TOKEN = os.environ.get("DUPE_API_TOKEN")

app = FastAPI(title="dupe-agent", version="0.1.0",
              description="Duplicate supplier payment detection. Rules find the pairs; a model only argues against them.")


def auth(authorization: str | None = Header(default=None)) -> None:
    """No token set means local use. Set DUPE_API_TOKEN before exposing this:
    the input is a full AP ledger, which is commercially sensitive on its own,
    and every uncertain pair can cost a model call."""
    if not TOKEN:
        return
    if not hmac.compare_digest(authorization or "", f"Bearer {TOKEN}"):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).resolve().parent / "index.html").read_text(encoding="utf-8")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/api/demo", dependencies=[Depends(auth)])
def demo() -> JSONResponse:
    return JSONResponse(run(load(SAMPLES / "payments.csv")))


@app.post("/api/scan", dependencies=[Depends(auth)])
async def scan(payments: UploadFile = File(...)) -> JSONResponse:
    raw = await payments.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, f"payments is larger than {MAX_BYTES} bytes")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows) > MAX_ROWS:
        raise HTTPException(413, f"payments has more than {MAX_ROWS} rows")
    try:
        items = [row_to_payment(r) for r in rows]
    except (KeyError, ValueError) as e:
        raise HTTPException(422, f"Bad payments CSV: {e}")
    return JSONResponse(run(items))
