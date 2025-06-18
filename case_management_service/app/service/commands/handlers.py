# Command Handler Implementation
import logging
import uuid
from typing import List, Optional, Dict, Any # Added Dict, Any for notification context

# Corrected imports for refactored structure
from .models import CreateCaseCommand, DetermineInitialDocumentRequirementsCommand, UpdateDocumentStatusCommand
from case_management_service.app.service.events import models as domain_event_models
from case_management_service.infrastructure.database.event_store import save_event
from case_management_service.app.service.events.projectors import dispatch_event_to_projectors
from case_management_service.app.observability import tracer
from opentelemetry import trace

# Imports for new notification logic
from case_management_service.infrastructure.config_service_client import get_notification_config
from case_management_service.infrastructure.kafka.producer import get_kafka_producer
from case_management_service.app.config import settings # For NOTIFICATION_KAFKA_TOPIC

# Import for handle_update_document_status to read current doc (design choice)
from case_management_service.infrastructure.database.document_requirements_store import get_required_document_by_id


logger = logging.getLogger(__name__)

async def handle_create_case_command(command: CreateCaseCommand) -> str:
    current_span = trace.get_current_span()
    current_span.set_attribute("command.name", "CreateCaseCommand")
    current_span.set_attribute("command.id", command.command_id)
    current_span.set_attribute("traitement.type", command.traitement_type)
    current_span.add_event("CreateCaseCommandHandlerStarted")

    logger.info(f"Handling CreateCaseCommand: {command.command_id} for client {command.client_id}, type: {command.traitement_type}")

    case_id = str(uuid.uuid4())
    company_id_str: Optional[str] = None

    events_to_dispatch: List[domain_event_models.BaseEvent] = []

    company_aggregate_version = 0
    case_aggregate_version = 0 # Tracks current version for the case being created

    if command.traitement_type == "KYB":
        if command.company_profile:
            company_id_obj = uuid.uuid4()
            company_id_str = str(company_id_obj)
            logger.info(f"Processing KYB company profile. New company_id: {company_id_str}")

            company_profile_payload = domain_event_models.CompanyProfileCreatedEventPayload(
                registered_name=command.company_profile.registered_name,
                trading_name=command.company_profile.trading_name,
                registration_number=command.company_profile.registration_number,
                registration_date=command.company_profile.registration_date,
                country_of_incorporation=command.company_profile.country_of_incorporation,
                registered_address=command.company_profile.registered_address,
                business_type=command.company_profile.business_type,
                industry_sector=command.company_profile.industry_sector
            )
            company_aggregate_version += 1
            company_created_event = domain_event_models.CompanyProfileCreatedEvent(
                aggregate_id=company_id_str,
                payload=company_profile_payload,
                version=company_aggregate_version
            )
            await save_event(company_created_event)
            events_to_dispatch.append(company_created_event)
            current_span.add_event("CompanyProfileCreatedEventGenerated", {"company.id": company_id_str})
        else:
            logger.warning(f"KYB treatment type specified for case {case_id} but no company_profile data provided in command.")

    case_aggregate_version += 1
    case_created_payload = domain_event_models.CaseCreatedEventPayload(
        client_id=command.client_id,
        case_type=command.case_type,
        case_version=command.case_version,
        traitement_type=command.traitement_type,
        company_id=company_id_str
    )
    case_created_event = domain_event_models.CaseCreatedEvent(
        aggregate_id=case_id,
        payload=case_created_payload,
        version=case_aggregate_version
    )
    await save_event(case_created_event)
    events_to_dispatch.append(case_created_event)
    current_span.add_event("CaseCreatedEventGenerated", {"case.id": case_id, "company.id.link": company_id_str if company_id_str else "N/A"})

    for person_data in command.persons:
        person_id_str_for_event = str(uuid.uuid4()) # Unique ID for this person instance/link for event payload

        if command.traitement_type == "KYB" and company_id_str:
            if person_data.role_in_company:
                company_aggregate_version += 1
                person_linked_payload = domain_event_models.PersonLinkedToCompanyEventPayload(
                    person_id=person_id_str_for_event,
                    firstname=person_data.firstname,
                    lastname=person_data.lastname,
                    birthdate=person_data.birthdate,
                    role_in_company=person_data.role_in_company
                )
                person_linked_event = domain_event_models.PersonLinkedToCompanyEvent(
                    aggregate_id=company_id_str,
                    payload=person_linked_payload,
                    version=company_aggregate_version
                )
                await save_event(person_linked_event)
                events_to_dispatch.append(person_linked_event)
                current_span.add_event("PersonLinkedToCompanyEventGenerated", {"person.id": person_id_str_for_event, "company.id": company_id_str, "role": person_data.role_in_company})
            else:
                logger.warning(f"Person {person_data.firstname} provided for KYB case {case_id} without a role_in_company. Not linking to company {company_id_str}.")

        elif command.traitement_type == "KYC":
            case_aggregate_version += 1
            person_added_payload = domain_event_models.PersonAddedToCaseEventPayload(
                person_id=person_id_str_for_event,
                firstname=person_data.firstname,
                lastname=person_data.lastname,
                birthdate=person_data.birthdate
            )
            person_added_event = domain_event_models.PersonAddedToCaseEvent(
                aggregate_id=case_id,
                payload=person_added_payload,
                version=case_aggregate_version
            )
            await save_event(person_added_event)
            events_to_dispatch.append(person_added_event)
            current_span.add_event("PersonAddedToCaseEventGenerated", {"person.id": person_id_str_for_event, "case.id": case_id})

    if command.traitement_type == "KYB" and company_id_str and command.beneficial_owners:
        for bo_data in command.beneficial_owners:
            company_aggregate_version += 1
            bo_id_str = str(uuid.uuid4())

            bo_added_payload = domain_event_models.BeneficialOwnerAddedEventPayload(
                beneficial_owner_id=bo_id_str,
                person_details=bo_data.person_details,
                ownership_percentage=bo_data.ownership_percentage,
                types_of_control=bo_data.types_of_control,
                is_ubo=bo_data.is_ubo
            )
            bo_added_event = domain_event_models.BeneficialOwnerAddedEvent(
                aggregate_id=company_id_str,
                payload=bo_added_payload,
                version=company_aggregate_version
            )
            await save_event(bo_added_event)
            events_to_dispatch.append(bo_added_event)
            current_span.add_event("BeneficialOwnerAddedEventGenerated", {"bo.id": bo_id_str, "company.id": company_id_str})

    # --- Configurable Notification Logic ---
    config_service_event_trigger = f"CASE_CREATED_{command.traitement_type}_{command.case_type}".upper().replace("-", "_")
    config_service_context: Dict[str, Any] = {
        "case_id": case_id,
        "client_id": command.client_id,
        "traitement_type": command.traitement_type,
        "case_type": command.case_type,
    }

    notification_rule = await get_notification_config(config_service_event_trigger, config_service_context)

    primary_person_for_notification = command.persons[0] if command.persons else None
    recipient_details_for_notification: Dict[str, Any] = { "case_id": case_id, "client_id": command.client_id }
    if primary_person_for_notification:
         recipient_details_for_notification["primary_contact_name"] = f"{primary_person_for_notification.firstname} {primary_person_for_notification.lastname}"
         # In a real system, you'd fetch/pass actual contact details like email/phone.

    if notification_rule and notification_rule.is_active:
        logger.info(f"Notification rule {notification_rule.rule_id} matched for case {case_id}. Preparing notification.")

        notification_payload = domain_event_models.NotificationRequiredEventPayload(
            notification_type=notification_rule.notification_type,
            recipient_details=recipient_details_for_notification,
            template_id=notification_rule.template_id,
            language_code=notification_rule.language_code,
            context_data={
                "case_id": case_id,
                "client_name": f"{primary_person_for_notification.firstname if primary_person_for_notification else 'N/A'}",
                "case_type": command.case_type,
                "traitement_type": command.traitement_type,
            }
        )

        case_aggregate_version += 1 # Increment version for the case aggregate
        notification_event = domain_event_models.NotificationRequiredEvent(
            aggregate_id=case_id,
            payload=notification_payload,
            version=case_aggregate_version
        )

        await save_event(notification_event)
        # NotificationRequiredEvent is not typically projected by local projectors in the same service.
        # It's for an external notification service. So, not adding to events_to_dispatch.

        try:
            kafka_producer = get_kafka_producer()
            kafka_producer.produce_message(
                topic=settings.NOTIFICATION_KAFKA_TOPIC,
                message=notification_event,
                key=case_id
            )
            logger.info(f"NotificationRequiredEvent for case {case_id} published to Kafka topic {settings.NOTIFICATION_KAFKA_TOPIC}.")
            current_span.add_event("NotificationRequiredEventPublishedToKafka", {"event.id": notification_event.event_id, "kafka.topic": settings.NOTIFICATION_KAFKA_TOPIC})
        except Exception as e:
            logger.error(f"Failed to publish NotificationRequiredEvent for case {case_id} to Kafka: {e}", exc_info=True)
            current_span.record_exception(e)
    elif notification_rule is None: # Rule is None could mean service down or no rule matched
        logger.info(f"No active notification rule found or config service unavailable for case {case_id} (trigger: {config_service_event_trigger}).")
    else: # Rule exists but is_active is False
        logger.info(f"Matching notification rule ({notification_rule.rule_id}) found for case {case_id} but it is inactive.")


    # --- Dispatch core domain events to local projectors ---
    for event_to_dispatch in events_to_dispatch:
        await dispatch_event_to_projectors(event_to_dispatch)

    logger.info(f"Successfully processed CreateCaseCommand for case_id: {case_id}. Total core events dispatched to projectors: {len(events_to_dispatch)}.")
    current_span.add_event("CreateCaseCommandHandlerFinished", {"case.id": case_id, "core.events.dispatched.count": len(events_to_dispatch)})

    return case_id

