import os
import time
import json
import logging
import random
import requests
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import uvicorn

from app.config import settings

# ===== Config =====
OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_MODEL = settings.OPENAI_MODEL
PROMPT_ANALYSIS = settings.PROMPT_ANALYSIS

MONGO_URI = settings.MONGO_URI
MONGO_DB = settings.MONGO_DB_NAME
MONGO_COLLECTION = settings.MONGO_COLL_NAME

ALERT_SCORE_THRESHOLD = settings.ALERT_SCORE_THRESHOLD

ENABLE_TELEGRAM = settings.ENABLE_TELEGRAM == 1
TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID = settings.TELEGRAM_CHAT_ID

# ===== Logging =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# ===== Database =====
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB]
col = db[MONGO_COLLECTION]

# ===== FastAPI App =====
app = FastAPI(title="OmniStatus Consumer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Models =====
class DateRangeRequest(BaseModel):
    start: Optional[str] = None  # ISO format
    end: Optional[str] = None    # ISO format

class EventGroup(BaseModel):
    sample_text: str
    count: int
    timestamp_first: str
    timestamp_last: str
    original_events: List[Dict[str, Any]] = [] # Optional: send back raw events if needed

class AnalysisRequest(BaseModel):
    events: List[Dict[str, Any]] # Expects list of event objects (or groups)
    question: Optional[str] = None # Optional user question/context
    model: Optional[str] = None # Optional OpenAI model override

class AnalysisResponse(BaseModel):
    score: float
    text: str

class TelegramRequest(BaseModel):
    text: str


# =========================================================
# 🔁 RETRIES (WITH EXPONENTIAL BACKOFF)
# =========================================================
def with_retries(request_fn, max_attempts=3, base_delay=1.0, max_delay=30.0):
    attempt = 0
    while True:
        try:
            return request_fn()
        except Exception as e:
            attempt += 1
            status = getattr(e, "response", None)
            status = getattr(status, "status_code", None)

            retriable = (
                isinstance(e, requests.Timeout) or 
                status in {429, 500, 502, 503, 504}
            )

            if attempt >= max_attempts or not retriable:
                raise

            if status == 429:
                sleep_s = min(max_delay, base_delay * (2 ** (attempt - 1)) * 2)
            else:
                sleep_s = min(max_delay, base_delay * (2 ** (attempt - 1)))

            sleep_s *= (0.5 + random.random())
            logging.warning(f"[RETRY] {attempt}/{max_attempts}. Retrying in {sleep_s:.2f}s…")
            time.sleep(sleep_s)

# =========================================================
# 🔍 Text Normalization & Grouping
# =========================================================
def normalize_text(s):
    if not isinstance(s, str):
        return ""
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\wáéíóúñ ]", "", s)
    return s.strip()

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

def group_similar_events(events, threshold=0.95):
    if not events:
        return []

    groups = []
    for evt in events:
        text = evt.get("text", "") or evt.get("msg", "") or ""
        norm = normalize_text(text)

        matched = False
        for g in groups:
            if similarity(g["norm"], norm) >= threshold:
                g["count"] += 1
                # Update last timestamp if this event is newer
                if evt["timestamp"] > g["timestamp_last"]:
                    g["timestamp_last"] = evt["timestamp"]
                # Update first timestamp if this event is older (though usually sorted)
                if evt["timestamp"] < g["timestamp_first"]:
                    g["timestamp_first"] = evt["timestamp"]
                
                matched = True
                break

        if not matched:
            groups.append({
                "sample_text": text,
                "norm": norm,
                "count": 1,
                "timestamp_first": evt["timestamp"],
                "timestamp_last": evt["timestamp"],
            })

    # Clean up internal 'norm' key before returning
    for g in groups:
        g.pop("norm", None)
    return groups


