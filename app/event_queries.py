import datetime as dt
from typing import Optional

from fastapi import HTTPException

from app.config import settings


def parse_iso_dt(value: str) -> Optional[str]:
    """Parse flexible ISO8601 dates and return a normalized ISO string."""
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
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


def build_event_filter(
    start: Optional[str],
    end: Optional[str],
    source: Optional[str],
    text: Optional[str],
    min_score: Optional[float],
) -> tuple[dict, Optional[str]]:
    mongo_filter: dict = {}

    ts_filter: dict = {}
    if start:
        start_iso = parse_iso_dt(start)
        if not start_iso:
            return {}, "invalid start/since (ISO8601)"
        ts_filter["$gte"] = start_iso
    if end:
        end_iso = parse_iso_dt(end)
        if not end_iso:
            return {}, "invalid end/until (ISO8601)"
        ts_filter["$lte"] = end_iso
    if ts_filter:
        mongo_filter["timestamp"] = ts_filter

    if source:
        # Exact match lets Mongo use the {source, timestamp} compound index.
        mongo_filter["source"] = source

    if text:
        mongo_filter["$or"] = [
            {"text": {"$regex": text, "$options": "i"}},
            {"description": {"$regex": text, "$options": "i"}},
        ]

    if min_score is not None:
        score_filter = [
            {"score": {"$gte": min_score}},
            {"avg_score": {"$gte": min_score}},
            {"value": {"$gte": min_score}},
            {"valor": {"$gte": min_score}},
            {"promedio": {"$gte": min_score}},
        ]
        if "$or" in mongo_filter:
            mongo_filter["$and"] = [
                {"$or": mongo_filter.pop("$or")},
                {"$or": score_filter},
            ]
        else:
            mongo_filter["$or"] = score_filter

    return mongo_filter, None


async def query_collection(
    target_coll,
    start: Optional[str],
    end: Optional[str],
    source: Optional[str],
    text: Optional[str],
    limit: int,
    min_score: Optional[float] = None,
):
    mongo_filter, error = build_event_filter(start, end, source, text, min_score)
    if error:
        return {"count": 0, "items": [], "error": error}

    try:
        cursor = (
            target_coll.find(mongo_filter, sort=[("timestamp", -1)])
            .max_time_ms(settings.MONGO_QUERY_MAX_TIME_MS)
            .limit(limit)
        )
        events = [serialize_event(event) async for event in cursor]
        return {"count": len(events), "items": events, "applied_filter": mongo_filter}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Mongo query failed",
                "message": str(exc),
                "applied_filter": mongo_filter,
            },
        ) from exc