# --- Document Requirement Command Handlers ---

async def handle_determine_initial_document_requirements(command: DetermineInitialDocumentRequirementsCommand) -> List[str]:
    current_span = trace.get_current_span()
    current_span.set_attribute("command.name", "DetermineInitialDocumentRequirementsCommand")
    # ... (rest of attributes and logging as before) ...
    logger.info(f"Handling DetermineInitialDocumentRequirementsCommand for case {command.case_id}, entity {command.entity_id} ({command.entity_type})")

    events_to_dispatch: List[domain_event_models.BaseEvent] = []
    determined_doc_req_event_ids: List[str] = []

    # Simplified Rules Engine logic (as before)
    required_docs_for_entity = []
    if command.entity_type == "PERSON":
        if command.traitement_type == "KYC":
            required_docs_for_entity.append({"type": "PASSPORT", "is_required": True})
            required_docs_for_entity.append({"type": "PROOF_OF_ADDRESS", "is_required": True})
        elif command.traitement_type == "KYB":
            required_docs_for_entity.append({"type": "PASSPORT_DIRECTOR_BO", "is_required": True})
    elif command.entity_type == "COMPANY":
        if command.traitement_type == "KYB":
            required_docs_for_entity.append({"type": "COMPANY_REGISTRATION_CERTIFICATE", "is_required": True})
            required_docs_for_entity.append({"type": "ARTICLES_OF_ASSOCIATION", "is_required": True})
            if command.case_type == "ENHANCED_DUE_DILIGENCE":
                 required_docs_for_entity.append({"type": "FINANCIAL_STATEMENTS_AUDITED", "is_required": True})

    # Versioning: Assume these events are new facts related to the case.
    # The `save_event` function's optimistic concurrency check (if aggregate exists)
    # will use the version provided in the event. If these are the first events for a new
    # "DocumentRequirement" aggregate (if modeled that way), version 1 is fine.
    # If they are part of the "Case" aggregate, version needs to be managed against the Case.
    # The handler currently sets aggregate_id = command.case_id for these events.
    # Let's assume version 1 for each, and save_event will handle it or warn.
    # This implies each DocumentRequirementDeterminedEvent is a standalone fact, not strictly versioning the Case itself.
    # This needs to be consistent with how save_event is implemented.
    # The current `save_event` checks `event_data.version <= latest_version`.
    # If we want to append to Case aggregate, we need to know Case's current version.
    # For now, let's use version 1 for each determination event.
    # This is a simplification and likely incorrect for true ES on the Case aggregate.

    for doc_spec in required_docs_for_entity:
        event_payload = domain_event_models.DocumentRequirementDeterminedEventPayload(
            case_id=command.case_id,
            entity_id=command.entity_id,
            entity_type=command.entity_type,
            document_type=doc_spec["type"],
            is_required=doc_spec["is_required"]
        )
        doc_req_event = domain_event_models.DocumentRequirementDeterminedEvent(
            aggregate_id=command.case_id,
            payload=event_payload,
            version=1 # Simplified: each determination is a new v1 event for its own event_id, grouped by case_id.
                      # Or, this should be a version on the Case aggregate.
        )
        await save_event(doc_req_event)
        events_to_dispatch.append(doc_req_event)
        determined_doc_req_event_ids.append(doc_req_event.event_id)
        current_span.add_event(f"DocumentRequirementDetermined: {doc_spec['type']}")

    for event_to_dispatch in events_to_dispatch:
        await dispatch_event_to_projectors(event_to_dispatch)

    logger.info(f"Determined {len(events_to_dispatch)} document requirements for entity {command.entity_id} in case {command.case_id}.")
    current_span.add_event("DetermineInitialDocsCommandHandlerFinished", {"requirements.determined.count": len(events_to_dispatch)})
    return determined_doc_req_event_ids