# =========================================================
# 🗂 Read Mongo Events
# =========================================================
def fetch_events(start_str=None, end_str=None):
    # Default to last 1 hour if nothing provided
    if not start_str:
        start_dt = datetime.now(timezone.utc) - timedelta(hours=1)
    else:
        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        except:
             start_dt = datetime.now(timezone.utc) - timedelta(hours=1)

    # Ensure we use datetime objects for query if DB has datetime, or strings if DB has strings
    query_parts = []
    
    # 1. Datetime object query
    query_parts.append({"timestamp": {"$gte": start_dt}})
    
    # 2. String query (ISO)
    query_parts.append({"timestamp": {"$gte": start_dt.isoformat()}})
    
    query = {"$or": query_parts}
    
    # If end time provided
    if end_str:
        try:
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            # Update the $or parts to include the $lte constraint
            range_dt = {"timestamp": {"$gte": start_dt, "$lte": end_dt}}
            range_str = {"timestamp": {"$gte": start_dt.isoformat(), "$lte": end_dt.isoformat()}}
            
            query = {"$or": [range_dt, range_str]}
        except:
            pass

    # Sort descending (newest first) for better dashboard experience
    docs = col.find(query).sort("timestamp", -1)

    events = []
    for doc in docs:
        ts = doc.get("timestamp")
        # Ensure standard ISO format in memory
        if isinstance(ts, datetime):
             if ts.tzinfo is None:
                 ts = ts.replace(tzinfo=timezone.utc)
             ts = ts.isoformat()
        
        doc["timestamp"] = ts
        doc.pop("_id", None)
        events.append(doc)

    return events


# =========================================================
# 🧠 LLM ANALYSIS
# =========================================================
    chosen_model = model or OPENAI_MODEL
    
    # Optimize payload: 
    # 1. Limit number of events to avoid token limits (User requested limiter)
    # Dynamic limit: Mini models can handle more
    if "mini" in chosen_model.lower():
        MAX_EVENTS = 200
    else:
        MAX_EVENTS = 50

    if len(events_list) > MAX_EVENTS:
        logging.warning(f"Truncating event list from {len(events_list)} to {MAX_EVENTS} to avoid Rate Limits for model {chosen_model}.")
        events_list = events_list[:MAX_EVENTS]

    # 2. Truncate long strings in events to save tokens
    optimized_events = []
    for ev in events_list:
        clean_ev = {}
        for k, v in ev.items():
            if isinstance(v, str) and len(v) > 150: # Reduced from 300 to 150
                clean_ev[k] = v[:150] + "..."
            else:
                clean_ev[k] = v
        optimized_events.append(clean_ev)

    # Prepare payload. 
    payload = {
        "events": optimized_events
    }
    
    # Construct prompt
    prompt_text = PROMPT_ANALYSIS
    if question:
        prompt_text += f"\n\nUSER QUESTION/FOCUS: {question}\nPlease answer the user's question specifically based on the events provided."
        payload["user_context"] = question

    payload["prompt"] = prompt_text
    
    chosen_model = model or OPENAI_MODEL
    logging.info(f"Analyzing {len(events_list)} items... Question: {question} Model: {chosen_model}")

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    req_body = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": "You are an expert monitoring system. Respond in valid JSON."},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"}
    }

    try:
        def _r():
            return requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=req_body, timeout=60)

        r = with_retries(_r)
        
        if not r.ok:
            logging.error(f"OpenAI API Error: {r.status_code} {r.text}")
            return {"score": 0.0, "text": f"API Error {r.status_code}: {r.text}"}

        content = r.json()["choices"][0]["message"]["content"].strip()
        logging.info(f"DEBUG: Raw LLM Response: {content}")
        
        # Clean potential markdown code blocks ```json ... ```
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
            elif content.startswith("python"):
                pass 
            content = content.strip()

        return json.loads(content)

    except Exception as e:
        logging.error(f"Analysis error: {e}")
        return {"score": 0.0, "text": f"Error during analysis: {str(e)}"}


# =========================================================
# 🔔 Telegram
# =========================================================
def send_telegram_msg(msg):
    if not ENABLE_TELEGRAM:
        return False, "Telegram disabled in settings"
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        def _r():
            return requests.post(url, data=data, timeout=10)
        r = with_retries(_r)
        if r.ok:
            return True, "Sent"
        else:
            return False, f"Telegram API error: {r.text}"
    except Exception as e:
        return False, f"Exception: {str(e)}"


