#!/usr/bin/env python3
# server.py — Events API + Analysis (MongoDB)

import os
import json
import re
import time
import random
import requests
import datetime as dt
from typing import Optional, List
from fastapi import FastAPI, Query, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

load_dotenv()

# ===== Config (.env) =====
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "omnistatus")
MONGO_COLL_NAME = os.getenv("MONGO_COLL_NAME", "events")
MONGO_COLL_VICTORIA = os.getenv("MONGO_COLL_VICTORIA", "victoria_history")
API_TOKEN = os.getenv("API_TOKEN")  # Optional API key for write/query endpoints

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are an expert security system. "
    "You must respond EXCLUSIVELY with valid JSON containing keys: "
    "{\"score\": float between 0 and 1, \"text\": string}. "
    "Do not include anything outside the JSON object."
)

PROMPT_ANALYSIS = os.getenv(
    "PROMPT_ANALYSIS",
    "Analyze events and return JSON {\"score\":float,\"text\":string}."
)

# ===== MongoDB Setup =====
client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
coll = db[MONGO_COLL_NAME]
coll_victoria = db[MONGO_COLL_VICTORIA]

def ensure_indexes():
    try:
        coll.create_index("timestamp")
        coll.create_index("source")
        coll.create_index("text")
        coll_victoria.create_index("timestamp")
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


def extract_score(ev: dict) -> Optional[float]:
    for key in ("score", "value", "valor", "promedio"):
        val = ev.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    return None

def save_event(ev: dict):
    ts = to_datetime(ev.get("timestamp"))
    if ts:
        ev["timestamp"] = ts
    try:
        coll.insert_one(ev)
    except PyMongoError as e:
        print(f"⚠ Error saving event: {e}")

def load_events(hours: int) -> List[dict]:
    cutoff_dt = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=max(1, hours))
    ts_filter = {"$or": [{"timestamp": {"$gte": cutoff_dt}}, {"timestamp": {"$gte": cutoff_dt.isoformat()}}]}
    try:
        events = list(coll.find(ts_filter))
        for ev in events:
            ts = to_datetime(ev.get("timestamp"))
            if ts:
                ev["timestamp"] = ts.isoformat()
        return events
    except PyMongoError as e:
        print(f"⚠ Error loading events: {e}")
        return []

# ===== HTTP + Retry =====
def with_retries(request_fn, max_attempts=3, base_delay=1.0, max_delay=15.0):
    attempt = 0
    while True:
        try:
            return request_fn()
        except Exception as e:
            attempt += 1
            status = getattr(getattr(e, "response", None), "status_code", None)
            retriable = isinstance(e, requests.Timeout) or status in {429, 500, 502, 503, 504}
            if attempt >= max_attempts or not retriable:
                raise
            sleep_s = min(max_delay, base_delay * (2 ** (attempt - 1)))
            if status == 429:
                sleep_s *= 2
            sleep_s *= (0.6 + random.random() * 0.8)
            time.sleep(sleep_s)

