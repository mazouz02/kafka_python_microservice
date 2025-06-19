import datetime
from typing import Optional

from pydantic import BaseModel, Field

from case_management_service.infrastructure.kafka.schemas import AddressData


class CompanyProfileDB(BaseModel): # Read Model for Companies
    id: str # This is the company_id (aggregate_id of CompanyProfileCreatedEvent)
    # client_id: Optional[str] = None # If company is directly associated with a client_id from Kafka message

    registered_name: str
    trading_name: Optional[str] = None
    registration_number: str
    registration_date: Optional[str] = None
    country_of_incorporation: str
    registered_address: AddressData # Embed AddressData
    business_type: Optional[str] = None
    industry_sector: Optional[str] = None

    # active_case_id: Optional[str] = None # Link back to an active case if needed

    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
