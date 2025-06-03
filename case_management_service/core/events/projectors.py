# Event Projectors and Dispatcher
import logging
import datetime # For updated_at timestamp if not handled by upsert directly

# Corrected imports
from . import models as domain_event_models # Relative import for domain event models
from case_management_service.infrastructure.database import schemas as db_schemas
from case_management_service.infrastructure.database import read_models as read_model_ops
# get_database is not directly used here if read_model_ops encapsulate all DB interactions for projectors.
# from case_management_service.infrastructure.database.connection import get_database
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
        created_at=event.timestamp,
        updated_at=event.timestamp
    )

    await read_model_ops.upsert_case_read_model(case_data_for_read_model)
    logger.info(f"Case read model CREATED/UPDATED for ID: {event.aggregate_id} via projector.")


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
    logger.info(f"Person read model CREATED/UPDATED for ID: {event.payload.person_id} in case {event.aggregate_id} via projector.")


# --- Event Dispatcher ---
EVENT_PROJECTORS = {
    "CaseCreated": [project_case_created],
    "PersonAddedToCase": [project_person_added_to_case],
}

async def project_event_with_tracing_and_metrics(projector_func, event: domain_event_models.BaseEvent):
    event_type_str = event.event_type if isinstance(event.event_type, str) else type(event.event_type).__name__

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
    event_type_str = event.event_type if isinstance(event.event_type, str) else type(event.event_type).__name__
    current_span.add_event("DispatchingToProjectors", {"event.type": event_type_str, "event.id": event.event_id})

    logger.debug(f"Dispatching event: {event_type_str} (ID: {event.event_id}) to projectors.")

    projector_functions_for_event_type = EVENT_PROJECTORS.get(event_type_str)

    if projector_functions_for_event_type:
        for projector_func in projector_functions_for_event_type:
            try:
                await project_event_with_tracing_and_metrics(projector_func, event)
            except Exception as e:
                logger.error(f"Dispatch loop encountered an error for projector {projector_func.__name__} processing event {event.event_id}: {e}", exc_info=True)
    else:
        logger.debug(f"No projectors registered for event type: {event_type_str}")
