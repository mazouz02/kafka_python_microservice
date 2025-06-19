from typing import Optional

from pydantic import BaseModel


class StoredEventMetaData(BaseModel):
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
