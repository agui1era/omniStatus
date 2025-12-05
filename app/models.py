from typing import Optional
from pydantic import BaseModel

class Event(BaseModel):
    source: str
    text: str            # event description
    score: Optional[float] = None  # risk level
    timestamp: Optional[str] = None  # ISO8601 string
