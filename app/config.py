from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App
    APP_NAME: str = "OmniStatus"
    SERVER_PORT: int = 8001
    EXTERNAL_API_KEY: str = ""
    OMNISTATUS_API_KEY: str = ""

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4.1-mini"
    COMPLEX_ANALYSIS_MODEL: str = "gpt-4.1-mini"

    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "omnistatus"
    MONGO_COLL_NAME: str = "events"
    MONGO_COLL_VICTORIA: str = "victoria_history"
    MONGO_QUERY_MAX_TIME_MS: int = 3000

    # Analysis
    SYSTEM_PROMPT: str = (
        "You are a surveillance camera monitoring assistant. "
        "The events you receive are descriptions of what cameras detected during a time window. "
        "IMPORTANT: Your response must be based EXCLUSIVELY on the events provided. "
        "Do NOT infer, assume, or include anything that is not explicitly present in the event data. "
        "If the events do not contain enough information to answer the query, say so briefly in Spanish. "
        "You must respond EXCLUSIVELY with valid JSON containing keys: "
        "{\"score\": float between 0 and 1, \"text\": string}. "
        "score=0 means fully normal, score=1 means critical. "
        "The 'text' field must be in Spanish. "
        "Do not include anything outside the JSON object."
    )
    PROMPT_ANALYSIS: str = "Analiza las descripciones de imágenes del vivero y responde en JSON {\"score\":float,\"text\":string}. text max 200 chars."

    # Victoria (external system)
    VICTORIA_SYSTEM_PROMPT: str = (
        "You are a monitoring assistant for an external integrated system called Victoria. "
        "Victoria is an external data source that sends events, alerts, and status updates from its own platform. "
        "Given a list of Victoria events, write a concise summary in Spanish of what happened during the time window. "
        "Focus on: alert volume, error states, status changes, anomalies, or anything that deviates from normal operation. "
        "You must respond EXCLUSIVELY with valid JSON containing keys: "
        "{\"score\": float between 0 and 1, \"text\": string}. "
        "score=0 means fully normal, score=1 means critical (error, outage, or major anomaly). "
        "The 'text' field must not exceed 200 characters. "
        "Do not include anything outside the JSON object."
    )
    VICTORIA_ANALYSIS_PROMPT: str = "Summarize the Victoria external system events and return JSON {\"score\":float,\"text\":string}. text max 200 chars."

    # Alerts
    ALERT_SCORE_THRESHOLD: float = 0.5
    WINDOW_SECONDS: int = 300
    ANALYZE_INTERVAL: int = 300
    ENABLE_COMPLEX_ANALYSIS_CRON: int = 1
    COMPLEX_ANALYSIS_LOOKBACK_HOURS: int = 3
    COMPLEX_ANALYSIS_CRON_HOURS: int = 3
    COMPLEX_ANALYSIS_SUMMARY_MAX_CHARS: int = 200
    CUSTOM_ANALYSIS_SUMMARY_MAX_CHARS: int = 200
    COMPLEX_ANALYSIS_MAX_EVENTS: int = 500
    COMPLEX_ANALYSIS_SOURCE_REGEX: str = "^(CAM|sentinex)"
    COMPLEX_ANALYSIS_PROMPT: str = (
        "You are analyzing only SENTINEX surveillance camera events from a plant nursery (vivero). "
        "Ignore any non-SENTINEX context if it appears. "
        "Summarize what the SENTINEX cameras detected during the time window: people, vehicles, activity in crop/plant areas, access points, etc. "
        "You MUST always describe what actually happened — never say 'nothing happened' or 'no activity'. "
        "If activity was low, describe what little was detected: how many detections, where, at what times. "
        "Highlight any unusual detections, recurring patterns, or anything that could indicate a threat, intrusion, or damage. "
        "Return JSON with keys score (0=calm/routine, 1=critical/threat) and text. "
        "text must be a descriptive summary in Spanish."
    )

    # Telegram
    ENABLE_TELEGRAM: int = 0
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
