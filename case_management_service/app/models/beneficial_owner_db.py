import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


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
