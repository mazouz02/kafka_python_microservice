# Event Store Logic (Saving and Retrieving Domain Events)
import logging
from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorDatabase # Added for type hinting

# Corrected imports
from .schemas import StoredEventDB
# Explicitly import event and payload models
from case_management_service.app.service.events.models import ( # Updated import path
    BaseEvent, EventMetaData, # Base types
    CaseCreatedEvent, CaseCreatedEventPayload,
    CompanyProfileCreatedEvent, CompanyProfileCreatedEventPayload,
# Import custom exceptions
from case_management_service.app.service.exceptions import ConcurrencyConflictError
    BeneficialOwnerAddedEvent, BeneficialOwnerAddedEventPayload,
    PersonLinkedToCompanyEvent, PersonLinkedToCompanyEventPayload,
    PersonAddedToCaseEvent, PersonAddedToCaseEventPayload,
    DocumentRequirementDeterminedEvent, DocumentRequirementDeterminedEventPayload,
    DocumentStatusUpdatedEvent, DocumentStatusUpdatedEventPayload,
    NotificationRequiredEvent, NotificationRequiredEventPayload
)

logger = logging.getLogger(__name__)

# Mapping for event types to their classes
# Event type strings are as defined in the event_type attribute of each event model
EVENT_CLASS_MAP = {
    "CaseCreated": CaseCreatedEvent,
    "CompanyProfileCreated": CompanyProfileCreatedEvent,
    "BeneficialOwnerAdded": BeneficialOwnerAddedEvent,
    "PersonLinkedToCompany": PersonLinkedToCompanyEvent,
    "PersonAddedToCase": PersonAddedToCaseEvent,
    "DocumentRequirementDetermined": DocumentRequirementDeterminedEvent,
    "DocumentStatusUpdated": DocumentStatusUpdatedEvent,
    "NotificationRequired": NotificationRequiredEvent,
}

# Mapping for payload model names to their classes
PAYLOAD_CLASS_MAP = {
    "CaseCreatedEventPayload": CaseCreatedEventPayload,
    "CompanyProfileCreatedEventPayload": CompanyProfileCreatedEventPayload,
    "BeneficialOwnerAddedEventPayload": BeneficialOwnerAddedEventPayload,
    "PersonLinkedToCompanyEventPayload": PersonLinkedToCompanyEventPayload,
    "PersonAddedToCaseEventPayload": PersonAddedToCaseEventPayload,
    "DocumentRequirementDeterminedEventPayload": DocumentRequirementDeterminedEventPayload,
    "DocumentStatusUpdatedEventPayload": DocumentStatusUpdatedEventPayload,
    "NotificationRequiredEventPayload": NotificationRequiredEventPayload,
}
EVENT_STORE_COLLECTION = "domain_events"

async def save_event(db: AsyncIOMotorDatabase, event_data: BaseEvent) -> BaseEvent: # Added db argument
    # db = await get_database() # Removed internal call

    latest_event_document = await db[EVENT_STORE_COLLECTION].find_one(
        {"aggregate_id": event_data.aggregate_id},
        sort=[("version", -1)]
    )
    latest_version = 0
    if latest_event_document:
        latest_version = latest_event_document.get("version", 0)

    if event_data.version <= latest_version and latest_version != 0:
        error_msg = (
            f"Concurrency conflict for aggregate {event_data.aggregate_id}. "
            f"Attempted event version {event_data.version}, but latest version in DB is {latest_version}."
        )
        logger.error(error_msg)
        raise ConcurrencyConflictError(
            aggregate_id=event_data.aggregate_id,
            expected_version=event_data.version -1, # Or however expected version is derived for command
            actual_version=latest_version
        )

    stored_event_payload = event_data.payload.model_dump()

    # Ensure metadata is correctly dumped from the domain model's EventMetaData
    stored_metadata_dict = event_data.metadata.model_dump()

    stored_event_dict = StoredEventDB(
        event_id=event_data.event_id,
        event_type=event_data.event_type,
        aggregate_id=event_data.aggregate_id,
        timestamp=event_data.timestamp,
        version=event_data.version,
        payload=stored_event_payload,
        metadata=stored_metadata_dict # Use the dumped dict for StoredEventMetaData
    ).model_dump()

    await db[EVENT_STORE_COLLECTION].insert_one(stored_event_dict)
    logger.info(f"Event '{event_data.event_type}' (ID: {event_data.event_id}) saved for aggregate {event_data.aggregate_id} with version {event_data.version}.")

    return event_data

async def get_events_for_aggregate(db: AsyncIOMotorDatabase, aggregate_id: str) -> List[BaseEvent]: # Added db argument
    # db = await get_database() # Removed internal call

    stored_events_cursor = db[EVENT_STORE_COLLECTION].find({"aggregate_id": aggregate_id}).sort("version", 1)

    deserialized_domain_events = []
    async for event_doc in stored_events_cursor:
        try:
            stored_event = StoredEventDB(**event_doc)
        except Exception as e:
            logger.error(f"Invalid event document structure in DB for aggregate {aggregate_id}, doc: {event_doc}. Error: {e}", exc_info=True)
            continue

        event_type_str = stored_event.event_type # e.g., "CaseCreated"
        payload_dict = stored_event.payload

        DomainEventClass = EVENT_CLASS_MAP.get(event_type_str)

        if DomainEventClass:
            # payload_model_name is a class variable on specific event types
            PayloadModelStr = getattr(DomainEventClass, 'payload_model_name', None)
            if not PayloadModelStr:
                logger.error(f"Event class {DomainEventClass.__name__} is missing 'payload_model_name' attribute.")
                continue

            PayloadModelClass = PAYLOAD_CLASS_MAP.get(PayloadModelStr)

            if PayloadModelClass:
                try:
                    deserialized_payload = PayloadModelClass(**payload_dict)

                    # Reconstruct domain's EventMetaData from StoredEventMetaData dict
                    # Ensure stored_event.metadata is not None before dumping
                    meta_data_dict = stored_event.metadata.model_dump() if stored_event.metadata else {}
                    deserialized_metadata = EventMetaData(**meta_data_dict)

                    domain_event_instance = DomainEventClass(
                        event_id=stored_event.event_id,
                        # event_type is set by the DomainEventClass itself, no need to pass from stored_event
                        aggregate_id=stored_event.aggregate_id,
                        timestamp=stored_event.timestamp,
                        version=stored_event.version,
                        payload=deserialized_payload,
                        metadata=deserialized_metadata
                    )
                    # The payload_model_name is already part of the class definition,
                    # no need to setattr unless it's managed differently.
                    # It's a class var, so instances will have access to it via their class.

                    deserialized_domain_events.append(domain_event_instance)
                except Exception as e:
                    logger.error(f"Error deserializing payload for event {stored_event.event_id} of type {event_type_str}: {e}", exc_info=True)
            else:
                logger.warning(f"Payload model class '{PayloadModelStr}' not found in PAYLOAD_CLASS_MAP for event type '{event_type_str}'. Aggregate: {aggregate_id}")
        else:
            logger.warning(f"Domain event class for event_type '{event_type_str}' not found in EVENT_CLASS_MAP. Aggregate: {aggregate_id}")

    logger.info(f"Retrieved and deserialized {len(deserialized_domain_events)} events for aggregate {aggregate_id}.")
    return deserialized_domain_events
