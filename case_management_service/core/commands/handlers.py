# Command Handler Implementation
import logging
import uuid
from typing import List # Added List

# Corrected imports for refactored structure
from .models import CreateCaseCommand
from case_management_service.core.events import models as domain_event_models
from case_management_service.infrastructure.database.event_store import save_event
from case_management_service.core.events.projectors import dispatch_event_to_projectors
from case_management_service.app.observability import tracer
from opentelemetry import trace

logger = logging.getLogger(__name__)

async def handle_create_case_command(command: CreateCaseCommand) -> str:
    current_span = trace.get_current_span()
    current_span.set_attribute("command.name", "CreateCaseCommand")
    current_span.set_attribute("command.id", command.command_id)
    current_span.set_attribute("traitement.type", command.traitement_type)
    current_span.add_event("CreateCaseCommandHandlerStarted")

    logger.info(f"Handling CreateCaseCommand: {command.command_id} for client {command.client_id}, type: {command.traitement_type}")

    case_id = str(uuid.uuid4()) # This is the main case aggregate ID
    company_id_str: Optional[str] = None # Will hold company_id if KYB

    events_to_dispatch: List[domain_event_models.BaseEvent] = []

    # Version tracking for aggregates within this command's scope
    # (Simplified: assumes this handler is the sole source of version increments for new aggregates during this tx)
    company_aggregate_version = 0
    case_aggregate_version = 0

    # --- Company Profile Processing (for KYB) ---
    if command.traitement_type == "KYB":
        if command.company_profile:
            company_id_obj = uuid.uuid4() # Generate a new UUID for company_id
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

    # --- Case Creation Event (Always created) ---
    case_aggregate_version += 1
    case_created_payload = domain_event_models.CaseCreatedEventPayload(
        client_id=command.client_id,
        case_type=command.case_type, # This is 'type' from Kafka message
        case_version=command.case_version, # This is 'version' from Kafka message
        traitement_type=command.traitement_type,
        company_id=company_id_str # Link case to company if KYB
    )
    case_created_event = domain_event_models.CaseCreatedEvent(
        aggregate_id=case_id,
        payload=case_created_payload,
        version=case_aggregate_version
    )
    await save_event(case_created_event)
    events_to_dispatch.append(case_created_event)
    current_span.add_event("CaseCreatedEventGenerated", {"case.id": case_id, "company.id.link": company_id_str if company_id_str else "N/A"})

    # --- Persons Processing ---
    # This loop handles persons listed in the 'persons' array of the command.
    # These persons are either linked to the company (for KYB) or to the case (for KYC).
    for person_data in command.persons:
        person_id_str = str(uuid.uuid4())

        if command.traitement_type == "KYB" and company_id_str:
            if person_data.role_in_company:
                company_aggregate_version += 1
                person_linked_payload = domain_event_models.PersonLinkedToCompanyEventPayload(
                    person_id=person_id_str,
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
                current_span.add_event("PersonLinkedToCompanyEventGenerated", {"person.id": person_id_str, "company.id": company_id_str, "role": person_data.role_in_company})
            else:
                logger.warning(f"Person {person_data.firstname} provided for KYB case {case_id} without a role_in_company. Not linking to company {company_id_str}.")

        elif command.traitement_type == "KYC":
            case_aggregate_version += 1 # Versioning against the Case aggregate
            person_added_payload = domain_event_models.PersonAddedToCaseEventPayload(
                person_id=person_id_str,
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
            current_span.add_event("PersonAddedToCaseEventGenerated", {"person.id": person_id_str, "case.id": case_id})

    # --- Beneficial Owner Processing (for KYB) ---
    if command.traitement_type == "KYB" and company_id_str and command.beneficial_owners:
        for bo_data in command.beneficial_owners:
            company_aggregate_version += 1
            bo_id_str = str(uuid.uuid4()) # ID for the BO link/record itself

            # The person_details within bo_data might also need to be processed to create/link a Person entity
            # and then that Person's ID used in PersonLinkedToCompanyEvent if BOs are also formal company roles.
            # For now, BeneficialOwnerAddedEvent captures the BO details directly.
            # If bo_data.person_details.role_in_company is set, a separate PersonLinkedToCompanyEvent could be emitted.
            # This depends on how detailed the BO role vs. other roles (director, etc.) should be.
            # For simplicity, only creating BeneficialOwnerAddedEvent here.

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

    # --- Dispatch all generated events to projectors ---
    for event_to_dispatch in events_to_dispatch:
        await dispatch_event_to_projectors(event_to_dispatch)

    logger.info(f"Successfully processed CreateCaseCommand for case_id: {case_id}. Total events created and dispatched: {len(events_to_dispatch)}.")
    current_span.add_event("CreateCaseCommandHandlerFinished", {"case.id": case_id, "events.dispatched.count": len(events_to_dispatch)})

    return case_id
