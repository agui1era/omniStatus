import os
import time
import json
import logging
import random
import subprocess
import requests
import re
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from difflib import SequenceMatcher

load_dotenv()

# ===== Config =====
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")
PROMPT_ANALYSIS = os.getenv("PROMPT_ANALYSIS")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB_NAME", "omniguard")
MONGO_COLLECTION = os.getenv("MONGO_COLL_NAME", "eventos")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB]
col = db[MONGO_COLLECTION]

ALERT_SCORE_THRESHOLD = float(os.getenv("ALERT_SCORE_THRESHOLD", 0.5))
WINDOW_SECONDS = int(os.getenv("WINDOW_SECONDS", 300))
ANALYZE_INTERVAL = int(os.getenv("ANALYZE_INTERVAL", 300))

ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "0") == "1"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ENABLE_TTS = os.getenv("ENABLE_TTS", "0") == "1"
TTS_URL = os.getenv("TTS_URL", "https://api.openai.com/v1/audio/speech")
TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.getenv("TTS_VOICE", "verse")
TTS_OUTPUT = os.getenv("TTS_OUTPUT", "alerta.mp3")
TTS_MESSAGE = os.getenv("TTS_MESSAGE", "Se ha detectado una alerta de seguridad")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# =========================================================
# 🔁 RETRIES (FALTABA ESTE BLOQUE — AHORA SÍ!)
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

            logging.warning(
                f"[RETRY] Intento {attempt}/{max_attempts} (status={status}). Reintentando en {sleep_s:.2f}s…"
            )

            time.sleep(sleep_s)


# =========================================================
# 🔍 Normalización de textos
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
                g["timestamp_last"] = evt["timestamp"]
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

    for g in groups:
        g.pop("norm", None)
    return groups


# =========================================================
# 🔐 Validación config
# =========================================================
def validate_config():
    missing = []
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not PROMPT_ANALYSIS:
        missing.append("PROMPT_ANALYSIS")
    if ENABLE_TELEGRAM:
        if not TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not TELEGRAM_CHAT_ID:
            missing.append("TELEGRAM_CHAT_ID")
    if missing:
        raise SystemExit(f"Faltan variables de entorno requeridas: {', '.join(missing)}")


# =========================================================
# 🗂 Leer eventos Mongo
# =========================================================
def read_events(window_seconds=None):
    effective_window = WINDOW_SECONDS if window_seconds is None else window_seconds
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=effective_window)
    docs = col.find({"timestamp": {"$gte": cutoff.isoformat()}}).sort("timestamp", 1)

    events = []
    for doc in docs:
        ts = doc.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, datetime):
            ts = ts.astimezone(timezone.utc)
        else:
            continue

        doc["timestamp"] = ts.isoformat()
        doc.pop("_id", None)
        events.append(doc)

    return events


# =========================================================
# 🧠 LLM ANALYSIS
# =========================================================
def analyze(events):
    if not events:
        return {"score": 0.0, "text": "Sin eventos recientes."}

    payload = {
        "prompt": PROMPT_ANALYSIS,
        "events": events
    }

    logging.info("\n────────────────────────────────────────────────────────────\n"
                 "🔵 [INPUT → OMNISTATUS LLM PAYLOAD]\n"
                 "────────────────────────────────────────────────────────────\n"
                 f"{json.dumps(payload, indent=2, ensure_ascii=False)}\n"
                 "────────────────────────────────────────────────────────────\n")

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    req_body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": "Eres un sistema experto en monitoreo. Responde en JSON válido."},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"}
    }

    try:
        def _r():
            return requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=req_body, timeout=30)

        r = with_retries(_r)
        r.raise_for_status()

        content = r.json()["choices"][0]["message"]["content"].strip()

        logging.info("\n────────────────────────────────────────────────────────────\n"
                     "🟢 [OUTPUT ← OMNISTATUS LLM RESPONSE]\n"
                     "────────────────────────────────────────────────────────────\n"
                     f"{content}\n"
                     "────────────────────────────────────────────────────────────\n")

        return json.loads(content)

    except Exception as e:
        logging.error(f"Error analizando: {e}")
        return {"score": 0.0, "text": f"Error: {e}"}


# =========================================================
# 🔔 Telegram
# =========================================================
def send_telegram(msg):
    if not ENABLE_TELEGRAM:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
    try:
        def _r():
            return requests.post(url, data=data, timeout=10)
        r = with_retries(_r)
        if not r.ok:
            logging.warning(f"Telegram respondió {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logging.error(f"Error enviando Telegram: {e}")


# =========================================================
# 🔊 TTS
# =========================================================
def speak_text(text):
    if not ENABLE_TTS:
        return
    try:
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": TTS_MODEL, "voice": TTS_VOICE, "input": text}

        def _r():
            return requests.post(TTS_URL, headers=headers, json=payload, timeout=30)

        resp = with_retries(_r)
        resp.raise_for_status()
        with open(TTS_OUTPUT, "wb") as f:
            f.write(resp.content)

        subprocess.run(["afplay", TTS_OUTPUT], check=False)
    except Exception as e:
        logging.error(f"Error en TTS: {e}")


# =========================================================
# MAIN LOOP
# =========================================================
def main():
    validate_config()
    logging.info(f"Consumer online (umbral {ALERT_SCORE_THRESHOLD})")

    initial = group_similar_events(read_events(3600))
    res = analyze(initial)

    if res.get("score", 0) >= ALERT_SCORE_THRESHOLD:
        send_telegram(f"🚨 ALERTA INICIAL\n{res.get('text')}")
        speak_text(res.get("text"))

    while True:
        events = group_similar_events(read_events())
        result = analyze(events)

        score = result.get("score", 0.0)
        msg = result.get("text", "")

        logging.info(f"Score={score:.2f} | Msg={msg}")

        if score >= ALERT_SCORE_THRESHOLD:
            send_telegram(f"🚨 ALERTA\n{msg}")
            speak_text(msg)

        time.sleep(ANALYZE_INTERVAL)


if __name__ == "__main__":
    main()