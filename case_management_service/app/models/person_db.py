import datetime
import uuid
from typing import Optional

from pydantic import BaseModel, Field


class PersonDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4().hex))
    case_id: Optional[str] = None # A person might be linked to a case (KYC)
    company_id: Optional[str] = None # Or linked to a company (KYB related party)
    # A person could be linked to both if a case involves a company they are part of.

    firstname: str
    lastname: str
    birthdate: Optional[str] = None
    role_in_company: Optional[str] = None # New field
    # email, phone etc. can be added later

    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
    updated_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))
