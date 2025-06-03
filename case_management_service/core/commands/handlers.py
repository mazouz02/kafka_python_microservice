# Command Handler Implementation
import logging
import uuid

# Corrected imports
from .models import CreateCaseCommand
from case_management_service.core.events import models as domain_event_models
from case_management_service.infrastructure.database.event_store import save_event
# core.events.projectors is the new location from step 9.6
from case_management_service.core.events.projectors import dispatch_event_to_projectors
from case_management_service.app.observability import tracer
from opentelemetry import trace

logger = logging.getLogger(__name__)

async def handle_create_case_command(command: CreateCaseCommand) -> str:
    current_span = trace.get_current_span()
    current_span.set_attribute("command.name", "CreateCaseCommand")
    current_span.set_attribute("command.id", command.command_id)
    current_span.add_event("CreateCaseCommandHandlerStarted")

    logger.info(f"Handling CreateCaseCommand: {command.command_id} for client {command.client_id}")

    case_id = str(uuid.uuid4())

    case_created_payload = domain_event_models.CaseCreatedEventPayload(
        client_id=command.client_id,
        case_type=command.case_type,
        case_version=command.case_version
    )
    case_created_event = domain_event_models.CaseCreatedEvent(
        aggregate_id=case_id,
        payload=case_created_payload,
        version=1
    )

    events_to_dispatch = []

    await save_event(case_created_event)
    events_to_dispatch.append(case_created_event)
    logger.info(f"CaseCreatedEvent stored for case_id: {case_id}, version: {case_created_event.version}")

    current_version = case_created_event.version
    for person_data in command.persons:
        current_version += 1
        person_id = str(uuid.uuid4())

        person_added_payload = domain_event_models.PersonAddedToCaseEventPayload(
            person_id=person_id,
            firstname=person_data.firstname,
            lastname=person_data.lastname,
            birthdate=person_data.birthdate
        )
        person_added_event = domain_event_models.PersonAddedToCaseEvent(
            aggregate_id=case_id,
            payload=person_added_payload,
            version=current_version
        )
        await save_event(person_added_event)
        events_to_dispatch.append(person_added_event)
        logger.info(f"PersonAddedToCaseEvent stored for person {person_data.firstname} in case_id: {case_id}, version: {current_version}")

    for event_to_dispatch in events_to_dispatch:
        await dispatch_event_to_projectors(event_to_dispatch)

    logger.info(f"Successfully processed CreateCaseCommand for case_id: {case_id}. Total events created and dispatched: {len(events_to_dispatch)}.")
    current_span.add_event("CreateCaseCommandHandlerFinished", {"case.id": case_id, "events.dispatched.count": len(events_to_dispatch)})

    return case_id

# COMMAND_HANDLERS example (commented out as per original)
# from .models import BaseCommand # If BaseCommand is needed for dispatcher type hint
# COMMAND_HANDLERS = {
# CreateCaseCommand: handle_create_case_command,
# }

# async def dispatch_command_to_handler(command: BaseCommand):
#     handler = COMMAND_HANDLERS.get(type(command))
#     if handler:
#         return await handler(command)
#     else:
#         logger.error(f"No handler registered for command type: {type(command).__name__}")
#         raise ValueError(f"No handler for {type(command).__name__}")
