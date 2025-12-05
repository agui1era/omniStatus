# OmniStatus 🛰️

**Cognitive Event Engine + LLM-Powered Risk Analysis**

OmniStatus is a **unified monitoring system** that collects events from multiple sources (cameras, sensors, DVRs, IoT devices, scripts, logs), stores them in MongoDB, and uses LLM analysis to generate intelligent summaries and risk scores. When risk thresholds are exceeded, it triggers automated alerts via Telegram, TTS, or other notification channels.

## ✨ Key Features

- 🌐 **REST API** - Full-featured API with `/event`, `/events`, `/analyze` endpoints
- 📊 **MongoDB Storage** - Persistent event storage with flexible querying
- 🧠 **LLM-Powered Analysis** - Intelligent event summarization and risk scoring
- 🔄 **Event Deduplication** - Smart grouping of similar events to reduce noise
- 📱 **Multi-Channel Alerts** - Telegram, TTS, and extensible notification system
- 🛡️ **Robust Error Handling** - Automatic retries with exponential backoff
- ⏱️ **Time-Window Analysis** - Configurable analysis periods
- 🎯 **Model Agnostic** - Works with any OpenAI-compatible LLM API

## 🏗️ Architecture

```
┌─────────────────┐
│  Event Sources  │ (Cameras, Sensors, DVRs, IoT)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  server_eventos │ FastAPI REST API
│     .py         │ - Receives events
└────────┬────────┘ - Stores in MongoDB
         │          - Query endpoints
         │
         ▼
┌─────────────────┐
│    MongoDB      │ Event Storage
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   consumer.py   │ Background Analyzer
└────────┬────────┘ - Groups similar events
         │          - LLM analysis
         │          - Triggers alerts
         ▼
┌─────────────────┐
│ Alert Channels  │ (Telegram, TTS, etc.)
└─────────────────┘
```

## 📁 Project Structure

```
omniStatus/
├── server_eventos.py   # FastAPI API server
├── consumer.py         # Background event analyzer
├── dashboard.html      # Web dashboard for viewing events
├── injector.html       # Event injection tool for testing
├── requirements.txt    # Python dependencies
├── .env               # Configuration (create from template below)
└── README.md          # This file
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root:

```bash
# Required
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4.1
PROMPT_ANALYSIS="Analyze the following security events and return a JSON with a risk score (0-1) and a text summary: {score: float, text: string}"
API_TOKEN=change_me_for_api_access  # Optional but recommended; sent as header X-API-Key

# MongoDB
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=omnistatus
MONGO_COLL_NAME=events
MONGO_COLL_VICTORIA=victoria_history

# Analysis Settings
ALERT_SCORE_THRESHOLD=0.5
WINDOW_SECONDS=300
ANALYZE_INTERVAL=300

# Optional: Telegram Notifications
ENABLE_TELEGRAM=0
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Optional: Text-to-Speech Alerts
ENABLE_TTS=0
TTS_URL=https://api.openai.com/v1/audio/speech
TTS_MODEL=gpt-4o-mini-tts
TTS_VOICE=verse
TTS_OUTPUT=alert.mp3
TTS_MESSAGE="Security alert detected"
```

### 3. Start MongoDB

```bash
# Using Docker
docker run -d -p 27017:27017 --name mongodb mongo:latest

# Or install MongoDB locally
# https://www.mongodb.com/docs/manual/installation/
```

### 4. Run the API Server

```bash
python server_eventos.py
```

The API will be available at `http://localhost:8001`

### 5. Run the Consumer (Background Analyzer)

In a separate terminal:

```bash
python consumer.py
```

### 6. Access the Dashboard

Open `dashboard.html` in your browser to view events and analytics.

Open `injector.html` to manually inject test events.

## 📡 API Endpoints

### Health Check
```bash
GET /health
```

### Submit Event
```bash
POST /event
Content-Type: application/json

{
  "source": "cam_entrance",
  "text": "Person detected near entrance",
  "score": 0.65,
  "timestamp": "2025-12-05T10:30:00Z"  # optional
}
```

### Query Events
```bash
GET /events?start=2025-12-01T00:00:00Z&end=2025-12-05T23:59:59Z&limit=200
```

Parameters:
- `start` (optional): ISO8601 start date
- `end` (optional): ISO8601 end date
- `source` (optional): Filter by source
- `text` (optional): Search in event text
- `limit` (optional): Max results (default 200, max 1000)

### Get 3-Hour Summary
```bash
GET /events/summary/3h?limit=200
```

### Get Daily Summary
```bash
GET /events/summary/day?limit=200
```

### Analyze Events
```bash
GET /analyze?hours=1
```

Returns LLM analysis of events from the last N hours.

### Victoria History
```bash
GET /victoria/history?limit=200
GET /victoria/history/summary/3h
GET /victoria/history/summary/day
```

## 🧠 How It Works

### Event Flow