async def handle_update_document_status(command: UpdateDocumentStatusCommand) -> Optional[str]:
    current_span = trace.get_current_span()
    current_span.set_attribute("command.name", "UpdateDocumentStatusCommand")
    # ... (rest of attributes and logging as before) ...
    logger.info(f"Handling UpdateDocumentStatusCommand for doc_req_id: {command.document_requirement_id} to status {command.new_status}")

    current_doc_req = await get_required_document_by_id(command.document_requirement_id)

    if not current_doc_req:
        logger.error(f"DocumentRequirement ID {command.document_requirement_id} not found. Cannot update status.")
        current_span.set_attribute("error", True) # Ensure error attribute is set
        current_span.set_attribute("error.message", "DocumentRequirement not found")
        return None

    old_status = current_doc_req.status

    # Versioning for DocumentStatusUpdatedEvent:
    # Aggregate is command.document_requirement_id.
    # save_event will check version against existing events for this aggregate_id.
    # This means the RequiredDocumentDB (read model) needs a version field that projectors update.
    # If RequiredDocumentDB doesn't have a version, we can't do a proper optimistic check here
    # without reading the event store for the DocumentRequirement aggregate.
    # For now, use a placeholder/pseudo-version as before, acknowledging this limitation.
    next_version = int(current_doc_req.updated_at.timestamp()) # Still a pseudo-version

    event_payload = domain_event_models.DocumentStatusUpdatedEventPayload(
        document_requirement_id=command.document_requirement_id,
        new_status=command.new_status,
        old_status=old_status,
        updated_by=command.updated_by_actor_id or command.updated_by_actor_type or "SYSTEM",
        metadata_update=command.metadata_changes,
        notes_added=command.notes_to_add
    )

    doc_status_event = domain_event_models.DocumentStatusUpdatedEvent(
        aggregate_id=command.document_requirement_id,
        payload=event_payload,
        version=next_version
    )

    await save_event(doc_status_event)
    await dispatch_event_to_projectors(doc_status_event)

    logger.info(f"DocumentStatusUpdatedEvent dispatched for doc_req_id: {command.document_requirement_id}")
    current_span.add_event("UpdateDocStatusCommandHandlerFinished")
    return command.document_requirement_id
