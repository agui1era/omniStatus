import asyncio
import contextlib
import datetime as dt
from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import db, get_event_collection, get_victoria_collection
from app.models import Event
from app.auth import require_api_key
from app.services.llm import openai_analyze_events
from app.services.complex_analysis import (
    complex_analysis_cron,
    load_recent_events,
    run_complex_analysis,
)
from app.external import router as ext_router


async def _startup_analysis() -> None:
    try:
        result = await run_complex_analysis()
        print(
            "Startup analysis:",
            result.get("status"),
            f"events={result.get('events_count')}",
            f"sent={result.get('notification', {}).get('sent')}",
        )
    except Exception as exc:
        print(f"Startup analysis error: {exc}")


# ===== Lifespan =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    await get_event_collection().create_index([("timestamp", -1)])
    await get_victoria_collection().create_index([("timestamp", -1)])
    task = None
    if settings.ENABLE_COMPLEX_ANALYSIS_CRON:
        asyncio.create_task(_startup_analysis())
        task = asyncio.create_task(complex_analysis_cron())
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    db.close()


# ===== App =====
app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.include_router(ext_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Utils =====
def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()

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
    try:
        return await load_recent_events(hours, settings.COMPLEX_ANALYSIS_MAX_EVENTS)
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

async def store_event(ev: Event):
    data = ev.model_dump() # Pydantic v2
    if not data.get("timestamp"):
        data["timestamp"] = now_iso()
    
    try:
        await get_event_collection().insert_one(data)
        return {"status": "stored"}
    except Exception as e:
        print(f"⚠ Error saving event: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/event")
async def add_event(ev: Event):
    return await store_event(ev)


@app.post("/ingest/event")
async def add_event_protected(ev: Event, _=Depends(require_api_key)):
    return await store_event(ev)


@app.get("/events")
async def list_events(
    start: Optional[str] = None,
    end: Optional[str] = None,
    source: Optional[str] = None,
    text: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    return await query_collection(get_event_collection(), start, end, source, text, limit)


@app.get("/events/raw")
async def list_events_raw(
    _=Depends(require_api_key),
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


@app.get("/analysis/complex")
async def complex_analysis(hours: Optional[int] = Query(None, ge=1, le=168)):
    return await run_complex_analysis(hours)


class AnalyzeRequest(BaseModel):
    hours: int = Field(..., ge=1, le=168)
    prompt: str = Field(..., min_length=1)
    model: Optional[str] = None


@app.post("/analyze/custom")
async def analyze_custom(body: AnalyzeRequest):
    events = await load_recent_events(body.hours, settings.COMPLEX_ANALYSIS_MAX_EVENTS)
    if not events:
        return {
            "status": "no_events",
            "score": 0.0,
            "msg": "No hay eventos en ese período.",
            "events_count": 0,
            "window_hours": body.hours,
        }

    full_prompt = (
        f"{body.prompt}\n"
        f"The 'text' field must not exceed {settings.CUSTOM_ANALYSIS_SUMMARY_MAX_CHARS} characters."
    )
    result = await openai_analyze_events(
        events,
        model=body.model or settings.OPENAI_MODEL,
        prompt=full_prompt,
    )
    return {
        "status": "ok",
        "score": float(result.get("score", 0.0)),
        "msg": result.get("text", "No summary"),
        "events_count": len(events),
        "window_hours": body.hours,
        "model": body.model or settings.OPENAI_MODEL,
    }
