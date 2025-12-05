import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App
    APP_NAME: str = "OmniStatus"
    
    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4.1"
    
    # MongoDB
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "omnistatus"
    MONGO_COLL_NAME: str = "events"
    MONGO_COLL_VICTORIA: str = "victoria_history"

    # Analysis
    SYSTEM_PROMPT: str = (
        "You are an expert security system. "
        "You must respond EXCLUSIVELY with valid JSON containing keys: "
        "{\"score\": float between 0 and 1, \"text\": string}. "
        "Do not include anything outside the JSON object."
    )
    PROMPT_ANALYSIS: str = "Analyze events and return JSON {\"score\":float,\"text\":string}."
    
    # Alerts
    ALERT_SCORE_THRESHOLD: float = 0.5
    WINDOW_SECONDS: int = 300
    ANALYZE_INTERVAL: int = 300
    
    # Telegram
    ENABLE_TELEGRAM: int = 0
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    
    # TTS
    ENABLE_TTS: int = 0
    TTS_URL: str = "https://api.openai.com/v1/audio/speech"
    TTS_MODEL: str = "gpt-4o-mini-tts"
    TTS_VOICE: str = "verse"
    TTS_OUTPUT: str = "alerta.mp3"
    TTS_MESSAGE: str = "Security alert detected"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
