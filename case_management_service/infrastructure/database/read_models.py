# Functions for Interacting with Read Model Collections
import logging
import datetime
from typing import List, Optional

# Corrected imports: Add CompanyProfileDB and BeneficialOwnerDB
from .connection import get_database
from .schemas import CaseManagementDB, PersonDB, CompanyProfileDB, BeneficialOwnerDB # Added new schemas

logger = logging.getLogger(__name__)

async def upsert_case_read_model(case_data: CaseManagementDB) -> CaseManagementDB:
    """Creates or updates a case document in the read model (cases collection)."""
    db = await get_database()

    case_dict = case_data.model_dump()
    case_dict["updated_at"] = datetime.datetime.utcnow()

    await db.cases.replace_one(
        {"id": case_data.id},
        case_dict,
        upsert=True
    )
    logger.info(f"Case read model upserted for ID: {case_data.id}")
    return case_data


async def upsert_person_read_model(person_data: PersonDB) -> PersonDB:
    """Creates or updates a person document in the read model (persons collection)."""
    db = await get_database()
    person_dict = person_data.model_dump()
    person_dict["updated_at"] = datetime.datetime.utcnow()

    await db.persons.replace_one(
        {"id": person_data.id},
        person_dict,
        upsert=True
    )
    logger.info(f"Person read model upserted for ID: {person_data.id}")
    return person_data

async def get_case_by_id_from_read_model(case_id: str) -> Optional[CaseManagementDB]:
    db = await get_database()
    case_doc = await db.cases.find_one({"id": case_id})
    return CaseManagementDB(**case_doc) if case_doc else None

async def list_cases_from_read_model(limit: int = 10, skip: int = 0) -> List[CaseManagementDB]:
    db = await get_database()
    cases_cursor = db.cases.find().limit(limit).skip(skip).sort("created_at", -1)
    cases_docs = await cases_cursor.to_list(length=limit)
    return [CaseManagementDB(**doc) for doc in cases_docs]

async def list_persons_for_case_from_read_model(case_id: str, limit: int = 10, skip: int = 0) -> List[PersonDB]:
    db = await get_database()
    persons_cursor = db.persons.find({"case_id": case_id}).limit(limit).skip(skip).sort("created_at", 1)
    persons_docs = await persons_cursor.to_list(length=limit)
    return [PersonDB(**doc) for doc in persons_docs]

async def upsert_company_read_model(company_data: CompanyProfileDB) -> CompanyProfileDB:
    """Creates or updates a company document in the read model (companies collection)."""
    db = await get_database()
    company_dict = company_data.model_dump()
    company_dict["updated_at"] = datetime.datetime.utcnow() # Ensure updated_at is fresh

    await db.companies.replace_one(
        {"id": company_data.id}, # Filter by company_id
        company_dict,
        upsert=True
    )
    logger.info(f"Company read model upserted for ID: {company_data.id}")
    return company_data

async def upsert_beneficial_owner_read_model(bo_data: BeneficialOwnerDB) -> BeneficialOwnerDB:
    """Creates or updates a beneficial owner document in the read model (beneficial_owners collection)."""
    db = await get_database()
    bo_dict = bo_data.model_dump()
    bo_dict["updated_at"] = datetime.datetime.utcnow()

    await db.beneficial_owners.replace_one(
        {"id": bo_data.id}, # Filter by bo_id
        bo_dict,
        upsert=True
    )
    logger.info(f"Beneficial Owner read model upserted for ID: {bo_data.id}")
    return bo_data
