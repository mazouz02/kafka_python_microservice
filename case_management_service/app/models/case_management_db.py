import datetime
import uuid
from typing import Optional

from pydantic import BaseModel, Field


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
