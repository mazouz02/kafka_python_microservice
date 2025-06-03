from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from .kafka_models import PersonData # Re-use for person data in command

class BaseCommand(BaseModel):
    command_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # correlation_id, causation_id can also be added here if needed

class CreateCaseCommand(BaseCommand):
    client_id: str
    case_type: str
    case_version: str
    persons: List[PersonData] # Include person data directly in the command
    # aggregate_id is not needed at command creation, will be generated for the new case

# Add other commands as needed, e.g., AddPersonToCaseCommand, UpdateCaseCommand
