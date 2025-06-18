# Pydantic models for Kafka message structures
from pydantic import BaseModel, field_validator, model_validator, Field
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

    @field_validator('version')
    @classmethod
    def version_must_be_valid(cls, v: str) -> str:
        if v != "1.0": # Example validation, can be expanded
            raise ValueError('Version must be 1.0 for this schema processing')
        return v

    @field_validator('traitement_type')
    @classmethod
    def traitement_type_must_be_valid(cls, v: str) -> str:
        if v.upper() not in ["KYC", "KYB"]:
            raise ValueError('traitement_type must be either KYC or KYB')
        return v.upper()

    @model_validator(mode='after')
    def check_dependencies_after_validation(self) -> 'KafkaMessage':
        # Company Profile Check (formerly company_profile_required_for_kyb)
        if self.traitement_type == "KYB" and self.company_profile is None:
            raise ValueError('company_profile is required when traitement_type is KYB')

        # Original logic for KYC and company_profile:
        # if self.traitement_type == "KYC" and self.company_profile is not None:
        #     pass # Allowing company_profile for KYC, consumer logic might ignore it.
        # This part of the original validator implies no action if KYC and company_profile is present.
        # If it should be an error, it would need to be:
        # if self.traitement_type == "KYC" and self.company_profile is not None:
        #     raise ValueError('company_profile should not be provided when traitement_type is KYC')


        # Beneficial Owners Check (formerly beneficial_owners_for_kyb)
        if self.traitement_type == "KYC":
            # If beneficial_owners is provided and not an empty list for KYC, it's an error.
            # self.beneficial_owners will be at least [] due to default_factory=list
            if self.beneficial_owners and any(self.beneficial_owners):
                 raise ValueError('beneficial_owners should be empty or not provided when traitement_type is KYC')

        # For KYB, beneficial_owners can be None or a list (empty or populated).
        # The default_factory=list ensures it's an empty list if not provided,
        # so no specific validation for KYB regarding presence is strictly needed here unless rules change.

        return self
