# OmniStatus 🛰️  
Cognitive event engine + risk analysis with LLMs

OmniStatus is a **unified monitoring brain**: it collects events from any source (cameras, sensors, DVRs, IoT devices, scripts, logs), stores them in MongoDB, and periodically asks an LLM to generate a clean summary + a risk score.  
If the score crosses the threshold → it triggers alerts (Telegram, TTS, etc).

Designed to be:
- simple to integrate  
- model-agnostic  
- robust under noise  
- compatible with GuardianBox, Sentinex, HelpNet & Victoria

---

## ⚙️ Features
- REST API (`/event`, `/events`, `/analyze`)
- MongoDB storage
- Time-window analysis
- LLM summarizer with strict JSON output
- Automatic retry logic (429, 5xx)
- Event deduplication via text similarity
- Telegram alerts (optional)
- TTS alerts (optional)
- Background consumer loop

---

## 🗂 Structure
```
server.py     -> FastAPI API gateway
consumer.py   -> Background analyzer + alerts
.env          -> Config
```

---

## 🔧 Environment Variables

### Required
```
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1
PROMPT_ANALYSIS="Analyze and return JSON {score,text}"

MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=omnistatus
MONGO_COLL_NAME=events
```

### Optional
```
ALERT_SCORE_THRESHOLD=0.5
WINDOW_SECONDS=300
ANALYZE_INTERVAL=300
```

### Telegram (optional)
```
ENABLE_TELEGRAM=1
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### TTS (optional)
```
ENABLE_TTS=1
TTS_URL=https://api.openai.com/v1/audio/speech
TTS_MODEL=gpt-4o-mini-tts
TTS_VOICE=verse
TTS_OUTPUT=alerta.mp3
TTS_MESSAGE="Security alert detected"
```

---

## 🚀 Running the API
```
python3 server.py
```

Endpoints:
```
GET  /health
POST /event
GET  /events
GET  /analyze?hours=N
```

Example event:
```json
{
  "source": "CAM1",
  "text": "Person detected near back gate",
  "score": 0.4
}
```

---

## 🧠 How LLM Analysis Works

The analyzer (`consumer.py`) does this loop:

1. Load recent events from MongoDB  
2. Normalize & group similar messages  
3. Send payload to LLM  
4. Receive `{score, text}`  
5. If `score >= threshold`:  
   - send Telegram alert  
   - (optional) generate TTS  
6. Sleep & repeat  

Everything is logged cleanly.

---

## 📡 Similar Event Grouping
Uses normalized text + 95% similarity ratio to merge spammy repeated events.  
This reduces noise and stabilizes LLM input.

---

## 🛡 Retry Strategy
Automatic retries for:
- timeouts  
- status 429  
- 500 / 502 / 503 / 504  

With exponential backoff + jitter.

---

## 🧪 Manual Test
```
curl -X POST http://localhost:8001/event \
  -H "Content-Type: application/json" \
  -d '{"source":"TEST","text":"Motion detected in warehouse"}'
```

Then:
```
curl http://localhost:8001/analyze?hours=1
```

---

## 🔥 Project Philosophy

OmniStatus is meant to be the **cognitive core** of a larger ecosystem:

- **GuardianBox** → camera/DVR acquisition  
- **Sentinex** → cognitive image analysis  
- **HelpNet** → resilient mesh communication  
- **Victoria** → action executor  
- **OmniStatus** → the brain that unifies everything  

---

## 📜 License
Free to use, free to fork.  
Built for **real-world resilience**, not corporate BS.