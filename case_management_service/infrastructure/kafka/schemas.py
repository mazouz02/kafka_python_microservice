# Pydantic models for Kafka message structures
from pydantic import BaseModel, validator
from typing import List, Optional

class PersonData(BaseModel):
    firstname: str
    lastname: str
    birthdate: Optional[str]

class KafkaMessage(BaseModel):
    client_id: str
    version: str
    type: str
    persons: List[PersonData]

    @validator('version')
    def version_must_be_valid(cls, v):
        if v != "1.0": # Example validation
            raise ValueError('Version must be 1.0')
        return v
