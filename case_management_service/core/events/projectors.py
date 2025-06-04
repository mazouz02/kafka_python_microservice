# Event Projectors and Dispatcher
import logging
import datetime

# Corrected imports for refactored structure
from . import models as domain_event_models
from case_management_service.infrastructure.database import schemas as db_schemas
from case_management_service.infrastructure.database import read_models as read_model_ops
# Import the new document requirements store
from case_management_service.infrastructure.database import document_requirements_store
from case_management_service.app.observability import tracer, domain_events_processed_counter, domain_events_by_type_counter

from opentelemetry.trace import SpanKind, get_current_span
from opentelemetry.trace.status import StatusCode, Status

logger = logging.getLogger(__name__)

# --- Specific Projector Functions ---

async def project_case_created(event: domain_event_models.CaseCreatedEvent):
    logger.info(f"Projecting CaseCreatedEvent: {event.event_id} for aggregate {event.aggregate_id}")

    case_data_for_read_model = db_schemas.CaseManagementDB(
        id=event.aggregate_id,
        client_id=event.payload.client_id,
        version=event.payload.case_version,
        type=event.payload.case_type,
        traitement_type=event.payload.traitement_type,
        company_id=event.payload.company_id,
        status="OPEN",
        created_at=event.timestamp,
        updated_at=event.timestamp
    )
    await read_model_ops.upsert_case_read_model(case_data_for_read_model)
    logger.info(f"Case read model CREATED/UPDATED for ID: {event.aggregate_id} via projector.")

async def project_company_profile_created(event: domain_event_models.CompanyProfileCreatedEvent):
    logger.info(f"Projecting CompanyProfileCreatedEvent: {event.event_id} for company {event.aggregate_id}")

    company_data_for_read_model = db_schemas.CompanyProfileDB(
        id=event.aggregate_id,
        registered_name=event.payload.registered_name,
        trading_name=event.payload.trading_name,
        registration_number=event.payload.registration_number,
        registration_date=event.payload.registration_date,
        country_of_incorporation=event.payload.country_of_incorporation,
        registered_address=event.payload.registered_address,
        business_type=event.payload.business_type,
        industry_sector=event.payload.industry_sector,
        created_at=event.timestamp,
        updated_at=event.timestamp
    )
    await read_model_ops.upsert_company_read_model(company_data_for_read_model)
    logger.info(f"CompanyProfile read model CREATED/UPDATED for ID: {event.aggregate_id} via projector.")

async def project_beneficial_owner_added(event: domain_event_models.BeneficialOwnerAddedEvent):
    logger.info(f"Projecting BeneficialOwnerAddedEvent: {event.event_id} for company {event.aggregate_id}")

    bo_data_for_read_model = db_schemas.BeneficialOwnerDB(
        id=event.payload.beneficial_owner_id,
        company_id=event.aggregate_id,
        firstname=event.payload.person_details.firstname,
        lastname=event.payload.person_details.lastname,
        birthdate=event.payload.person_details.birthdate,
        ownership_percentage=event.payload.ownership_percentage,
        types_of_control=event.payload.types_of_control,
        is_ubo=event.payload.is_ubo,
        created_at=event.timestamp,
        updated_at=event.timestamp
    )
    await read_model_ops.upsert_beneficial_owner_read_model(bo_data_for_read_model)
    logger.info(f"BeneficialOwner read model CREATED/UPDATED for ID: {event.payload.beneficial_owner_id} in company {event.aggregate_id}.")

async def project_person_linked_to_company(event: domain_event_models.PersonLinkedToCompanyEvent):
    logger.info(f"Projecting PersonLinkedToCompanyEvent: {event.event_id} for company {event.aggregate_id}")

    person_data_for_read_model = db_schemas.PersonDB(
        id=event.payload.person_id,
        company_id=event.aggregate_id,
        firstname=event.payload.firstname,
        lastname=event.payload.lastname,
        birthdate=event.payload.birthdate,
        role_in_company=event.payload.role_in_company,
        created_at=event.timestamp,
        updated_at=event.timestamp
    )
    await read_model_ops.upsert_person_read_model(person_data_for_read_model)
    logger.info(f"Person read model CREATED/UPDATED for ID: {event.payload.person_id} linked to company {event.aggregate_id} with role {event.payload.role_in_company}.")

async def project_person_added_to_case(event: domain_event_models.PersonAddedToCaseEvent):
    logger.info(f"Projecting PersonAddedToCaseEvent: {event.event_id} for case {event.aggregate_id}")

    person_data_for_read_model = db_schemas.PersonDB(
        id=event.payload.person_id,
        case_id=event.aggregate_id,
        firstname=event.payload.firstname,
        lastname=event.payload.lastname,
        birthdate=event.payload.birthdate,
        created_at=event.timestamp,
        updated_at=event.timestamp
    )
    await read_model_ops.upsert_person_read_model(person_data_for_read_model)
    logger.info(f"Person read model CREATED/UPDATED for ID: {event.payload.person_id} in case {event.aggregate_id}.")

