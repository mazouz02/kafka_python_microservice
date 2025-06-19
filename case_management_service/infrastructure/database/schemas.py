# Pydantic models for database document structures
import datetime
from pydantic import BaseModel, Field # BaseModel and Field might still be used by other files importing from here, or for future direct additions.
from typing import List, Optional, Dict, Any # Same logic, keep general useful typings.
import uuid # Keep for similar reasons.

# Re-using AddressData from Kafka schemas for DB storage as well for company address.
# If DB storage needs different fields/validation, define a separate AddressDB here.
from case_management_service.infrastructure.kafka.schemas import AddressData

# All specific model definitions (PersonDB, CaseManagementDB, RawEventDB,
# CompanyProfileDB, BeneficialOwnerDB, StoredEventMetaData, StoredEventDB,
# RequiredDocumentDB) have been moved to individual files under
# case_management_service/app/models/
#
# They can now be imported from case_management_service.app.models
# For example: from case_management_service.app.models import PersonDB

# This file is kept to maintain the AddressData import and potentially other
# shared database schema-related utilities or base classes in the future.
# If AddressData is the only thing remaining and it's only used by models
# now in app/models/, this import could eventually be moved there too,
# and this file potentially removed if no longer serving any purpose.
# For now, retaining it as per instructions.
