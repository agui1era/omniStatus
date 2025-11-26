# OmniStatus – Overview Table

| Section | Description |
|--------|-------------|
| **What is OmniStatus?** | Central event processor + decision engine for AI, security, automation ecosystems. Receives events from cameras, LLMs, RAG systems, IoT, microcomputers, Alexa, and more. Applies rules and triggers actions. |
| **Core Features** | • Unified event receiver (JSON / API)  
• Rule engine with conditions  
• Multi-channel alerts (Telegram, Email, HTTP)  
• AI/LLM integration  
• Works on microcomputers (Raspberry Pi, Orange Pi)  
• Lightweight, fast, modular |
| **Architecture Flow** | **Sources → OmniStatus → Rules → Actions → Notifications**  
Sources include:  
• Sentinex (vision)  
• GuardianBox (DVR/IP analysis)  
• NovaRAG (RAG documents)  
• Alexa Skill (GhostSignal)  
• IoT devices  
• Microcomputers  
• Mesh nodes (HelpNet) |
| **Typical Sources (Examples)** | • Video systems: person, fire, car detections  
• RAG: document insights  
• LLM pipelines: deep reasoning events  
• Alexa: silent triggers  
• Sensors: motion, temperature, access events |
| **Typical Actions** | • Send Telegram alert  
• Send email  
• Call webhook / API  
• Trigger Victoria (automation module)  
• Log event  
• LLM summary request |
| **Event Example (JSON)** | ```json  
{  
  "source": "sentinex",  
  "camera_id": "CAM3",  
  "type": "person_detected",  
  "confidence": 0.92,  
  "timestamp": "2025-01-12T15:42:10Z",  
  "metadata": { "image_url": "http://local/frame.jpg" }  
}  
``` |
| **Rule Example** | ```json  
{  
  "if": { "source": "guardianbox", "type": "fire_alert" },  
  "then": { "notify": ["telegram"], "level": "critical" }  
}  
``` |
| **How to Run** | **Requirements:** Python 3.9+, FastAPI/Flask  
**Start:** `python omnistatus.py`  
**Test:**  
```bash  
curl -X POST http://localhost:8001/event \  
  -H "Content-Type: application/json" \  
  -d '{"source":"test","type":"ping"}'  
``` |
| **Security Notes** | • Can run local-only  
• Use API tokens or firewalls if exposed  
• Works behind Nginx, Traefik, Cloudflare Tunnel |
| **Integrations** | Sentinex • GuardianBox • NovaRAG • Victoria • HelpNet • GhostSignal (Alexa) • Custom APIs |
| **License** | MIT License |
| **Contributions** | Pull requests welcome. System is built to expand with new modules and AI features. |
