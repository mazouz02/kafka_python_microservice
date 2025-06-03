import logging
import uuid
from . import commands
from . import domain_events
from .database import save_event, get_events_for_aggregate # For versioning/state reconstruction if needed by handler
from .kafka_models import PersonData as KafkaPersonData # To map from command to event

logger = logging.getLogger(__name__)

async def handle_create_case_command(command: commands.CreateCaseCommand):
    logger.info(f"Handling CreateCaseCommand: {command.command_id} for client {command.client_id}")

    # Generate a new ID for the case (this will be the aggregate_id)
    case_id = str(uuid.uuid4())

    # 1. Create and store the CaseCreatedEvent
    case_created_payload = domain_events.CaseCreatedEventPayload(
        client_id=command.client_id,
        case_type=command.case_type,
        case_version=command.case_version
    )
    case_created_event = domain_events.CaseCreatedEvent(
        aggregate_id=case_id,
        payload=case_created_payload,
        version=1 # First event for this aggregate
    )
    await save_event(case_created_event)
    logger.info(f"CaseCreatedEvent stored for case_id: {case_id}")

    # 2. Create and store PersonAddedToCaseEvent for each person in the command
    #    These events will share the same aggregate_id (case_id)
    #    Their versions will increment starting from the next version after CaseCreatedEvent.
    current_version = 1
    for person_data in command.persons:
        current_version += 1
        person_id = str(uuid.uuid4()) # Generate person ID within the handler / event

        person_added_payload = domain_events.PersonAddedToCaseEventPayload(
            person_id=person_id, # Use the newly generated person_id
            firstname=person_data.firstname,
            lastname=person_data.lastname,
            birthdate=person_data.birthdate
        )
        person_added_event = domain_events.PersonAddedToCaseEvent(
            aggregate_id=case_id, # Belongs to the same case
            payload=person_added_payload,
            version=current_version
        )
        await save_event(person_added_event)
        logger.info(f"PersonAddedToCaseEvent stored for person {person_data.firstname} in case_id: {case_id} with version {current_version}")

    logger.info(f"Successfully processed CreateCaseCommand for case_id: {case_id}, total events: {current_version}")
    return case_id # Return the ID of the newly created case aggregate

# Register handlers (simple dict for now, can be more sophisticated)
COMMAND_HANDLERS = {
    commands.CreateCaseCommand: handle_create_case_command,
}
