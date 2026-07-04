# OmniStatus 🛰️

**Cognitive Event Engine + LLM-Powered Risk Analysis**

OmniStatus is a unified monitoring system that collects events from multiple sources (cameras, sensors, DVRs, IoT devices, scripts, logs), stores them in MongoDB, and uses LLM analysis to generate intelligent summaries and risk scores. When risk thresholds are exceeded, it triggers automated alerts via Telegram.

## ✨ Key Features

- 🌐 **REST API** - Full-featured FastAPI with event ingestion, querying, and analysis endpoints
- 📊 **MongoDB Storage** - Persistent event storage with time-indexed querying
- 🧠 **LLM-Powered Analysis** - Intelligent event summarization and risk scoring (0–1 scale)
- 🔄 **Event Deduplication** - Smart grouping of repeated events to reduce noise and token usage
- 📱 **Telegram Alerts** - Automated notifications when risk thresholds are exceeded
- ⏱️ **Periodic Analysis Cron** - Configurable background analysis built into the API process
- 🔐 **External API** - Rate-limited, key-authenticated endpoints for external consumers
- 🎯 **Model Agnostic** - Works with any OpenAI-compatible model

## 🏗️ Architecture

```
┌─────────────────┐
│  Event Sources  │  (Cameras, Sensors, DVRs, IoT, Scripts)
└────────┬────────┘
         │ POST /event
         ▼
┌─────────────────┐
│   OmniStatus    │  FastAPI REST API
│   (server.py)   │  - Receives & stores events
└────────┬────────┘  - Queries & summaries
         │            - LLM analysis endpoints
         ▼
┌─────────────────┐
│    MongoDB      │  Event Storage
└────────┬────────┘  (events + victoria_history)
         │
         ▼
┌─────────────────┐
│  Analysis Cron  │  Built-in background task
└────────┬────────┘  - Reads N hours of events
         │            - Sends to LLM
         ▼
┌─────────────────┐
│    Telegram     │  Alert Channel
└─────────────────┘
```

## 📁 Project Structure

```
omniStatus/
├── server.py                      # Entry point
├── app/
│   ├── main.py                   # FastAPI app + all endpoints
│   ├── config.py                 # Settings (env-driven, pydantic-settings)
│   ├── models.py                 # Pydantic event model
│   ├── database.py               # MongoDB client
│   ├── external.py               # /ext/ router (external API)
│   └── services/
│       ├── llm.py               # OpenAI integration + event aggregation
│       ├── complex_analysis.py  # Periodic analysis cron
│       └── notifications.py     # Telegram notifications
├── requirements.txt
├── .env.example
└── README.md
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root (minimum required):

```bash
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1-mini
COMPLEX_ANALYSIS_MODEL=gpt-4.1-mini

MONGO_URI=mongodb://localhost:27017

# Optional: Telegram alerts
ENABLE_TELEGRAM=1
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Optional: External API protection
EXTERNAL_API_KEY=change_me
```

See `.env.example` for all available options.

### 3. Start MongoDB

```bash
# Using Docker
docker run -d -p 27017:27017 --name mongodb mongo:latest
```

### 4. Run

```bash
python server.py
```

API available at `http://localhost:8001`. Swagger docs at `http://localhost:8001/docs`.

## 📡 API Endpoints

### Events

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/event` | Internal/trusted event ingest |
| `POST` | `/ingest/event` | API-key protected event ingest (`X-API-Key`) |
| `GET` | `/events` | Query events (`start`/`since`, `end`/`until`, `source`, `text`, `min_score`, `limit`) |
| `GET` | `/events/raw` | API-key protected raw event query |
| `GET` | `/events/external` | API-key protected external collection query with the same response format as `/events/raw` |
| `GET` | `/events/summary/3h` | Events bucketed into 3-hour periods |
| `GET` | `/events/summary/day` | Events bucketed by day |

### Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/analyze?hours=N` | LLM analysis of last N hours |
| `GET` | `/analysis/complex?hours=N` | Full analysis + Telegram notification |
| `POST` | `/analyze/custom` | Custom prompt + model override |

### Victoria (External System)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/victoria/history` | Query Victoria events |
| `GET` | `/victoria/history/summary/3h` | 3-hour buckets |
| `GET` | `/victoria/history/summary/day` | Daily buckets |

### External API (`/ext/` — requires `X-API-Key` header, max 30 req/min)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/ext/health` | Connectivity check |
| `GET` | `/ext/events` | Read-only event query |
| `GET` | `/ext/events/summary` | Aggregated summary (`?mode=3h\|day`) |
| `GET` | `/ext/status?hours=N` | Event count + avg score snapshot |

