# Pydantic models for Domain Events
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, ClassVar # Import ClassVar
import datetime
import uuid

# Re-importing PersonData from its new location for use in event payloads if needed
from case_management_service.infrastructure.kafka.schemas import PersonData, AddressData

class EventMetaData(BaseModel):
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None

class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    aggregate_id: str
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    version: int = 1
    payload: BaseModel
    metadata: EventMetaData = Field(default_factory=EventMetaData)
    # payload_model_name should be a ClassVar on concrete event types, not an instance field on BaseEvent.

# --- Existing Event Payloads - Modifications ---
class CaseCreatedEventPayload(BaseModel):
    client_id: str
    case_type: str
    case_version: str
    traitement_type: str
    company_id: Optional[str] = None

# --- New Domain Event Payloads & Events ---

# Company Profile Events
class CompanyProfileEventPayloadStructure(BaseModel):
    registered_name: str
    trading_name: Optional[str] = None
    registration_number: str
    registration_date: Optional[str] = None
    country_of_incorporation: str
    registered_address: AddressData
    business_type: Optional[str] = None
    industry_sector: Optional[str] = None

class CompanyProfileCreatedEventPayload(CompanyProfileEventPayloadStructure):
    pass

class CompanyProfileCreatedEvent(BaseEvent):
    event_type: str = "CompanyProfileCreated"
    payload: CompanyProfileCreatedEventPayload
    payload_model_name: ClassVar[str] = "CompanyProfileCreatedEventPayload"

# Beneficial Owner Events
class BeneficialOwnerEventPayloadStructure(BaseModel):
    person_details: PersonData
    ownership_percentage: Optional[float] = None
    types_of_control: Optional[List[str]] = Field(default_factory=list)
    is_ubo: bool = False

class BeneficialOwnerAddedEventPayload(BeneficialOwnerEventPayloadStructure):
    beneficial_owner_id: str

class BeneficialOwnerAddedEvent(BaseEvent):
    event_type: str = "BeneficialOwnerAdded"
    payload: BeneficialOwnerAddedEventPayload
    payload_model_name: ClassVar[str] = "BeneficialOwnerAddedEventPayload"

# Person Event Modifications/Additions
class PersonAddedToCaseEventPayload(BaseModel):
    person_id: str
    firstname: str
    lastname: str
    birthdate: Optional[str]

class PersonLinkedToCompanyEventPayload(BaseModel):
    person_id: str
    firstname: str
    lastname: str
    birthdate: Optional[str]
    role_in_company: str

class PersonLinkedToCompanyEvent(BaseEvent):
    event_type: str = "PersonLinkedToCompany"
    payload: PersonLinkedToCompanyEventPayload
    payload_model_name: ClassVar[str] = "PersonLinkedToCompanyEventPayload"

# --- Existing Events - Ensure they use the updated BaseEvent and payloads ---
class CaseCreatedEvent(BaseEvent):
    event_type: str = "CaseCreated"
    payload: CaseCreatedEventPayload
    payload_model_name: ClassVar[str] = "CaseCreatedEventPayload"

class PersonAddedToCaseEvent(BaseEvent):
    event_type: str = "PersonAddedToCase"
    payload: PersonAddedToCaseEventPayload
    payload_model_name: ClassVar[str] = "PersonAddedToCaseEventPayload"

# --- Document Requirement Domain Event Payloads & Events ---

class DocumentRequirementDeterminedEventPayload(BaseModel):
    case_id: str
    entity_id: str
    entity_type: str
    document_type: str
    is_required: bool

class DocumentRequirementDeterminedEvent(BaseEvent):
    event_type: str = "DocumentRequirementDetermined"
    payload: DocumentRequirementDeterminedEventPayload
    payload_model_name: ClassVar[str] = "DocumentRequirementDeterminedEventPayload"

class DocumentStatusUpdatedEventPayload(BaseModel):
    document_requirement_id: str
    new_status: str
    old_status: str
    updated_by: Optional[str] = None
    metadata_update: Optional[Dict[str, Any]] = None
    notes_added: Optional[List[str]] = None

class DocumentStatusUpdatedEvent(BaseEvent):
    event_type: str = "DocumentStatusUpdated"
    payload: DocumentStatusUpdatedEventPayload
    payload_model_name: ClassVar[str] = "DocumentStatusUpdatedEventPayload"

# --- Notification Required Domain Event Payloads & Events ---

class NotificationRequiredEventPayload(BaseModel):
    notification_type: str # e.g., "EMAIL_WELCOME_KYC", "SMS_CASE_INITIATED"
    recipient_details: Dict[str, Any] # e.g., {"email": "foo@bar.com", "user_id": "user123"}

    template_id: Optional[str] = None # ID of the template for the communication service
    language_code: Optional[str] = None # e.g., "en", "fr"
    context_data: Dict[str, Any]   # Key-value pairs for template personalization

class NotificationRequiredEvent(BaseEvent):
    event_type: str = "NotificationRequired" # Standardized event type name
    payload: NotificationRequiredEventPayload
    payload_model_name: ClassVar[str] = "NotificationRequiredEventPayload"
    # aggregate_id will typically be the case_id this notification pertains to.