1. **Event Ingestion**: Events are submitted via POST to `/event`
2. **Storage**: Events are stored in MongoDB with timestamps
3. **Background Analysis**: `consumer.py` runs continuously:
   - Reads recent events from the database
   - Groups similar events to reduce noise (95% similarity threshold)
   - Sends grouped events to LLM for analysis
   - Receives risk score (0-1) and text summary
4. **Alert Triggering**: If score ≥ threshold:
   - Sends Telegram notification
   - Generates TTS audio alert (optional)
   - Logs the alert

### Event Deduplication

The system uses text normalization and similarity matching to group duplicate or near-duplicate events:

```python
# Example: These would be grouped together
"Person detected near door"
"Person detected near the door"
"person DETECTED near   door!!"
```

This prevents alert fatigue from repeated similar events.

### Retry Strategy

Automatic retries with exponential backoff for:
- Network timeouts
- Rate limiting (429)
- Server errors (500, 502, 503, 504)

## 🧪 Testing

### Using the Event Injector

1. Open `injector.html` in your browser
2. Configure the API server URL
3. Send manual or random events
4. Review logs and verify events are received

### Using cURL

```bash
# Send a test event
curl -X POST http://localhost:8001/event \
  -H "Content-Type: application/json" \
  -d '{
    "source": "test_camera",
    "text": "Motion detected in warehouse zone",
    "score": 0.75
  }'

# Query events
curl http://localhost:8001/events?limit=10

# Trigger analysis
curl http://localhost:8001/analyze?hours=1
```

## 🔧 Configuration Details

### Alert Threshold
`ALERT_SCORE_THRESHOLD=0.5` - Risk score (0-1) that triggers alerts. Adjust based on your use case:
- `0.3` - More sensitive (more alerts)
- `0.7` - Less sensitive (fewer alerts)

### Analysis Window
`WINDOW_SECONDS=300` - Time window (in seconds) for event analysis. Default is 5 minutes.

### Analysis Interval
`ANALYZE_INTERVAL=300` - How often (in seconds) the consumer runs analysis. Default is 5 minutes.

### LLM Prompt
Customize `PROMPT_ANALYSIS` to adjust how events are analyzed. The prompt should instruct the LLM to return JSON with `score` and `text` fields.

## 🔌 Integration Examples

### Python Client

```python
import requests

def send_event(source, text, score=None):
    response = requests.post(
        "http://localhost:8001/event",
        json={
            "source": source,
            "text": text,
            "score": score
        }
    )
    return response.json()

# Example usage
send_event("camera_1", "Unauthorized access detected", 0.8)
```

### JavaScript/Node.js Client

```javascript
async function sendEvent(source, text, score) {
  const response = await fetch('http://localhost:8001/event', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, text, score })
  });
  return await response.json();
}

// Example usage
sendEvent('sensor_temp', 'Temperature exceeds threshold', 0.6);
```

## 🌐 Ecosystem

OmniStatus is designed to be the **cognitive core** of a larger security/monitoring ecosystem:

- **GuardianBox** → Camera/DVR acquisition and streaming
- **Sentinex** → AI-powered image/video analysis
- **HelpNet** → Resilient mesh communication
- **Victoria** → Automated action executor
- **OmniStatus** → Central event intelligence and coordination

## 🛠️ Development

### Running in Development Mode

```bash
# API with auto-reload
uvicorn server_eventos:app --reload --host 0.0.0.0 --port 8001

# Consumer with debug logging
python consumer.py
```

### MongoDB Connection String Examples

```bash
# Local
MONGO_URI=mongodb://localhost:27017

# With authentication
MONGO_URI=mongodb://username:password@localhost:27017

# MongoDB Atlas
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/

# Replica set
MONGO_URI=mongodb://host1:27017,host2:27017,host3:27017/?replicaSet=myReplSet
```

## 📊 Dashboard Features

The included web dashboard provides:
- Real-time event viewing
- Time range filtering
- Source and text search
- 3-hour and daily summaries
- Risk score visualization
- Auto-refresh capability

## 🔒 Security Considerations

- Keep your `.env` file secure and never commit it to version control
- Use strong MongoDB authentication in production
- Consider using HTTPS for API endpoints in production
- Implement rate limiting for public-facing endpoints
- Regularly rotate API keys and tokens
- Set `API_TOKEN` and send it via header `X-API-Key` to protect ingestion/query endpoints

## 🐛 Troubleshooting

### Events not being stored
- Check MongoDB is running: `mongosh` or `mongo`
- Verify connection string in `.env`
- Check API server logs for errors

### Analysis not running
- Ensure `consumer.py` is running
- Check OpenAI API key is valid
- Verify events exist in the time window
- Check consumer logs for errors

### Alerts not triggering
- Verify event scores exceed `ALERT_SCORE_THRESHOLD`
- Check Telegram configuration if using notifications
- Ensure consumer has proper API credentials

## 📜 License

Free to use, free to fork. Built for **real-world resilience**.

## 🤝 Contributing

Contributions are welcome! This project is designed to be:
- Simple to integrate
- Model-agnostic
- Robust under noise
- Production-ready

Feel free to submit issues, feature requests, or pull requests.

---

**Built with ❤️ for intelligent monitoring and security automation**
