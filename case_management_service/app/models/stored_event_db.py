import datetime
import uuid
from typing import Dict, Any

from pydantic import BaseModel, Field

from .stored_event_meta_data import StoredEventMetaData


class StoredEventDB(BaseModel): # For storing domain events in MongoDB
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    aggregate_id: str
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    version: int = 1
    payload: Dict[str, Any] # Stored as a dictionary, matches domain event's Pydantic payload model_dump()
    metadata: StoredEventMetaData = Field(default_factory=StoredEventMetaData)
