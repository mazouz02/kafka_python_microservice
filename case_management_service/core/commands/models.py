# Pydantic models for Commands
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid

# Import data structures from Kafka schemas
from case_management_service.infrastructure.kafka.schemas import PersonData, CompanyProfileData, BeneficialOwnerData

class BaseCommand(BaseModel):
    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # correlation_id, causation_id can also be added here

class CreateCaseCommand(BaseCommand):
    # Fields from KafkaMessage
    client_id: str
    # 'type' from Kafka message can map to 'case_event_type' or similar if needed for CaseCreatedEvent
    # For now, let's assume 'type' from Kafka message is used as 'case_type' directly in the command.
    case_type: str # Corresponds to 'type' in KafkaMessage
    case_version: str # Corresponds to 'version' in KafkaMessage

    traitement_type: str # "KYC" or "KYB"

    persons: List[PersonData] # PersonData now includes role_in_company

    company_profile: Optional[CompanyProfileData] = None
    # Default to empty list for consistency, as KafkaMessage now does.
    beneficial_owners: Optional[List[BeneficialOwnerData]] = Field(default_factory=list)

    # Note: No specific Pydantic validators here for now, assuming KafkaMessage validation is sufficient
    # before this command is created. If command can be created from other sources, add validators.

# Future commands (placeholders for now):
# class AddBeneficialOwnerToCompanyCommand(BaseCommand):
#     company_id: str # Aggregate ID of the company
#     bo_details: BeneficialOwnerData

# class UpdateCompanyProfileCommand(BaseCommand):
#     company_id: str
#     updated_data: CompanyProfileData # Or a partial update model
