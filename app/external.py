"""
External API router — public-facing endpoints protected by EXTERNAL_API_KEY.
Mounted under /ext/ prefix. Does NOT affect any existing internal endpoints.

Usage:
  GET /ext/health          — simple ping
  GET /ext/events          — query events (read-only)
  GET /ext/events/summary  — aggregated event summaries
  GET /ext/status          — current system status snapshot

All requests require header:  X-API-Key: <EXTERNAL_API_KEY>
"""

import hmac
import time
import datetime as dt
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from app.config import settings
from app.database import get_event_collection
from app.event_queries import query_collection


# ===== Rate Limiter (stricter for external) =====
class ExternalRateLimiter:
    """Sliding-window rate limiter — 30 req/min for external traffic."""

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window_seconds
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]
        if len(self._hits[key]) >= self.max_requests:
            return False
        self._hits[key].append(now)
        return True


_rate_limiter = ExternalRateLimiter()


# ===== Auth dependency =====
async def require_external_key(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Validates EXTERNAL_API_KEY — separate from OMNISTATUS_API_KEY."""
    configured = settings.EXTERNAL_API_KEY

    if not configured:
        raise HTTPException(
            status_code=500,
            detail="External API key not configured. Set EXTERNAL_API_KEY in .env",
        )

    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not hmac.compare_digest(x_api_key, configured):
        raise HTTPException(status_code=403, detail="Invalid API key.")

    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.check(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Max 30 requests/min.",
            headers={"Retry-After": "60"},
        )

    return True


# ===== Router =====
router = APIRouter(
    prefix="/ext",
    tags=["External"],
    dependencies=[],  # auth applied per-endpoint
)


# ──────────────── helpers ────────────────
def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _serialize(doc: dict) -> dict:
    data = dict(doc)
    if "_id" in data:
        data["_id"] = str(data["_id"])
    return data


def _extract_score(ev: dict) -> Optional[float]:
    for key in ("score", "value", "valor", "promedio"):
        val = ev.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    return None


# ──────────────── endpoints ────────────────

@router.get("/health")
async def ext_health(_=Depends(require_external_key)):
    """Simple connectivity check."""
    return {"ok": True, "ts": _now_iso(), "source": "external"}


@router.get("/events")
async def ext_events(
    _=Depends(require_external_key),
    start: Optional[str] = None,
    end: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    source: Optional[str] = None,
    text: Optional[str] = None,
    min_score: Optional[float] = Query(None, ge=0.0),
    limit: int = Query(100, ge=1, le=500),
):
    """Read-only event query for external consumers."""
    return await query_collection(
        get_event_collection(),
        start or since,
        end or until,
        source,
        text,
        limit,
        min_score,
    )


@router.get("/events/summary")
async def ext_events_summary(
    _=Depends(require_external_key),
    mode: str = Query("day", pattern="^(3h|day)$"),
    limit: int = Query(100, ge=1, le=500),
):
    """Aggregated event summary (buckets of 3h or day)."""
    try:
        coll = get_event_collection()
        cursor = coll.find({}, sort=[("timestamp", -1)], projection={"_id": 0}).limit(3000)
        raw = await cursor.to_list(length=3000)
    except Exception as exc:
        return {"count": 0, "items": [], "error": str(exc)}

    buckets: dict = {}
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
            start_dt = d.replace(hour=bucket_hour)
            key = start_dt.isoformat() + "Z"
            bucket = buckets.setdefault(
                key, {"period": key, "tipo": "3h", "count": 0, "scores": []}
            )
        else:
            date_key = d.date().isoformat()
            bucket = buckets.setdefault(
                date_key, {"date": date_key, "tipo": "dia", "count": 0, "scores": []}
            )

        bucket["count"] += 1
        sc = _extract_score(ev)
        if sc is not None:
            bucket["scores"].append(sc)

    items = []
    for _, data in buckets.items():
        avg = sum(data["scores"]) / len(data["scores"]) if data["scores"] else None
        entry = {
            "count": data["count"],
            "avg_score": round(avg, 3) if avg is not None else None,
            "tipo": data["tipo"],
        }
        if mode == "3h":
            entry["period"] = data["period"]
        else:
            entry["date"] = data["date"]
        items.append(entry)

    sort_key = "period" if mode == "3h" else "date"
    items.sort(key=lambda x: x.get(sort_key, ""), reverse=True)
    return {"count": len(items[:limit]), "items": items[:limit]}


@router.get("/status")
async def ext_status(
    _=Depends(require_external_key),
    hours: int = Query(1, ge=1, le=24),
):
    """Quick system status: event count and average score over the last N hours."""
    cutoff = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(hours=hours)
    try:
        coll = get_event_collection()
        cursor = coll.find({"timestamp": {"$gte": cutoff.isoformat()}})
        events = [_serialize(doc) async for doc in cursor]
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    scores = [s for ev in events if (s := _extract_score(ev)) is not None]
    avg = round(sum(scores) / len(scores), 3) if scores else None

    return {
        "ok": True,
        "ts": _now_iso(),
        "window_hours": hours,
        "event_count": len(events),
        "avg_score": avg,
    }
