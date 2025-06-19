import datetime
import uuid
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field


class RawEventDB(BaseModel): # For storing raw incoming messages (e.g. from Kafka)
    id: str = Field(default_factory=lambda: str(uuid.uuid4().hex))
    event_type: str # e.g., "KAFKA_MESSAGE_RAW_STORED"
    payload: Dict[str, Any]   # The raw message payload as a dictionary. Changed from 'dict' to 'Dict[str, Any]'
    received_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    processed_at: Optional[datetime.datetime] = None # Timestamp when it was processed into domain events
