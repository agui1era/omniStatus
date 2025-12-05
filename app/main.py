import datetime as dt
from typing import Optional, List
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import db, get_event_collection, get_victoria_collection
from app.models import Event
from app.services.llm import openai_analyze_events

# ===== App =====
app = FastAPI(title=settings.APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_db_client():
    db.connect()

@app.on_event("shutdown")
async def shutdown_db_client():
    db.close()

# ===== Utils =====
def now_iso() -> str:
    return dt.datetime.utcnow().isoformat()

def parse_iso_dt(value: str) -> Optional[str]:
    """Parses flexible ISO8601 dates and returns normalized ISO string."""
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Save in UTC if timestamp comes with tzinfo
        if parsed.tzinfo:
            parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return parsed.isoformat()
    except Exception:
        return None

def serialize_event(doc: dict) -> dict:
    data = dict(doc)
    if "_id" in data:
        data["_id"] = str(data["_id"])
    return data

def extract_score(ev: dict) -> Optional[float]:
    for key in ("score", "value", "valor", "promedio"):
        val = ev.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    return None

async def load_events(hours: int) -> List[dict]:
    cutoff = dt.datetime.utcnow() - dt.timedelta(hours=max(1, hours))
    try:
        coll = get_event_collection()
        cursor = coll.find({"timestamp": {"$gte": cutoff.isoformat()}})
        return [serialize_event(doc) async for doc in cursor]
    except Exception as e:
        print(f"⚠ Error loading events: {e}")
        return []

async def summarize_collection(target_coll, mode: str, limit_buckets: int = 200) -> List[dict]:
    try:
        # Motor cursor needs async iteration or to_list
        cursor = target_coll.find({}, sort=[("timestamp", -1)], projection={"_id": 0}).limit(5000)
        raw = await cursor.to_list(length=5000)
    except Exception as e:
        print(f"⚠ Error reading events: {e}")
        return []

    buckets = {}
    for ev in raw:
        ts = ev.get("timestamp")
        if not ts:
            continue
        try:
            d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            continue

        if mode == "3h":
            d = d.replace(minute=0, second=0, microsecond=0)
            bucket_hour = (d.hour // 3) * 3
            start = d.replace(hour=bucket_hour)
            key = start.isoformat() + "Z"
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


async def query_collection(
    target_coll,
    start: Optional[str],
    end: Optional[str],
    source: Optional[str],
    text: Optional[str],
    limit: int,
):
    mongo_filter = {}

    ts_filter = {}
    if start:
        start_iso = parse_iso_dt(start)
        if not start_iso:
            return {"count": 0, "items": [], "error": "invalid start (ISO8601)"}
        ts_filter["$gte"] = start_iso
    if end:
        end_iso = parse_iso_dt(end)
        if not end_iso:
            return {"count": 0, "items": [], "error": "invalid end (ISO8601)"}
        ts_filter["$lte"] = end_iso
    if ts_filter:
        mongo_filter["timestamp"] = ts_filter

    if source:
        mongo_filter["source"] = {"$regex": source, "$options": "i"}

    if text:
        mongo_filter["$or"] = [
            {"text": {"$regex": text, "$options": "i"}},
            {"description": {"$regex": text, "$options": "i"}},
        ]

    try:
        cursor = target_coll.find(mongo_filter, sort=[("timestamp", -1)]).limit(limit)
        events = [serialize_event(e) async for e in cursor]
        return {"count": len(events), "items": events, "applied_filter": mongo_filter}
    except Exception as e:
        return {"count": 0, "items": [], "error": str(e), "applied_filter": mongo_filter}

# ===== Endpoints =====
@app.get("/health")
async def health():
    return {"ok": True, "ts": now_iso()}

@app.post("/event")
async def add_event(ev: Event):
    data = ev.model_dump() # Pydantic v2
    if not data.get("timestamp"):
        data["timestamp"] = now_iso()
    
    try:
        await get_event_collection().insert_one(data)
        return {"status": "stored"}
    except Exception as e:
        print(f"⚠ Error saving event: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/events")
async def list_events(
    start: Optional[str] = None,
    end: Optional[str] = None,
    source: Optional[str] = None,
    text: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    return await query_collection(get_event_collection(), start, end, source, text, limit)


@app.get("/events/summary/3h")
async def summary_3h(limit: int = Query(200, ge=1, le=1000)):
    items = await summarize_collection(get_event_collection(), mode="3h", limit_buckets=limit)
    return {"count": len(items), "items": items}


@app.get("/events/summary/day")
async def summary_day(limit: int = Query(200, ge=1, le=1000)):
    items = await summarize_collection(get_event_collection(), mode="day", limit_buckets=limit)
    return {"count": len(items), "items": items}


@app.get("/victoria/history")
async def victoria_history(
    start: Optional[str] = None,
    end: Optional[str] = None,
    source: Optional[str] = None,
    text: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    return await query_collection(get_victoria_collection(), start, end, source, text, limit)


@app.get("/victoria/history/summary/3h")
async def victoria_summary_3h(limit: int = Query(200, ge=1, le=1000)):
    items = await summarize_collection(get_victoria_collection(), mode="3h", limit_buckets=limit)
    return {"count": len(items), "items": items}


@app.get("/victoria/history/summary/day")
async def victoria_summary_day(limit: int = Query(200, ge=1, le=1000)):
    items = await summarize_collection(get_victoria_collection(), mode="day", limit_buckets=limit)
    return {"count": len(items), "items": items}

@app.get("/analyze")
async def analyze(hours: int = Query(1, ge=1, le=168)):
    events = await load_events(hours)
    if not events:
        return {
            "status": "no_events",
            "score": 0.0,
            "msg": "No recent events.",
            "events_count": 0,
            "window_hours": hours,
        }
    res = await openai_analyze_events(events)
    return {
        "status": "ok",
        "score": float(res.get("score", 0.0)),
        "msg": res.get("text", "No summary"),
        "events_count": len(events),
        "window_hours": hours,
    }
