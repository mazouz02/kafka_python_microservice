# Pydantic models for Commands
from pydantic import BaseModel, Field
from typing import List
import uuid
# Adjusted import path for PersonData, will be from infrastructure.kafka.schemas
# For now, define it here if it's simple, or fix imports later.
# To avoid immediate error, let's use a placeholder or assume it will be fixed.
# For robustness, temporarily redefine or use Any.
# from app.kafka_models import PersonData -> will become from infrastructure.kafka.schemas import PersonData
from case_management_service.infrastructure.kafka.schemas import PersonData # Assuming this path will be valid after all moves & import fixes

class BaseCommand(BaseModel):
    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # correlation_id, causation_id can also be added here

class CreateCaseCommand(BaseCommand):
    client_id: str
    case_type: str
    case_version: str
    persons: List[PersonData]
