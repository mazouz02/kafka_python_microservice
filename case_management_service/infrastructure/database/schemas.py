# Pydantic models for database document structures
import datetime
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any # Added Dict, Any for StoredEvent parts
import os # For default ID factory in DB models
import uuid # For default ID factory for StoredEvent

# --- Schemas for Read Models and Raw Events ---
class PersonDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4().hex)) # Changed default factory slightly
    case_id: str
    firstname: str
    lastname: str
    birthdate: Optional[str] = None
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

class CaseManagementDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4().hex))
    client_id: str
    version: str
    type: str
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

class RawEventDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4().hex))
    event_type: str
    payload: dict
    received_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    processed_at: Optional[datetime.datetime] = None

# --- Schema for Stored Domain Events in Event Store ---
# This structure is based on the original BaseEvent from domain_events.py
class StoredEventMetaData(BaseModel): # Renamed to avoid clash if EventMetaData is also domain primitive
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None

class StoredEventDB(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    aggregate_id: str
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    version: int = 1
    payload: Dict[str, Any] # Stored as a dictionary
    metadata: StoredEventMetaData = Field(default_factory=StoredEventMetaData)
