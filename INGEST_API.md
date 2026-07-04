# OmniStatus Ingest API

Contract for external systems that need to inject events into OmniStatus.

## Base URL

Local default:

```text
http://localhost:8001
```

Production or LAN deployments should use the host/IP where OmniStatus is running.

## Authentication

Use the protected ingest endpoint for external systems:

```http
POST /ingest/event
X-API-Key: <OMNISTATUS_API_KEY>
```

Set the key on the OmniStatus server:

```env
OMNISTATUS_API_KEY=replace_with_a_long_random_secret
```

The legacy `POST /event` endpoint is still available for trusted internal producers such as the existing Sentinex integration. Do not expose legacy `/event` directly to the public internet.

If the API is exposed outside the trusted machine or LAN, also consider network-level protection:

- Put OmniStatus behind a reverse proxy that enforces an API key, VPN, or allowlist.
- Use ngrok access policy, firewall rules, or IP allowlists when practical.
- Keep the legacy `/event` path private.

## Insert Event

```http
POST /ingest/event
Content-Type: application/json
X-API-Key: <OMNISTATUS_API_KEY>
```

### Minimal Payload

```json
{
  "source": "system_name",
  "text": "Short event description"
}
```

### Full Payload

```json
{
  "source": "sentinex_cam_1",
  "text": "Person detected near the north gate",
  "score": 0.82,
  "timestamp": "2026-07-04T12:00:00Z",
  "summary": "Person near north gate",
  "event_count": 3,
  "avg_score": 0.76,
  "first_seen": "2026-07-04T11:58:00Z",
  "last_seen": "2026-07-04T12:00:00Z",
  "dedup_key": "person_north_gate",
  "samples": [
    "Person detected near the north gate",
    "Human movement near the north gate"
  ],
  "metadata": {
    "camera": "north_gate",
    "system": "sentinex",
    "site": "main"
  }
}
```

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | string | yes | System, sensor, camera, or module that produced the event. |
| `text` | string | yes | Main event description used by analysis. |
| `score` | number | no | Risk or importance score, normally `0.0` to `1.0`. |
| `timestamp` | string | no | ISO8601 timestamp. If omitted, OmniStatus stores the current server time. |
| `summary` | string | no | Short summary for grouped or enriched events. |
| `event_count` | integer | no | Number of real observations represented by this payload. Useful for batching. |
| `avg_score` | number | no | Average score across grouped observations. |
| `first_seen` | string | no | ISO8601 timestamp for first observation in a grouped event. |
| `last_seen` | string | no | ISO8601 timestamp for last observation in a grouped event. |
| `dedup_key` | string | no | Stable key for repeated or grouped events. |
| `samples` | array of strings | no | Example event texts included in a grouped payload. |
| `metadata` | object | no | Extra structured data. Keep it JSON-serializable. |

Unknown fields are ignored by the current Pydantic model unless they are added to `metadata`.

## Response

Success:

```json
{
  "status": "stored"
}
```

Application-level storage error:

```json
{
  "status": "error",
  "message": "..."
}
```

Validation errors are returned by FastAPI as HTTP `422`, usually when `source` or `text` is missing or the JSON body has the wrong type.

## curl Examples

Minimal event:

```bash
curl -X POST http://localhost:8001/ingest/event \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $OMNISTATUS_API_KEY" \
  -d '{"source":"pax_radar","text":"3 devices detected near entrance"}'
```

Event with score and metadata:

```bash
curl -X POST http://localhost:8001/ingest/event \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $OMNISTATUS_API_KEY" \
  -d '{
    "source": "pax_radar",
    "text": "High proximity device detected near entrance",
    "score": 0.68,
    "metadata": {
      "device_count": 3,
      "location": "entrance",
      "producer": "esp32-pax"
    }
  }'
```

Grouped event:

```bash
curl -X POST http://localhost:8001/ingest/event \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $OMNISTATUS_API_KEY" \
  -d '{
    "source": "sentinex_cam_1",
    "text": "Person detected near north gate (repeated 4 times)",
    "score": 0.91,
    "avg_score": 0.84,
    "event_count": 4,
    "first_seen": "2026-07-04T11:55:00Z",
    "last_seen": "2026-07-04T12:01:00Z",
    "dedup_key": "person_north_gate",
    "samples": [
      "Person detected near north gate",
      "Human figure near north gate"
    ]
  }'
```

## Query Inserted Events

Protected raw event read for external systems:

```http
GET /events/raw
X-API-Key: <OMNISTATUS_API_KEY>
```

Query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `start` | ISO8601 string | Include events with `timestamp >= start`. |
| `end` | ISO8601 string | Include events with `timestamp <= end`. |
| `source` | string | Case-insensitive source filter. |
| `text` | string | Case-insensitive text/description filter. |
| `limit` | integer | Max rows returned, `1` to `1000`. Default `200`. |

```http
GET /events/raw?limit=20
GET /events/raw?source=pax_radar&limit=20
GET /events/raw?start=2026-07-04T00:00:00Z&end=2026-07-04T23:59:59Z
```

Example:

```bash
curl "http://localhost:8001/events/raw?source=pax_radar&start=2026-07-04T00:00:00Z&limit=50" \
  -H "X-API-Key: $OMNISTATUS_API_KEY"
```

Response:

```json
{
  "count": 1,
  "items": [
    {
      "_id": "...",
      "source": "pax_radar",
      "text": "3 devices detected near entrance",
      "score": 0.68,
      "timestamp": "2026-07-04T12:00:00+00:00",
      "metadata": {
        "location": "entrance"
      }
    }
  ],
  "applied_filter": {
    "source": {
      "$regex": "pax_radar",
      "$options": "i"
    }
  }
}
```

## Analyze Inserted Events

Normal analysis:

```http
GET /analyze?hours=2
```

Custom prompt analysis:

```http
POST /analyze/custom
Content-Type: application/json
```

```json
{
  "hours": 2,
  "prompt": "Analyze recent PaxRadar and Sentinex events. Tell me how many events happened and whether there is risk."
}
```

## Periodic Cron Behavior

OmniStatus cron reads the main OmniStatus `events` collection.

For automatic Telegram summaries, the cron is filtered to SENTINEX/camera events by `COMPLEX_ANALYSIS_SOURCE_REGEX`. This keeps new injected sources such as drones or PaxRadar out of the Sentinex camera summary unless the regex is changed.

Current practical state:

- Sentinex injects into internal `POST /event`, so Sentinex events are included in the OmniStatus cron.
- The current default source filter is `^(CAM|sentinex)`, matching existing camera sources such as `CAM1` and explicit `sentinex...` source names.
- Victoria calls `POST /analyze/custom`; it queries analysis but does not inject events.
- PaxRadar currently writes to its own `pax_events` collection and has its own analysis cron, so PaxRadar events are not included in the OmniStatus cron unless PaxRadar also posts to `/event` or OmniStatus is extended to read `pax_events`.

Relevant env vars:

```env
ENABLE_COMPLEX_ANALYSIS_CRON=1
COMPLEX_ANALYSIS_LOOKBACK_HOURS=12
COMPLEX_ANALYSIS_CRON_HOURS=12
COMPLEX_ANALYSIS_MAX_EVENTS=500
COMPLEX_ANALYSIS_SOURCE_REGEX=^(CAM|sentinex)
ENABLE_TELEGRAM=1
```
