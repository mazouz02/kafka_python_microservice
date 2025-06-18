# Pydantic models for Commands
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any # Added Dict, Any
import uuid

# Import data structures from Kafka schemas
from case_management_service.infrastructure.kafka.schemas import PersonData, CompanyProfileData, BeneficialOwnerData

class BaseCommand(BaseModel):
    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # correlation_id, causation_id can also be added here

class CreateCaseCommand(BaseCommand):
    # Fields from KafkaMessage
    client_id: str
    case_type: str
    case_version: str
    traitement_type: str
    persons: List[PersonData]
    company_profile: Optional[CompanyProfileData] = None
    beneficial_owners: Optional[List[BeneficialOwnerData]] = Field(default_factory=list)

# Future commands (placeholders for now):
# class AddBeneficialOwnerToCompanyCommand(BaseCommand):
#     company_id: str
#     bo_details: BeneficialOwnerData
# class UpdateCompanyProfileCommand(BaseCommand):
#     company_id: str
#     updated_data: CompanyProfileData

# --- Document Requirement Command Models ---

class ClientProfileDataForDocDetermination(BaseModel): # Simplified data for rules engine
    case_id: str
    traitement_type: str # KYC or KYB
    case_type: str # e.g., STANDARD_DUE_DILIGENCE, ENHANCED_DUE_DILIGENCE
    # For KYC:
    person_type: Optional[str] = None # e.g., INDIVIDUAL, DIRECTOR, UBO_PERSON
    person_jurisdiction: Optional[str] = None
    # For KYB:
    company_type: Optional[str] = None # e.g., PLC, LTD, PARTNERSHIP
    company_jurisdiction: Optional[str] = None
    industry_sector: Optional[str] = None


class DetermineInitialDocumentRequirementsCommand(BaseCommand):
    case_id: str # The case for which to determine document requirements
    entity_id: str # person_id or company_id
    entity_type: str # "PERSON" or "COMPANY"
    traitement_type: str
    case_type: str # Type of case (e.g. standard, enhanced)
    # Contextual data to help rules engine. Can be expanded.
    context_data: Optional[Dict[str, Any]] = Field(default_factory=dict)


class UpdateDocumentStatusCommand(BaseCommand):
    document_requirement_id: str # The ID of the RequiredDocumentDB entry
    new_status: str
    # Optional: Information about who/what triggered the update
    updated_by_actor_type: Optional[str] = None # e.g., "SYSTEM", "USER"
    updated_by_actor_id: Optional[str] = None   # e.g., service name or user ID
    # Optional: Metadata or notes to add/update
    metadata_changes: Optional[Dict[str, Any]] = None
    notes_to_add: Optional[List[str]] = Field(default_factory=list)
