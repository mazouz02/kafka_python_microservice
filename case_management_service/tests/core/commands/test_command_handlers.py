# Unit Tests for Command Handlers (Refactored Structure)
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, call # Removed MagicMock as it wasn't strictly needed here
import uuid
import datetime # Added for mock data

# Modules to test and their new locations
from case_management_service.core.commands import models as commands
from case_management_service.core.commands import handlers as command_handlers
from case_management_service.core.events import models as domain_events
# Updated import to include CompanyProfileData, BeneficialOwnerData, AddressData
from case_management_service.infrastructure.kafka.schemas import PersonData, CompanyProfileData, BeneficialOwnerData, AddressData
# Added import for db_schemas for RequiredDocumentDB mock in UpdateDocumentStatusCommand test
from case_management_service.infrastructure.database import schemas as db_schemas


class TestCommandHandlers(unittest.IsolatedAsyncioTestCase):

    @patch('case_management_service.core.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
    @patch('case_management_service.core.commands.handlers.save_event', new_callable=AsyncMock)
    async def test_handle_create_case_command_success(self, mock_save_event, mock_dispatch_projectors):
        # Arrange
        client_id = "test_client_123"
        case_type = "KYC_STANDARD"
        case_version = "1.1"

        person1_data = PersonData(firstname="John", lastname="Doe", birthdate="1990-01-01")
        person2_data = PersonData(firstname="Jane", lastname="Doe", birthdate="1992-02-02")

        cmd = commands.CreateCaseCommand(
            client_id=client_id,
            case_type=case_type,
            case_version=case_version,
            traitement_type="KYC",
            persons=[person1_data, person2_data],
            company_profile=None,
            beneficial_owners=[]
        )

        # Act
        returned_case_id_str = await command_handlers.handle_create_case_command(cmd)

        # Assert
        self.assertIsNotNone(returned_case_id_str)
        try:
            uuid.UUID(returned_case_id_str)
        except ValueError:
            self.fail("Returned case_id is not a valid UUID string")

        self.assertEqual(mock_save_event.call_count, 3)

        saved_events = [call_obj.args[0] for call_obj in mock_save_event.call_args_list]

        case_created_event = next(e for e in saved_events if isinstance(e, domain_events.CaseCreatedEvent))
        self.assertEqual(case_created_event.aggregate_id, returned_case_id_str)
        self.assertEqual(case_created_event.payload.client_id, client_id)
        self.assertEqual(case_created_event.payload.traitement_type, "KYC")
        self.assertIsNone(case_created_event.payload.company_id)
        self.assertEqual(case_created_event.version, 1)

        person_events = [e for e in saved_events if isinstance(e, domain_events.PersonAddedToCaseEvent)]
        self.assertEqual(len(person_events), 2)

        person1_event_saved = next(e for e in person_events if e.payload.firstname == "John")
        self.assertEqual(person1_event_saved.aggregate_id, returned_case_id_str)
        self.assertEqual(person1_event_saved.version, 2)

        person2_event_saved = next(e for e in person_events if e.payload.firstname == "Jane")
        self.assertEqual(person2_event_saved.aggregate_id, returned_case_id_str)
        self.assertEqual(person2_event_saved.version, 3)


        self.assertEqual(mock_dispatch_projectors.call_count, 3)
        dispatched_events = [call_obj.args[0] for call_obj in mock_dispatch_projectors.call_args_list]
        for event in saved_events:
            self.assertIn(event, dispatched_events)

    @patch('case_management_service.core.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
    @patch('case_management_service.core.commands.handlers.save_event', new_callable=AsyncMock)
    async def test_handle_create_case_command_kyb_with_company_and_bos_and_persons(self, mock_save_event, mock_dispatch_projectors):
        # Arrange
        client_id = "kyb_client_001"
        case_type = "KYB_FULL"
        case_version = "1.0"
        traitement_type = "KYB"

        company_address = AddressData(street="123 Corp St", city="Businesstown", country="US", postal_code="12345")
        company_profile = CompanyProfileData(
            registered_name="Test Corp Inc.",
            registration_number="C12345",
            country_of_incorporation="US",
            registered_address=company_address
        )

        bo1_person_details = PersonData(firstname="Beneficial", lastname="OwnerOne", birthdate="1970-01-01")
        bo1_data = BeneficialOwnerData(
            person_details=bo1_person_details,
            ownership_percentage=50.0,
            types_of_control=["Direct Shareholding"],
            is_ubo=True
        )

        director_person_data = PersonData(firstname="Director", lastname="One", birthdate="1980-05-05", role_in_company="Director")
        contact_person_data = PersonData(firstname="Contact", lastname="Person", birthdate="1990-03-03", role_in_company="Primary Contact")

        cmd = commands.CreateCaseCommand(
            client_id=client_id,
            case_type=case_type,
            case_version=case_version,
            traitement_type=traitement_type,
            company_profile=company_profile,
            persons=[director_person_data, contact_person_data],
            beneficial_owners=[bo1_data]
        )

        # Act
        returned_case_id_str = await command_handlers.handle_create_case_command(cmd)

        # Assert
        self.assertIsNotNone(returned_case_id_str)
        self.assertEqual(mock_save_event.call_count, 5)

        saved_events = [call_obj.args[0] for call_obj in mock_save_event.call_args_list]

        company_created_event = next(e for e in saved_events if isinstance(e, domain_events.CompanyProfileCreatedEvent))
        company_id_generated = company_created_event.aggregate_id
        self.assertIsNotNone(company_id_generated)
        self.assertEqual(company_created_event.payload.registered_name, company_profile.registered_name)
        self.assertEqual(company_created_event.version, 1)

        case_created_event = next(e for e in saved_events if isinstance(e, domain_events.CaseCreatedEvent))
        self.assertEqual(case_created_event.aggregate_id, returned_case_id_str)
        self.assertEqual(case_created_event.payload.client_id, client_id)
        self.assertEqual(case_created_event.payload.traitement_type, "KYB")
        self.assertEqual(case_created_event.payload.company_id, company_id_generated)
        self.assertEqual(case_created_event.version, 1)

        person_linked_events = [e for e in saved_events if isinstance(e, domain_events.PersonLinkedToCompanyEvent)]
        self.assertEqual(len(person_linked_events), 2)

        director_event = next(e for e in person_linked_events if e.payload.firstname == "Director")
        self.assertEqual(director_event.aggregate_id, company_id_generated)
        self.assertEqual(director_event.payload.role_in_company, "Director")

        contact_event = next(e for e in person_linked_events if e.payload.firstname == "Contact")
        self.assertEqual(contact_event.aggregate_id, company_id_generated)
        self.assertEqual(contact_event.payload.role_in_company, "Primary Contact")

        sorted_company_agg_events = sorted(
            [e for e in saved_events if e.aggregate_id == company_id_generated],
            key=lambda e: e.version
        )
        self.assertEqual(sorted_company_agg_events[0].version, 1)
        self.assertIsInstance(sorted_company_agg_events[0], domain_events.CompanyProfileCreatedEvent)
        self.assertEqual(sorted_company_agg_events[1].version, 2)
        self.assertIsInstance(sorted_company_agg_events[1], domain_events.PersonLinkedToCompanyEvent)
        self.assertEqual(sorted_company_agg_events[2].version, 3)
        self.assertIsInstance(sorted_company_agg_events[2], domain_events.PersonLinkedToCompanyEvent)

        bo_added_event = next(e for e in saved_events if isinstance(e, domain_events.BeneficialOwnerAddedEvent))
        self.assertEqual(bo_added_event.aggregate_id, company_id_generated)
        self.assertEqual(bo_added_event.payload.person_details.firstname, "Beneficial")
        self.assertTrue(bo_added_event.payload.is_ubo)
        self.assertEqual(bo_added_event.version, 4)

        self.assertEqual(mock_dispatch_projectors.call_count, mock_save_event.call_count)
        dispatched_events = [call_obj.args[0] for call_obj in mock_dispatch_projectors.call_args_list]
        for saved_event in saved_events:
            self.assertIn(saved_event, dispatched_events)

    @patch('case_management_service.core.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
    @patch('case_management_service.core.commands.handlers.save_event', new_callable=AsyncMock)
    async def test_handle_create_case_command_kyc_only_person(self, mock_save_event, mock_dispatch_projectors):
        client_id = "kyc_client_002"
        case_type = "KYC_SIMPLE"
        case_version = "1.0"
        traitement_type = "KYC"
        person_data = PersonData(firstname="Simple", lastname="KycPerson", birthdate="1995-06-15")

        cmd = commands.CreateCaseCommand(
            client_id=client_id,
            case_type=case_type,
            case_version=case_version,
            traitement_type=traitement_type,
            persons=[person_data],
            company_profile=None,
            beneficial_owners=[]
        )

        returned_case_id_str = await command_handlers.handle_create_case_command(cmd)

        self.assertIsNotNone(returned_case_id_str)
        self.assertEqual(mock_save_event.call_count, 2)

        saved_events = [call_obj.args[0] for call_obj in mock_save_event.call_args_list]

        case_created_event = next(e for e in saved_events if isinstance(e, domain_events.CaseCreatedEvent))
        self.assertEqual(case_created_event.payload.traitement_type, "KYC")
        self.assertIsNone(case_created_event.payload.company_id)
        self.assertEqual(case_created_event.version, 1)

        person_added_event = next(e for e in saved_events if isinstance(e, domain_events.PersonAddedToCaseEvent))
        self.assertEqual(person_added_event.aggregate_id, returned_case_id_str)
        self.assertEqual(person_added_event.payload.firstname, "Simple")
        self.assertEqual(person_added_event.version, 2)

        self.assertEqual(mock_dispatch_projectors.call_count, 2)

    # --- Tests for Document Requirement Command Handlers ---

    @patch('case_management_service.core.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
    @patch('case_management_service.core.commands.handlers.save_event', new_callable=AsyncMock)
    async def test_handle_determine_initial_document_requirements_person_kyc(self, mock_save_event, mock_dispatch_projectors):
        case_id = str(uuid.uuid4())
        person_id = str(uuid.uuid4())
        cmd = commands.DetermineInitialDocumentRequirementsCommand(
            case_id=case_id,
            entity_id=person_id,
            entity_type="PERSON",
            traitement_type="KYC",
            case_type="STANDARD",
            context_data={}
        )

        generated_event_ids = await command_handlers.handle_determine_initial_document_requirements(cmd)

        self.assertEqual(len(generated_event_ids), 2) # PASSPORT, PROOF_OF_ADDRESS
        self.assertEqual(mock_save_event.call_count, 2)
        self.assertEqual(mock_dispatch_projectors.call_count, 2)

        saved_events = [call_obj.args[0] for call_obj in mock_save_event.call_args_list]

        passport_event = next(e for e in saved_events if e.payload.document_type == "PASSPORT")
        self.assertIsInstance(passport_event, domain_events.DocumentRequirementDeterminedEvent)
        self.assertEqual(passport_event.aggregate_id, case_id)
        self.assertEqual(passport_event.payload.entity_id, person_id)
        self.assertTrue(passport_event.payload.is_required)

        # Versioning in handler is simplified for these events, check based on that.
        # The handler's current logic for these events: "version=doc_event_version # Simplified versioning"
        # and doc_event_version = 1, not incremented in loop. This means all these events get version 1.
        # This is a known simplification/potential issue in the handler.
        self.assertEqual(passport_event.version, 1)
        proof_event = next(e for e in saved_events if e.payload.document_type == "PROOF_OF_ADDRESS")
        self.assertEqual(proof_event.version, 1)


    @patch('case_management_service.core.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
    @patch('case_management_service.core.commands.handlers.save_event', new_callable=AsyncMock)
    async def test_handle_determine_initial_document_requirements_company_kyb(self, mock_save_event, mock_dispatch_projectors):
        case_id = str(uuid.uuid4())
        company_id = str(uuid.uuid4())
        cmd = commands.DetermineInitialDocumentRequirementsCommand(
            case_id=case_id,
            entity_id=company_id,
            entity_type="COMPANY",
            traitement_type="KYB",
            case_type="STANDARD",
            context_data={}
        )
        await command_handlers.handle_determine_initial_document_requirements(cmd)
        self.assertEqual(mock_save_event.call_count, 2) # COMPANY_REGISTRATION_CERTIFICATE, ARTICLES_OF_ASSOCIATION


    @patch('case_management_service.core.commands.handlers.get_required_document_by_id', new_callable=AsyncMock) # Patched here
    @patch('case_management_service.core.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
    @patch('case_management_service.core.commands.handlers.save_event', new_callable=AsyncMock)
    async def test_handle_update_document_status_success(
        self, mock_save_event, mock_dispatch_projectors, mock_get_doc_req_by_id
    ):
        doc_req_id = str(uuid.uuid4())
        cmd = commands.UpdateDocumentStatusCommand(
            document_requirement_id=doc_req_id,
            new_status="UPLOADED",
            updated_by_actor_type="USER",
            updated_by_actor_id="user123"
        )
        mock_current_doc = db_schemas.RequiredDocumentDB(
            id=doc_req_id, case_id="c1", entity_id="e1", entity_type="PERSON",
            document_type="PASSPORT", status="AWAITING_UPLOAD", is_required=True,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow() # This will be used for pseudo-version
        )
        mock_get_doc_req_by_id.return_value = mock_current_doc

        result_doc_req_id = await command_handlers.handle_update_document_status(cmd)

        self.assertEqual(result_doc_req_id, doc_req_id)
        mock_save_event.assert_called_once()
        mock_dispatch_projectors.assert_called_once()

        saved_event = mock_save_event.call_args.args[0]
        self.assertIsInstance(saved_event, domain_events.DocumentStatusUpdatedEvent)
        self.assertEqual(saved_event.aggregate_id, doc_req_id)
        self.assertEqual(saved_event.payload.new_status, "UPLOADED")
        self.assertEqual(saved_event.payload.old_status, "AWAITING_UPLOAD")
        self.assertEqual(saved_event.payload.updated_by, "user123")
        # Versioning for DocumentStatusUpdatedEvent using timestamp pseudo-version
        self.assertEqual(saved_event.version, int(mock_current_doc.updated_at.timestamp()))


    @patch('case_management_service.core.commands.handlers.get_required_document_by_id', new_callable=AsyncMock) # Patched here
    @patch('case_management_service.core.commands.handlers.save_event', new_callable=AsyncMock)
    async def test_handle_update_document_status_doc_not_found(self,mock_save_event, mock_get_doc_req_by_id):
        doc_req_id = "non_existent_doc_id"
        cmd = commands.UpdateDocumentStatusCommand(
            document_requirement_id=doc_req_id, new_status="UPLOADED"
        )
        mock_get_doc_req_by_id.return_value = None

        result = await command_handlers.handle_update_document_status(cmd)

        self.assertIsNone(result)
        mock_save_event.assert_not_called()

# To run these tests (after all test files are created):
# Ensure PYTHONPATH includes the root directory of the project (e.g., parent of case_management_service)
# python -m unittest case_management_service.tests.core.commands.test_command_handlers
# Or using pytest: pytest case_management_service/tests/core/commands/test_command_handlers.py