# ===== OpenAI Analyzer =====
def openai_analyze(events: List[dict]) -> dict:
    events_text = "\n".join(
        f"[{e.get('timestamp')}] {e.get('source')}: {e.get('text')} (score={e.get('score')})"
        for e in events
    ) or "(no events)"

    system_msg = SYSTEM_PROMPT
    user_msg = f"{PROMPT_ANALYSIS}\n\nEvents:\n{events_text}"

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    if not OPENAI_API_KEY:
        return {"score": 0.0, "text": "Missing OPENAI_API_KEY"}

    try:
        def _r():
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )
            if resp.status_code in {429, 500, 502, 503, 504}:
                resp.raise_for_status()
            return resp

        r = with_retries(_r)

        if r.status_code != 200:
            return {"score": 0.0, "text": f"OpenAI {r.status_code}: {r.text[:200]}"}

        content = r.json()["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except Exception:
            m = re.search(r"\{.*\}", content, flags=re.DOTALL)
            parsed = json.loads(m.group(0)) if m else {"score": 0.0, "text": "Parse error"}

        score = float(parsed.get("score", 0.0))
        text = parsed.get("text") or "No summary"
        return {"score": max(0.0, min(score, 1.0)), "text": text}

    except Exception as e:
        return {"score": 0.0, "text": f"Analysis error: {e}"}


def summarize_events_3h(limit_buckets: int = 200) -> List[dict]:
    return summarize_collection(coll, mode="3h", limit_buckets=limit_buckets)


def summarize_events_day(limit_buckets: int = 200) -> List[dict]:
    return summarize_collection(coll, mode="day", limit_buckets=limit_buckets)


def summarize_collection(target_coll, mode: str, limit_buckets: int = 200) -> List[dict]:
    try:
        raw = list(
            target_coll.find({}, sort=[("timestamp", -1)], projection={"_id": 0}).limit(5000)
        )
    except PyMongoError as e:
        print(f"⚠ Error reading events: {e}")
        return []

    buckets = {}
    for ev in raw:
        ts = ev.get("timestamp")
        d = to_datetime(ts)
        if not d:
            continue

        if mode == "3h":
            d = d.replace(minute=0, second=0, microsecond=0)
            bucket_hour = (d.hour // 3) * 3
            start = d.replace(hour=bucket_hour)
            key = start.isoformat()
            bucket = buckets.setdefault(
                key,
                {"period": key, "tipo": "3h", "count": 0, "scores": [], "texts": []},
            )
        else:
            date_key = d.date().isoformat()
            bucket = buckets.setdefault(
                date_key,
                {"date": date_key, "tipo": "dia", "count": 0, "scores": [], "texts": []},
            )

        bucket["count"] += 1
        sc = extract_score(ev)
        if sc is not None:
            bucket["scores"].append(sc)
        if len(bucket["texts"]) < 3:
            txt = ev.get("text") or ev.get("texto") or ev.get("description") or ev.get("msg")
            if txt:
                bucket["texts"].append(str(txt))

    items = []
    for _, data in buckets.items():
        avg = sum(data["scores"]) / len(data["scores"]) if data["scores"] else None
        entry = {
            "text": " | ".join(data["texts"]) if data["texts"] else "No samples",
            "score": avg if avg is not None else "—",
            "hash": f"{data['count']} evts",
            "tipo": data["tipo"],
        }
        if mode == "3h":
            entry["period"] = data["period"]
        else:
            entry["date"] = data["date"]
        items.append(entry)

    sort_key = "period" if mode == "3h" else "date"
    items.sort(key=lambda x: x.get(sort_key, ""), reverse=True)
    return items[:limit_buckets]


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


@app.get("/events/summary/3h")
def summary_3h(_: bool = Depends(require_api_key), limit: int = Query(200, ge=1, le=1000)):
    items = summarize_events_3h(limit)
    return {"count": len(items), "items": items}


@app.get("/events/summary/day")
def summary_day(_: bool = Depends(require_api_key), limit: int = Query(200, ge=1, le=1000)):
    items = summarize_events_day(limit)
    return {"count": len(items), "items": items}


@app.get("/victoria/history")
def victoria_history(
    _: bool = Depends(require_api_key),
    start: Optional[str] = None,
    end: Optional[str] = None,
    source: Optional[str] = None,
    text: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    return query_collection(coll_victoria, start, end, source, text, limit)


@app.get("/victoria/history/summary/3h")
def victoria_summary_3h(_: bool = Depends(require_api_key), limit: int = Query(200, ge=1, le=1000)):
    items = summarize_collection(coll_victoria, mode="3h", limit_buckets=limit)
    return {"count": len(items), "items": items}


@app.get("/victoria/history/summary/day")
def victoria_summary_day(_: bool = Depends(require_api_key), limit: int = Query(200, ge=1, le=1000)):
    items = summarize_collection(coll_victoria, mode="day", limit_buckets=limit)
    return {"count": len(items), "items": items}

@app.get("/analyze")
def analyze(_: bool = Depends(require_api_key), hours: int = Query(1, ge=1, le=168)):
    if not OPENAI_API_KEY:
        return {"status": "config_error", "msg": "Missing OPENAI_API_KEY", "score": 0.0}
    events = load_events(hours)
    if not events:
        return {
            "status": "no_events",
            "score": 0.0,
            "msg": "No recent events.",
            "events_count": 0,
            "window_hours": hours,
        }
    res = openai_analyze(events)
    return {
        "status": "ok",
        "score": float(res.get("score", 0.0)),
        "msg": res.get("text", "No summary"),
        "events_count": len(events),
        "window_hours": hours,
    }

# ===== Main =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=False)
