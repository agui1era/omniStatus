import asyncio
import datetime as dt
from typing import Any, Optional

from app.config import settings
from app.database import get_event_collection
from app.services.llm import openai_analyze_events
from app.services.notifications import send_telegram_message


def _serialize_event(doc: dict) -> dict:
    data = dict(doc)
    if "_id" in data:
        data["_id"] = str(data["_id"])
    timestamp = data.get("timestamp")
    if isinstance(timestamp, dt.datetime):
        data["timestamp"] = timestamp.astimezone(dt.timezone.utc).isoformat()
    return data


def _event_timestamp(value: Any) -> Optional[dt.datetime]:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        except Exception:
            return None
    return None


async def load_recent_events(hours: int, limit: int, source_regex: str | None = None) -> list[dict]:
    lookback_hours = max(1, hours)
    max_events = max(1, limit)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=lookback_hours)
    cutoff_iso = cutoff.isoformat()

    timestamp_filter = {
        "$or": [
            {"timestamp": {"$gte": cutoff}},
            {"timestamp": {"$gte": cutoff_iso}},
        ]
    }
    mongo_filter = timestamp_filter
    if source_regex:
        mongo_filter = {
            "$and": [
                timestamp_filter,
                {"source": {"$regex": source_regex, "$options": "i"}},
            ]
        }

    cursor = (
        get_event_collection()
        .find(mongo_filter, sort=[("timestamp", -1)])
        .limit(max_events)
    )
    events = [_serialize_event(doc) async for doc in cursor]
    return [
        event
        for event in events
        if (timestamp := _event_timestamp(event.get("timestamp"))) and timestamp >= cutoff
    ]


def format_complex_analysis_message(result: dict, events_count: int, hours: int) -> str:
    score = float(result.get("score", 0.0))
    summary = result.get("text") or "Sin actividad registrada."
    if score < 0.3:
        estado = "Todo tranquilo"
    elif score < 0.6:
        estado = "Actividad moderada"
    else:
        estado = "ALERTA"
    return f"🌿 {settings.APP_NAME} | {hours}h | {estado} ({score:.2f})\nEventos: {events_count}\n{summary}"


def total_observed_events(events: list[dict]) -> int:
    total = 0
    for event in events:
        try:
            total += int(event.get("event_count") or 1)
        except (TypeError, ValueError):
            total += 1
    return total


async def run_complex_analysis(hours: int | None = None) -> dict:
    lookback_hours = hours or settings.COMPLEX_ANALYSIS_LOOKBACK_HOURS
    events = await load_recent_events(
        lookback_hours,
        settings.COMPLEX_ANALYSIS_MAX_EVENTS,
        settings.COMPLEX_ANALYSIS_SOURCE_REGEX,
    )
    if not events:
        return {
            "status": "no_events",
            "score": 0.0,
            "msg": "No recent events.",
            "events_count": 0,
            "window_hours": lookback_hours,
            "source_filter": settings.COMPLEX_ANALYSIS_SOURCE_REGEX,
            "notification": {"sent": False, "reason": "no_events"},
        }

    prompt = (
        f"{settings.COMPLEX_ANALYSIS_PROMPT}\n"
        f"The 'text' field must not exceed {settings.COMPLEX_ANALYSIS_SUMMARY_MAX_CHARS} characters."
    )
    result = await openai_analyze_events(
        events,
        model=settings.COMPLEX_ANALYSIS_MODEL,
        prompt=prompt,
    )
    observed_events = total_observed_events(events)
    message = format_complex_analysis_message(result, observed_events, lookback_hours)
    notification = await send_telegram_message(message)

    return {
        "status": "ok",
        "score": float(result.get("score", 0.0)),
        "msg": result.get("text", "No summary"),
        "events_count": observed_events,
        "event_documents": len(events),
        "window_hours": lookback_hours,
        "source_filter": settings.COMPLEX_ANALYSIS_SOURCE_REGEX,
        "model": settings.COMPLEX_ANALYSIS_MODEL,
        "notification": notification,
    }


async def complex_analysis_cron() -> None:
    interval_seconds = max(1, settings.COMPLEX_ANALYSIS_CRON_HOURS) * 60 * 60
    await asyncio.sleep(interval_seconds)
    while True:
        try:
            result = await run_complex_analysis()
            print(
                "Complex analysis cron:",
                result.get("status"),
                f"events={result.get('events_count')}",
                f"sent={result.get('notification', {}).get('sent')}",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Complex analysis cron error: {exc}")
        await asyncio.sleep(interval_seconds)
