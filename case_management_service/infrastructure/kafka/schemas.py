# Pydantic models for Kafka message structures
from pydantic import BaseModel, validator, Field
from typing import List, Optional

# New reusable Address model
class AddressData(BaseModel):
    street: Optional[str] = None
    city: Optional[str] = None
    state_province: Optional[str] = None # State or Province
    postal_code: Optional[str] = None
    country: str # Typically required, e.g., ISO 3166-1 alpha-2

class PersonData(BaseModel):
    firstname: str
    lastname: str
    birthdate: Optional[str] = None
    role_in_company: Optional[str] = None # e.g., Director, Contact Person

class CompanyProfileData(BaseModel):
    registered_name: str
    trading_name: Optional[str] = None
    registration_number: str
    registration_date: Optional[str] = None # Consider date type if strict validation needed
    country_of_incorporation: str # ISO 3166-1 alpha-2
    registered_address: AddressData
    business_type: Optional[str] = None # e.g., Limited Company, Partnership
    industry_sector: Optional[str] = None # e.g., Finance, Technology

class BeneficialOwnerData(BaseModel):
    # Assuming person_details will be provided in a flat structure for BOs in Kafka message
    # or a nested PersonData. For simplicity with existing PersonData:
    person_details: PersonData
    # Alternatively, if BO details are flat:
    # firstname: str
    # lastname: str
    # birthdate: Optional[str] = None
    ownership_percentage: Optional[float] = Field(default=None, ge=0, le=100)
    types_of_control: Optional[List[str]] = Field(default_factory=list) # e.g., ["Direct Shareholding >25%", "Voting Rights"]
    is_ubo: bool = False # Ultimate Beneficial Owner flag

class KafkaMessage(BaseModel):
    client_id: str
    version: str
    type: str # Existing field, might be related to case_type or a general message type

    traitement_type: str # New: "KYC" or "KYB"

    persons: List[PersonData] # Now includes optional role_in_company

    company_profile: Optional[CompanyProfileData] = None
    beneficial_owners: Optional[List[BeneficialOwnerData]] = Field(default_factory=list) # Default to empty list

    @validator('version')
    def version_must_be_valid(cls, v):
        if v != "1.0": # Example validation, can be expanded
            raise ValueError('Version must be 1.0 for this schema processing')
        return v

    @validator('traitement_type')
    def traitement_type_must_be_valid(cls, v):
        if v.upper() not in ["KYC", "KYB"]:
            raise ValueError('traitement_type must be either KYC or KYB')
        return v.upper()

    @validator('company_profile', always=True)
    def company_profile_required_for_kyb(cls, v, values):
        # 'values' is a dict of already validated fields
        traitement = values.get('traitement_type')
        if traitement == "KYB" and v is None:
            raise ValueError('company_profile is required when traitement_type is KYB')
        if traitement == "KYC" and v is not None:
            # Decide: allow company profile for KYC or raise error? For now, let's allow but it might be ignored.
            # Or raise ValueError('company_profile should not be provided when traitement_type is KYC')
            pass # Allowing company_profile for KYC, consumer logic might ignore it.
        return v

    @validator('beneficial_owners', always=True)
    def beneficial_owners_for_kyb(cls, v, values): # v is the list of beneficial_owners
        traitement = values.get('traitement_type')
        if traitement == "KYC":
            # For KYC, beneficial_owners list should be empty or None.
            # The field defaults to an empty list, so `v` will be `[]` if not provided.
            # If it's explicitly provided as `None`, that's also fine.
            # If it's provided as a populated list, that's an error.
            if v and any(v): # Checks if list is not None and not empty
                 raise ValueError('beneficial_owners should not be provided or be empty when traitement_type is KYC')
        # For KYB, it can be None or a list (empty or populated).
        # The default_factory=list ensures 'v' is at least an empty list if not provided.
        return v
