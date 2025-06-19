import datetime
import uuid
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


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

    version: int = 1 # Added for optimistic concurrency control on the read model

    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
