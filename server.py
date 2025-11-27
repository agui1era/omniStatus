#!/usr/bin/env python3
# server.py — API de eventos + análisis (MongoDB)

import os
import json
import re
import requests
import datetime as dt
from typing import Optional, List
from fastapi import FastAPI, Query
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

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Eres un sistema experto en seguridad. "
    "Debes responder EXCLUSIVAMENTE un JSON válido con claves: "
    "{\"score\": float entre 0 y 1, \"text\": string}. "
    "No incluyas nada fuera del objeto JSON."
)

PROMPT_ANALYSIS = os.getenv(
    "PROMPT_ANALYSIS",
    "Analiza eventos y devuelve JSON {\"score\":float,\"text\":string}."
)

# ===== MongoDB Setup =====
client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
coll = db[MONGO_COLL_NAME]

# ===== App =====
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Nuevo Modelo =====
class Event(BaseModel):
    source: str
    text: str            # descripción del evento
    score: Optional[float] = None  # nivel de riesgo
    timestamp: Optional[str] = None  # ISO8601 string

# ===== Utils =====
def now_iso() -> str:
    return dt.datetime.utcnow().isoformat()

def save_event(ev: dict):
    try:
        coll.insert_one(ev)
    except PyMongoError as e:
        print(f"⚠ Error guardando evento: {e}")

def load_events(hours: int) -> List[dict]:
    cutoff = dt.datetime.utcnow() - dt.timedelta(hours=max(1, hours))
    try:
        return list(coll.find({"timestamp": {"$gte": cutoff.isoformat()}}))
    except PyMongoError as e:
        print(f"⚠ Error cargando eventos: {e}")
        return []

# ===== OpenAI Analyzer =====
def openai_analyze(events: List[dict]) -> dict:
    events_text = "\n".join(
        f"[{e.get('timestamp')}] {e.get('source')}: {e.get('text')} (score={e.get('score')})"
        for e in events
    ) or "(sin eventos)"

    system_msg = SYSTEM_PROMPT
    user_msg = f"{PROMPT_ANALYSIS}\n\nEventos:\n{events_text}"

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )

        if r.status_code != 200:
            return {"score": 0.0, "text": f"OpenAI {r.status_code}: {r.text[:200]}"}

        content = r.json()["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except Exception:
            m = re.search(r"\{.*\}", content, flags=re.DOTALL)
            parsed = json.loads(m.group(0)) if m else {"score": 0.0, "text": "Error parseo"}

        score = float(parsed.get("score", 0.0))
        text = parsed.get("text") or "Sin resumen"
        return {"score": max(0.0, min(score, 1.0)), "text": text}

    except Exception as e:
        return {"score": 0.0, "text": f"Error analizando: {e}"}

# ===== Endpoints =====
@app.get("/health")
def health():
    return {"ok": True, "ts": now_iso()}

@app.post("/event")
def add_event(ev: Event):
    data = ev.dict()
    if not data.get("timestamp"):
        data["timestamp"] = now_iso()
    save_event(data)
    return {"status": "stored"}

@app.get("/events")
def list_events():
    try:
        events = list(coll.find({}, sort=[("timestamp", -1)]))
        return {"count": len(events), "items": events}
    except PyMongoError as e:
        return {"count": 0, "items": [], "error": str(e)}

@app.get("/analyze")
def analyze(hours: int = Query(1, ge=1, le=168)):
    events = load_events(hours)
    if not events:
        return {
            "status": "no_events",
            "score": 0.0,
            "msg": "Sin eventos recientes.",
            "events_count": 0,
            "window_hours": hours,
        }
    res = openai_analyze(events)
    return {
        "status": "ok",
        "score": float(res.get("score", 0.0)),
        "msg": res.get("text", "Sin resumen"),
        "events_count": len(events),
        "window_hours": hours,
    }

# ===== Main =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8001, reload=False)