# =========================================================
# 🚀 API Endpoints
# =========================================================

@app.get("/unique_events")
def get_unique_events(start: Optional[str] = None, end: Optional[str] = None):
    """
    Fetch events in range, group them by similarity, return groups.
    """
    raw_events = fetch_events(start, end)
    grouped = group_similar_events(raw_events)
    return {"count_raw": len(raw_events), "count_unique": len(grouped), "groups": grouped}

@app.post("/analyze", response_model=AnalysisResponse)
def trigger_analysis(req: AnalysisRequest):
    """
    Analyze the provided list of events (or groups).
    """
    result = call_llm_analysis(req.events, question=req.question, model=req.model)
    
    # --- Robust Adaptive Parsing ---
    score = result.get("score")
    text = result.get("text") 
    
    # Helper to clean text
    def clean(t):
        if isinstance(t, (dict, list)):
            return json.dumps(t, ensure_ascii=False, indent=2)
        return str(t) if t else ""

    # 1. Try "analisis" wrapper
    if "analisis" in result:
        res = result["analisis"]
        if not text:
            text = res.get("conclusion") or res.get("resumen_eventos")
        
        # Infer score if missing
        if score is None:
            anoms = res.get("anomalías_detectadas") or res.get("riesgos_detectados")
            alert = result.get("alerta")
            if alert is True:
                score = 0.9
            elif anoms and isinstance(anoms, list) and len(anoms) > 0:
                score = 0.8
            else:
                score = 0.0

    # 2. Try root "conclusion" or "summary"
    if not text:
        conc = result.get("conclusion")
        if conc:
            if isinstance(conc, dict):
                text = conc.get("comentario") or conc.get("text") or conc.get("descripcion") or str(conc)
                # Check for risks in conclusion object
                if score is None:
                    if conc.get("riesgos_detectados") is True:
                        score = 0.8
                    elif conc.get("actividad_inusual") is True:
                        score = 0.7
            else:
                text = conc
    
    if not text:
        text = result.get("comentario") or result.get("summary")

    # 3. Fallback: Dump full JSON
    if not text:
        text = json.dumps(result, ensure_ascii=False, indent=2)
        
    # Final Score Default
    if score is None:
        # Check specific root keys for risks
        if result.get("alerta") is True:
            score = 0.9
        else:
            score = 0.0

    # Ensure text is string and score is float
    text = clean(text)
    
    return AnalysisResponse(
        score=float(score),
        text=text
    )

@app.post("/telegram")
def trigger_telegram(req: TelegramRequest):
    """
    Send text to Telegram manually.
    """
    success, reason = send_telegram_msg(req.text)
    if not success:
        raise HTTPException(status_code=500, detail=reason)
    return {"status": "ok", "detail": reason}

@app.post("/export_rag")
def export_rag(req: AnalysisRequest):
    """
    Generate a Markdown formatted string of events suitable for RAG.
    """
    events = req.events
    
    # Header
    md_output = f"# OmniStatus Event Log Export\n"
    md_output += f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
    md_output += f"Total Events: {len(events)}\n\n"
    
    # Body
    for ev in events:
        # Extract key info
        ts = ev.get("timestamp_first") or ev.get("timestamp") or "Unknown Time"
        cam = ev.get("camera_id") or "Unknown Cam"
        
        # Handle Grouped events
        if "sample_text" in ev:
            desc = ev["sample_text"]
            count = ev.get("count", 1)
            header = f"[{ts} | {cam}] (Count: {count})"
        else:
            # Handle Raw events
            desc = ev.get("description") or ev.get("text") or str(ev)
            header = f"[{ts} | {cam}]"
            
        md_output += f"### {header}\n{desc}\n\n"
        
    return {"markdown": md_output}

if __name__ == "__main__":
    uvicorn.run("consumer:app", host="0.0.0.0", port=8002, reload=False)
