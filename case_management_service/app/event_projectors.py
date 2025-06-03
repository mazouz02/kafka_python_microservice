import logging
from .domain_events import CaseCreatedEvent, PersonAddedToCaseEvent, BaseEvent
from .database import get_database, CaseManagementDB, PersonDB # Read model DB representations
from .database import add_case as upsert_case_read_model # Re-using add_case for upsert logic
from .database import add_person as upsert_person_read_model # Re-using add_person for upsert logic
import datetime

logger = logging.getLogger(__name__)

# --- Projector for CaseCreatedEvent ---
async def project_case_created(event: CaseCreatedEvent):
    logger.info(f"Projecting CaseCreatedEvent: {event.event_id} for aggregate {event.aggregate_id}")
    db = await get_database()
    if not db:
        logger.error("Database not available for projecting CaseCreatedEvent.")
        return

    # Data for CaseManagementDB read model
    case_data_for_read_model = CaseManagementDB(
        id=event.aggregate_id, # Use aggregate_id as the read model's main ID
        client_id=event.payload.client_id,
        version=event.payload.case_version, # from CaseCreatedEventPayload
        type=event.payload.case_type,       # from CaseCreatedEventPayload
        created_at=event.timestamp, # Use event timestamp
        updated_at=event.timestamp
    )

    # Using an "upsert" like logic
    existing_case = await db.cases.find_one({"id": event.aggregate_id})
    if existing_case:
        update_data = case_data_for_read_model.model_dump(exclude_defaults=True) # Use exclude_defaults for cleaner updates
        update_data["updated_at"] = datetime.datetime.utcnow()
        await db.cases.update_one(
            {"id": event.aggregate_id},
            {"$set": update_data}
        )
        logger.info(f"Case read model UPDATED for ID: {event.aggregate_id}")
    else:
        await upsert_case_read_model(case_data_for_read_model)
        # The logger message is in upsert_case_read_model (originally add_case)
        # logger.info(f"Case read model CREATED for ID: {event.aggregate_id}")


# --- Projector for PersonAddedToCaseEvent ---
async def project_person_added_to_case(event: PersonAddedToCaseEvent):
    logger.info(f"Projecting PersonAddedToCaseEvent: {event.event_id} for aggregate {event.aggregate_id}")
    db = await get_database()
    if not db:
        logger.error("Database not available for projecting PersonAddedToCaseEvent.")
        return

    # Data for PersonDB read model
    person_data_for_read_model = PersonDB(
        id=event.payload.person_id, # Use person_id from event payload
        case_id=event.aggregate_id, # Link to the case
        firstname=event.payload.firstname,
        lastname=event.payload.lastname,
        birthdate=event.payload.birthdate,
        created_at=event.timestamp, # Use event timestamp
        updated_at=event.timestamp
    )

    existing_person = await db.persons.find_one({"id": event.payload.person_id})
    if existing_person:
        update_data = person_data_for_read_model.model_dump(exclude_defaults=True)
        update_data["updated_at"] = datetime.datetime.utcnow()
        await db.persons.update_one(
            {"id": event.payload.person_id},
            {"$set": update_data}
        )
        logger.info(f"Person read model UPDATED for ID: {event.payload.person_id}")
    else:
        await upsert_person_read_model(person_data_for_read_model)
        # logger.info(f"Person read model CREATED for ID: {event.payload.person_id}")


# --- Event Dispatcher ---
EVENT_PROJECTORS = {
    "CaseCreated": [project_case_created],
    "PersonAddedToCase": [project_person_added_to_case],
}

async def dispatch_event_to_projectors(event: BaseEvent):
    # This function receives a BaseEvent, but the actual instance passed to it
    # (e.g., from save_event) will be a specific event type like CaseCreatedEvent.
    # The projectors are typed to receive specific event types.
    # This dynamic dispatch works because the object 'event' IS a CaseCreatedEvent or PersonAddedToCaseEvent.
    logger.debug(f"Dispatching event: {event.event_type} (ID: {event.event_id}) to projectors.")
    if event.event_type in EVENT_PROJECTORS:
        for projector_func in EVENT_PROJECTORS[event.event_type]:
            try:
                await projector_func(event) # Pass the specific event instance directly
            except Exception as e:
                logger.error(f"Error in projector {projector_func.__name__} for event {event.event_id}: {e}", exc_info=True)
    else:
        logger.debug(f"No projectors registered for event type: {event.event_type}")
