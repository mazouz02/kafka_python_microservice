# Pydantic models for database document structures
import datetime
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid

# Re-using AddressData from Kafka schemas for DB storage as well for company address.
# If DB storage needs different fields/validation, define a separate AddressDB here.
from case_management_service.infrastructure.kafka.schemas import AddressData


# --- Schemas for Read Models and Raw Events ---
class PersonDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4().hex))
    case_id: Optional[str] = None # A person might be linked to a case (KYC)
    company_id: Optional[str] = None # Or linked to a company (KYB related party)
    # A person could be linked to both if a case involves a company they are part of.

    firstname: str
    lastname: str
    birthdate: Optional[str] = None
    role_in_company: Optional[str] = None # New field
    # email, phone etc. can be added later

    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))

class CaseManagementDB(BaseModel): # Read Model for Cases
    id: str = Field(default_factory=lambda: str(uuid.uuid4().hex)) # This is the case_id
    client_id: str
    version: str # Case version from original message, or internal case version
    type: str    # Case type from original message

    traitement_type: str # New: "KYC" or "KYB"
    company_id: Optional[str] = None # Link to CompanyProfileDB if KYB

    # Denormalized person info if primary subject is a person (for KYC)
    # primary_person_id: Optional[str] = None
    # primary_person_name: Optional[str] = None

    status: str = Field(default="OPEN") # e.g., OPEN, PENDING_REVIEW, CLOSED. Default to OPEN.
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))

class RawEventDB(BaseModel): # For storing raw incoming messages (e.g. from Kafka)
    id: str = Field(default_factory=lambda: str(uuid.uuid4().hex))
    event_type: str # e.g., "KAFKA_MESSAGE_RAW_STORED"
    payload: Dict[str, Any]   # The raw message payload as a dictionary. Changed from 'dict' to 'Dict[str, Any]'
    received_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    processed_at: Optional[datetime.datetime] = None # Timestamp when it was processed into domain events

# --- New Read Model Schemas for Company and BO ---
class CompanyProfileDB(BaseModel): # Read Model for Companies
    id: str # This is the company_id (aggregate_id of CompanyProfileCreatedEvent)
    # client_id: Optional[str] = None # If company is directly associated with a client_id from Kafka message

    registered_name: str
    trading_name: Optional[str] = None
    registration_number: str
    registration_date: Optional[str] = None
    country_of_incorporation: str
    registered_address: AddressData # Embed AddressData
    business_type: Optional[str] = None
    industry_sector: Optional[str] = None

    # active_case_id: Optional[str] = None # Link back to an active case if needed

    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))

class BeneficialOwnerDB(BaseModel): # Read Model for Beneficial Owners
    id: str # This is the beneficial_owner_id from BeneficialOwnerAddedEventPayload
    company_id: str # Link to the CompanyProfileDB

    # Denormalized person details for easier querying of BOs
    firstname: str
    lastname: str
    birthdate: Optional[str] = None
    # person_id: Optional[str] = None # If PersonData in BO event has its own unique ID from a Persons collection

    ownership_percentage: Optional[float] = None
    types_of_control: Optional[List[str]] = Field(default_factory=list)
    is_ubo: bool = False

    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))


# --- Schema for Stored Domain Events in Event Store ---
class StoredEventMetaData(BaseModel):
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None

class StoredEventDB(BaseModel): # For storing domain events in MongoDB
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    aggregate_id: str
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    version: int = 1
    payload: Dict[str, Any] # Stored as a dictionary, matches domain event's Pydantic payload model_dump()
    metadata: StoredEventMetaData = Field(default_factory=StoredEventMetaData)

# --- Schema for Required Documents ---
class RequiredDocumentDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4().hex))
    case_id: str # Link to the main case
    entity_id: str # ID of the entity this document is for (e.g., person_id, company_id)
    entity_type: str # e.g., "PERSON", "COMPANY"

    document_type: str # e.g., "PASSPORT", "PROOF_OF_ADDRESS", "COMPANY_REGISTRATION_CERTIFICATE"
    status: str = Field(default="AWAITING_UPLOAD") # Enum-like: AWAITING_UPLOAD, UPLOADED, VERIFIED_SYSTEM, VERIFIED_MANUAL, REJECTED, NOT_APPLICABLE
    is_required: bool = True

    metadata: Optional[Dict[str, Any]] = None # For storing e.g., rejection reasons, link to actual document, notes
    notes: Optional[List[str]] = Field(default_factory=list) # For audit trail or comments

    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
