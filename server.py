#!/usr/bin/env python3
# server.py — Events API (MongoDB)
# Refactored: Analysis logic moved to Victoria. This server only stores events.

import os
import datetime as dt
from typing import Optional
from fastapi import FastAPI, Query, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

load_dotenv()

# ===== Config (.env) =====
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "omnistatus")
MONGO_COLL_NAME = os.getenv("MONGO_COLL_NAME", "events")
API_TOKEN = os.getenv("API_TOKEN")  # Optional API key for write/query endpoints

# ===== MongoDB Setup =====
client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
coll = db[MONGO_COLL_NAME]

def ensure_indexes():
    try:
        coll.create_index("timestamp")
        coll.create_index("source")
        coll.create_index("text")
    except PyMongoError as e:
        print(f"⚠ Error creating indexes: {e}")

ensure_indexes()

# ===== App =====
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Event Model =====
class Event(BaseModel):
    source: str
    text: str            # event description
    score: Optional[float] = None  # risk level
    timestamp: Optional[str] = None  # ISO8601 string


def require_api_key(x_api_key: Optional[str] = Header(None)):
    if API_TOKEN and x_api_key != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API token")
    return True

# ===== Utils =====
def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def to_datetime(value) -> Optional[dt.datetime]:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            else:
                parsed = parsed.astimezone(dt.timezone.utc)
            return parsed
        except Exception:
            return None
    return None

def parse_iso_dt(value: str) -> Optional[dt.datetime]:
    """Parses flexible ISO8601 dates and returns normalized UTC datetime."""
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        else:
            parsed = parsed.astimezone(dt.timezone.utc)
        return parsed
    except Exception:
        return None

def serialize_event(doc: dict) -> dict:
    data = dict(doc)
    if "_id" in data:
        data["_id"] = str(data["_id"])
    ts = data.get("timestamp")
    if isinstance(ts, dt.datetime):
        data["timestamp"] = ts.astimezone(dt.timezone.utc).isoformat()
    return data

def save_event(ev: dict):
    ts = to_datetime(ev.get("timestamp"))
    if ts:
        ev["timestamp"] = ts
    try:
        coll.insert_one(ev)
    except PyMongoError as e:
        print(f"⚠ Error saving event: {e}")

def query_collection(
    target_coll,
    start: Optional[str],
    end: Optional[str],
    source: Optional[str],
    text: Optional[str],
    limit: int,
):
    filters = []
    ts_filters = []
    ts_range_dt = {}
    ts_range_str = {}
    if start:
        start_dt = parse_iso_dt(start)
        if not start_dt:
            return {"count": 0, "items": [], "error": "invalid start (ISO8601)"}
        ts_range_dt["$gte"] = start_dt
        ts_range_str["$gte"] = start_dt.isoformat()
    if end:
        end_dt = parse_iso_dt(end)
        if not end_dt:
            return {"count": 0, "items": [], "error": "invalid end (ISO8601)"}
        ts_range_dt["$lte"] = end_dt
        ts_range_str["$lte"] = end_dt.isoformat()
    if ts_range_dt:
        ts_filters.append({"timestamp": ts_range_dt})
    if ts_range_str:
        ts_filters.append({"timestamp": ts_range_str})
    if ts_filters:
        filters.append({"$or": ts_filters} if len(ts_filters) > 1 else ts_filters[0])

    if source:
        filters.append({"source": {"$regex": source, "$options": "i"}})

    if text:
        filters.append(
            {
                "$or": [
                    {"text": {"$regex": text, "$options": "i"}},
                    {"description": {"$regex": text, "$options": "i"}},
                ]
            }
        )

    if not filters:
        mongo_filter = {}
    elif len(filters) == 1:
        mongo_filter = filters[0]
    else:
        mongo_filter = {"$and": filters}

    try:
        events = [
            serialize_event(e)
            for e in target_coll.find(mongo_filter, sort=[("timestamp", -1)]).limit(limit)
        ]
        return {"count": len(events), "items": events, "applied_filter": mongo_filter}
    except PyMongoError as e:
        return {"count": 0, "items": [], "error": str(e), "applied_filter": mongo_filter}

# ===== Endpoints =====
@app.get("/health")
def health():
    return {"ok": True, "ts": now_iso()}

@app.post("/event")
def add_event(ev: Event, _: bool = Depends(require_api_key)):
    data = ev.dict()
    ts = to_datetime(data.get("timestamp"))
    if not ts:
        ts = dt.datetime.now(dt.timezone.utc)
    data["timestamp"] = ts
    save_event(data)
    return {"status": "stored"}

@app.get("/events")
def list_events(
    _: bool = Depends(require_api_key),
    start: Optional[str] = None,
    end: Optional[str] = None,
    source: Optional[str] = None,
    text: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    return query_collection(coll, start, end, source, text, limit)


# ===== Main =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=False)