## 🧠 How It Works

### Event Ingestion

Events are submitted via internal `POST /event` or protected `POST /ingest/event` with `source`, `text`, and optional `score` and `timestamp`. OmniStatus also accepts pre-aggregated payloads with `event_count`, `avg_score`, `first_seen`, `last_seen`, `summary`, `dedup_key`, and `samples` — useful for systems like Sentinex that batch detections before sending.

For the full ingestion contract for other systems, see [INGEST_API.md](INGEST_API.md).

### Event Deduplication

Before sending events to the LLM, repeated events are aggregated by source + text. Multiple occurrences become a single entry with a count, average score, and time range — reducing token usage and preventing alert fatigue from high-frequency cameras.

### Periodic Analysis Cron

The built-in cron reads the last `COMPLEX_ANALYSIS_LOOKBACK_HOURS` of events from the main `events` collection, filters them with `COMPLEX_ANALYSIS_SOURCE_REGEX`, sends them to the LLM, and optionally delivers a summary via Telegram. Runs every `COMPLEX_ANALYSIS_CRON_HOURS` hours inside the API process — no separate worker needed.

### Custom Analysis

`POST /analyze/custom` accepts a `prompt`, `hours`, and optional `model` override — allowing ad-hoc queries against recent event data without changing any configuration.

## ⚙️ Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required. OpenAI API key |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Model for `/analyze` and custom analysis |
| `COMPLEX_ANALYSIS_MODEL` | `gpt-4.1-mini` | Model for the periodic cron |
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGO_DB_NAME` | `omnistatus` | Database name |
| `ENABLE_COMPLEX_ANALYSIS_CRON` | `1` | Enable/disable background cron |
| `COMPLEX_ANALYSIS_LOOKBACK_HOURS` | `3` | Hours of events to read per cron run |
| `COMPLEX_ANALYSIS_CRON_HOURS` | `3` | How often the cron runs (hours) |
| `COMPLEX_ANALYSIS_MAX_EVENTS` | `500` | Max events per analysis run |
| `COMPLEX_ANALYSIS_SOURCE_REGEX` | `^(CAM\|sentinex)` | Source regex used by cron/manual complex analysis |
| `COMPLEX_ANALYSIS_SUMMARY_MAX_CHARS` | `200` | Max chars in cron summary |
| `CUSTOM_ANALYSIS_SUMMARY_MAX_CHARS` | `200` | Max chars in custom analysis summary |
| `ALERT_SCORE_THRESHOLD` | `0.5` | Score (0–1) that triggers alerts |
| `ENABLE_TELEGRAM` | `0` | Enable Telegram notifications |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | Telegram chat/channel ID |
| `EXTERNAL_API_KEY` | — | API key for `/ext/` endpoints |
| `SERVER_PORT` | `8001` | API server port |
| `OMNISTATUS_API_KEY` | — | API key required by protected `POST /ingest/event` |

### MongoDB Connection Examples

```bash
# Local
MONGO_URI=mongodb://localhost:27017

# With authentication
MONGO_URI=mongodb://username:password@localhost:27017

# MongoDB Atlas
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/
```

## 🧪 Testing

```bash
# Send a test event
curl -X POST http://localhost:8001/ingest/event \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $OMNISTATUS_API_KEY" \
  -d '{"source": "cam_1", "text": "Motion detected at entrance", "score": 0.75}'

# Query recent events
curl http://localhost:8001/events?limit=10

# Run analysis on last 2 hours
curl http://localhost:8001/analyze?hours=2

# Custom analysis
curl -X POST http://localhost:8001/analyze/custom \
  -H "Content-Type: application/json" \
  -d '{"hours": 6, "prompt": "Were there any unusual patterns?"}'
```

## 🌐 Ecosystem

OmniStatus is the **cognitive core** of a larger security/monitoring ecosystem:

- **GuardianBox** → Camera/DVR acquisition and streaming
- **Sentinex** → AI-powered image/video analysis
- **HelpNet** → Resilient mesh communication
- **Victoria** → Automated action executor
- **OmniStatus** → Central event intelligence and coordination

## 🔒 Security

- Never commit `.env` to version control — it contains your API keys
- Set `EXTERNAL_API_KEY` to protect external endpoints (rate-limited to 30 req/min per IP)
- Use MongoDB authentication in production
- Rotate API keys regularly

## 📜 License

Copyright 2026 Oscar Aguilera — Apache License 2.0. See [LICENSE](LICENSE).
