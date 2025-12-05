import json
import re
import httpx
from typing import List, Dict, Any
from app.config import settings

async def openai_analyze_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    events_text = "\n".join(
        f"[{e.get('timestamp')}] {e.get('source')}: {e.get('text')} (score={e.get('score')})"
        for e in events
    ) or "(no events)"

    system_msg = settings.SYSTEM_PROMPT
    user_msg = f"{settings.PROMPT_ANALYSIS}\n\nEvents:\n{events_text}"

    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload
            )

        if r.status_code != 200:
            return {"score": 0.0, "text": f"OpenAI {r.status_code}: {r.text[:200]}"}

        content = r.json()["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except Exception:
            m = re.search(r"\{.*\}", content, flags=re.DOTALL)
            parsed = json.loads(m.group(0)) if m else {"score": 0.0, "text": "Parse error"}

        score = float(parsed.get("score", 0.0))
        text = parsed.get("text") or "No summary"
        return {"score": max(0.0, min(score, 1.0)), "text": text}

    except Exception as e:
        return {"score": 0.0, "text": f"Analysis error: {e}"}
