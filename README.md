# OmniStatus 🛰️  
Cognitive event engine + risk analysis with LLMs

OmniStatus is a **unified monitoring brain**:  
it collects events from any source (cameras, sensors, DVRs, scripts, IoT devices, logs, custom apps), stores them in **MongoDB**, and periodically asks an **LLM** to generate a clean summary + a risk score.

If the score crosses the threshold → it triggers alerts (Telegram, TTS, or your custom actions).

It is designed to be:
- simple to integrate  
- model-agnostic  
- robust under high noise  
- compatible with DVR setups, Sentinex, GuardianBox, HelpNet and any future modules

---

## ⚙️ Features

- **REST API** for pushing events (`/event`)
- **Event storage** in MongoDB
- **Time-window analysis** (`/analyze?hours=N`)
- **LLM summarizer & risk scoring**
- **Retry logic** (429, 500, 502, 503, 504)
- **Event deduplication** via text similarity
- **Telegram alerts** (optional)
- **Text-to-speech alerts** (optional)
- **Standalone consumer loop**

---

## 🗂 Directory Overview