# --- Document Requirement Event Projectors ---

async def project_document_requirement_determined(event: domain_event_models.DocumentRequirementDeterminedEvent):
    logger.info(f"Projecting DocumentRequirementDeterminedEvent for case {event.payload.case_id}, entity {event.payload.entity_id}, doc type {event.payload.document_type}")

    doc_req_db = db_schemas.RequiredDocumentDB(
        # ID is generated by default_factory in RequiredDocumentDB schema
        case_id=event.payload.case_id,
        entity_id=event.payload.entity_id,
        entity_type=event.payload.entity_type,
        document_type=event.payload.document_type,
        is_required=event.payload.is_required,
        status="AWAITING_UPLOAD",
        created_at=event.timestamp,
        updated_at=event.timestamp
    )

    await document_requirements_store.add_required_document(doc_req_db)
    logger.info(f"Document requirement {doc_req_db.id} (type: {doc_req_db.document_type}) created in read model.")

async def project_document_status_updated(event: domain_event_models.DocumentStatusUpdatedEvent):
    logger.info(f"Projecting DocumentStatusUpdatedEvent for doc_req_id {event.payload.document_requirement_id} to status {event.payload.new_status}")

    updated_doc = await document_requirements_store.update_required_document_status_and_meta(
        doc_requirement_id=event.payload.document_requirement_id,
        new_status=event.payload.new_status,
        metadata_update=event.payload.metadata_update,
        notes_to_add=event.payload.notes_added
    )

    if updated_doc:
        logger.info(f"Document requirement {updated_doc.id} status updated to {updated_doc.status} in read model.")
    else:
        logger.warning(f"Failed to update document requirement {event.payload.document_requirement_id} in read model (not found or no change).")

# --- Event Dispatcher (Update EVENT_PROJECTORS map) ---
EVENT_PROJECTORS = {
    "CaseCreated": [project_case_created],
    "PersonAddedToCase": [project_person_added_to_case],
    "CompanyProfileCreated": [project_company_profile_created],
    "BeneficialOwnerAdded": [project_beneficial_owner_added],
    "PersonLinkedToCompany": [project_person_linked_to_company],
    "DocumentRequirementDetermined": [project_document_requirement_determined], # New
    "DocumentStatusUpdated": [project_document_status_updated],       # New
}

# Wrapper for tracing and metrics (remains the same)
async def project_event_with_tracing_and_metrics(projector_func, event: domain_event_models.BaseEvent):
    event_type_str = event.event_type
    with tracer.start_as_current_span(f"projector.{event_type_str}.{projector_func.__name__}", kind=SpanKind.INTERNAL) as proj_span:
        proj_span.set_attribute("event.id", event.event_id)
        proj_span.set_attribute("event.type", event_type_str)
        proj_span.set_attribute("aggregate.id", event.aggregate_id)
        proj_span.set_attribute("projector.function", projector_func.__name__)
        logger.debug(f"Projector {projector_func.__name__} starting for event {event.event_id}")
        try:
            await projector_func(event)
            if hasattr(domain_events_processed_counter, 'add'):
                 domain_events_processed_counter.add(1, {"projector.name": projector_func.__name__})
            if hasattr(domain_events_by_type_counter, 'add'):
                 domain_events_by_type_counter.add(1, {"event.type": event_type_str, "projector.name": projector_func.__name__})
            proj_span.set_status(Status(StatusCode.OK))
            logger.debug(f"Projector {projector_func.__name__} completed for event {event.event_id}")
        except Exception as e:
            logger.error(f"Error in projector {projector_func.__name__} for event {event.event_id}: {e}", exc_info=True)
            proj_span.record_exception(e)
            proj_span.set_status(Status(StatusCode.ERROR, description=f"Projector Error: {type(e).__name__}"))
            raise

async def dispatch_event_to_projectors(event: domain_event_models.BaseEvent):
    current_span = get_current_span()
    event_type_str = event.event_type
    current_span.add_event("DispatchingToProjectors", {"event.type": event_type_str, "event.id": event.event_id})
    logger.debug(f"Dispatching event: {event_type_str} (ID: {event.event_id}) to projectors.")

    projector_functions_for_event_type = EVENT_PROJECTORS.get(event.event_type)

    if projector_functions_for_event_type:
        for projector_func in projector_functions_for_event_type:
            try:
                await project_event_with_tracing_and_metrics(projector_func, event)
            except Exception as e:
                logger.error(f"Dispatch loop encountered an error for projector {projector_func.__name__} processing event {event.event_id}: {e}", exc_info=True)
    else:
        logger.debug(f"No projectors registered for event type: {event_type_str}")
