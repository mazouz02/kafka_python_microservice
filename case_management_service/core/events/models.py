# Pydantic models for Domain Events
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import datetime
import uuid

class EventMetaData(BaseModel): # This is the domain's view of metadata
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None

class BaseEvent(BaseModel): # This is the base for domain event *objects*
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str # To be overridden by specific events
    aggregate_id: str
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    version: int = 1
    payload: BaseModel # Payload is a Pydantic model for type safety in domain
    metadata: EventMetaData = Field(default_factory=EventMetaData)
    payload_model_name: Optional[str] = None # Hint for deserialization if needed

# --- Specific Domain Event Payloads ---
class CaseCreatedEventPayload(BaseModel):
    client_id: str
    case_type: str
    case_version: str

class PersonAddedToCaseEventPayload(BaseModel):
    person_id: str # ID for the person entity within the case
    firstname: str
    lastname: str
    birthdate: Optional[str]

# --- Specific Domain Events ---
class CaseCreatedEvent(BaseEvent):
    event_type: str = "CaseCreated"
    payload: CaseCreatedEventPayload
    payload_model_name: str = "CaseCreatedEventPayload"

class PersonAddedToCaseEvent(BaseEvent):
    event_type: str = "PersonAddedToCase"
    payload: PersonAddedToCaseEventPayload
    payload_model_name: str = "PersonAddedToCaseEventPayload"
