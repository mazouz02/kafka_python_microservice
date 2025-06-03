from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import datetime
import uuid

class EventMetaData(BaseModel):
    correlation_id: Optional[str] = None # For tracing
    causation_id: Optional[str] = None   # For tracing related events

class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str # To be overridden by specific events
    aggregate_id: str # ID of the aggregate this event belongs to (e.g., case_id)
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    version: int = 1 # For optimistic concurrency, event sequence for an aggregate
    payload: Dict[str, Any]
    metadata: EventMetaData = Field(default_factory=EventMetaData)

# --- Specific Domain Events ---

# Case Events
class CaseCreatedEventPayload(BaseModel):
    client_id: str
    case_type: str # Renamed from 'type' to avoid keyword clash
    case_version: str # Renamed from 'version'

class CaseCreatedEvent(BaseEvent):
    event_type: str = "CaseCreated"
    payload: CaseCreatedEventPayload
    # Storing the payload model name for potential deserialization, not directly used by Pydantic
    payload_model_name: str = "CaseCreatedEventPayload"


class CasePersonData(BaseModel): # Re-using a structure similar to Kafka for persons within an event
    firstname: str
    lastname: str
    birthdate: Optional[str]

class PersonAddedToCaseEventPayload(BaseModel):
    person_id: str = Field(default_factory=lambda: str(uuid.uuid4())) # Generate person ID here
    firstname: str
    lastname: str
    birthdate: Optional[str]

class PersonAddedToCaseEvent(BaseEvent):
    event_type: str = "PersonAddedToCase" # aggregate_id will be the case_id
    payload: PersonAddedToCaseEventPayload
    # Storing the payload model name for potential deserialization
    payload_model_name: str = "PersonAddedToCaseEventPayload"

# Add other events as needed, e.g., CaseUpdatedEvent, CaseStatusChangedEvent etc.
