# Unit Tests for Command Handlers (Refactored Structure)
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, call
import uuid

# Modules to test and their new locations
from case_management_service.core.commands import models as commands
from case_management_service.core.commands import handlers as command_handlers
from case_management_service.core.events import models as domain_events
# Updated import to include CompanyProfileData, BeneficialOwnerData, AddressData
from case_management_service.infrastructure.kafka.schemas import PersonData, CompanyProfileData, BeneficialOwnerData, AddressData

class TestCommandHandlers(unittest.IsolatedAsyncioTestCase):

    @patch('case_management_service.core.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
    @patch('case_management_service.core.commands.handlers.save_event', new_callable=AsyncMock)
    async def test_handle_create_case_command_success(self, mock_save_event, mock_dispatch_projectors):
        # Arrange
        client_id = "test_client_123"
        case_type = "KYC_STANDARD" # Original test was KYC, so this implies traitement_type might be missing or defaulted
        case_version = "1.1"
        # Assuming CreateCaseCommand now requires traitement_type.
        # The original test for CreateCaseCommand might need this field.
        # For this test, let's assume it's a KYC type.
        # The command handler logic for KYC with multiple persons and their versioning was simplified.
        # This test might need adjustment based on that refined (simplified) KYC logic.
        # The original test setup for CreateCaseCommand did not have traitement_type, company_profile, beneficial_owners

        person1_data = PersonData(firstname="John", lastname="Doe", birthdate="1990-01-01")
        person2_data = PersonData(firstname="Jane", lastname="Doe", birthdate="1992-02-02")

        # Adjusting cmd to include new mandatory fields or ensure defaults are fine for KYC path.
        # The command handler now expects 'traitement_type'.
        # The old test did not specify it. If it's KYC, it should be "KYC".
        cmd = commands.CreateCaseCommand(
            client_id=client_id,
            case_type=case_type, # Maps to 'type' in KafkaMessage
            case_version=case_version, # Maps to 'version' in KafkaMessage
            traitement_type="KYC", # Explicitly setting for clarity for this test case
            persons=[person1_data, person2_data],
            company_profile=None, # Explicitly None for KYC
            beneficial_owners=[]  # Explicitly empty for KYC
        )

        # Act
        returned_case_id_str = await command_handlers.handle_create_case_command(cmd)

        # Assert
        self.assertIsNotNone(returned_case_id_str)
        try:
            uuid.UUID(returned_case_id_str)
        except ValueError:
            self.fail("Returned case_id is not a valid UUID string")

        # Expected events for KYC with 2 persons: 1 CaseCreated, 2 PersonAddedToCase
        self.assertEqual(mock_save_event.call_count, 3)

        saved_events = [call_obj.args[0] for call_obj in mock_save_event.call_args_list]

        case_created_event = next(e for e in saved_events if isinstance(e, domain_events.CaseCreatedEvent))
        self.assertEqual(case_created_event.aggregate_id, returned_case_id_str)
        self.assertEqual(case_created_event.payload.client_id, client_id)
        self.assertEqual(case_created_event.payload.traitement_type, "KYC")
        self.assertIsNone(case_created_event.payload.company_id)
        self.assertEqual(case_created_event.version, 1) # Case aggregate version 1

        person_events = [e for e in saved_events if isinstance(e, domain_events.PersonAddedToCaseEvent)]
        self.assertEqual(len(person_events), 2)

        # Check PersonAddedToCaseEvent for person1 (version depends on handler logic for case aggregate)
        person1_event_saved = next(e for e in person_events if e.payload.firstname == "John")
        self.assertEqual(person1_event_saved.aggregate_id, returned_case_id_str)
        self.assertEqual(person1_event_saved.version, 2) # Case aggregate version 2

        # Check PersonAddedToCaseEvent for person2
        person2_event_saved = next(e for e in person_events if e.payload.firstname == "Jane")
        self.assertEqual(person2_event_saved.aggregate_id, returned_case_id_str)
        self.assertEqual(person2_event_saved.version, 3) # Case aggregate version 3


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

        company_address = AddressData(street="123 Corp St", city="Businesstown", country="US", postal_code="12345") # Added postal_code for completeness
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

        # Expected events: CompanyProfileCreated (v1 on company), CaseCreated (v1 on case),
        # 2x PersonLinkedToCompany (v2, v3 on company), 1x BeneficialOwnerAdded (v4 on company)
        # Total = 1 (Company) + 1 (Case) + 2 (Persons linked to Company) + 1 (BO linked to Company) = 5
        self.assertEqual(mock_save_event.call_count, 5)

        saved_events = [call_obj.args[0] for call_obj in mock_save_event.call_args_list]

        # 1. CompanyProfileCreatedEvent
        company_created_event = next(e for e in saved_events if isinstance(e, domain_events.CompanyProfileCreatedEvent))
        company_id_generated = company_created_event.aggregate_id
        self.assertIsNotNone(company_id_generated)
        self.assertEqual(company_created_event.payload.registered_name, company_profile.registered_name)
        self.assertEqual(company_created_event.version, 1) # First event for company aggregate

        # 2. CaseCreatedEvent
        case_created_event = next(e for e in saved_events if isinstance(e, domain_events.CaseCreatedEvent))
        self.assertEqual(case_created_event.aggregate_id, returned_case_id_str)
        self.assertEqual(case_created_event.payload.client_id, client_id)
        self.assertEqual(case_created_event.payload.traitement_type, "KYB")
        self.assertEqual(case_created_event.payload.company_id, company_id_generated)
        self.assertEqual(case_created_event.version, 1) # First event for case aggregate


        # 3. PersonLinkedToCompanyEvents (2 of them, check versions on company aggregate)
        person_linked_events = [e for e in saved_events if isinstance(e, domain_events.PersonLinkedToCompanyEvent)]
        self.assertEqual(len(person_linked_events), 2)

        director_event = next(e for e in person_linked_events if e.payload.firstname == "Director")
        self.assertEqual(director_event.aggregate_id, company_id_generated)
        self.assertEqual(director_event.payload.role_in_company, "Director")

        contact_event = next(e for e in person_linked_events if e.payload.firstname == "Contact")
        self.assertEqual(contact_event.aggregate_id, company_id_generated)
        self.assertEqual(contact_event.payload.role_in_company, "Primary Contact")

        # Check versions are sequential on company aggregate after CompanyProfileCreatedEvent
        # CompanyProfileCreatedEvent is v1. PersonsLinked should be v2, v3. BO should be v4.
        # This requires knowing the order they were created in the handler.
        # The handler does: Company, (Persons loop), (BOs loop)
        # So, Company (v1), Person1 (v2), Person2 (v3), BO1 (v4) on Company Aggregate.
        sorted_company_agg_events = sorted(
            [e for e in saved_events if e.aggregate_id == company_id_generated],
            key=lambda e: e.version
        )
        self.assertEqual(sorted_company_agg_events[0].version, 1) # CompanyProfileCreated
        self.assertIsInstance(sorted_company_agg_events[0], domain_events.CompanyProfileCreatedEvent)
        self.assertEqual(sorted_company_agg_events[1].version, 2) # First PersonLinked
        self.assertIsInstance(sorted_company_agg_events[1], domain_events.PersonLinkedToCompanyEvent)
        self.assertEqual(sorted_company_agg_events[2].version, 3) # Second PersonLinked
        self.assertIsInstance(sorted_company_agg_events[2], domain_events.PersonLinkedToCompanyEvent)


        # 4. BeneficialOwnerAddedEvent (version 4 on company aggregate)
        bo_added_event = next(e for e in saved_events if isinstance(e, domain_events.BeneficialOwnerAddedEvent))
        self.assertEqual(bo_added_event.aggregate_id, company_id_generated)
        self.assertEqual(bo_added_event.payload.person_details.firstname, "Beneficial")
        self.assertTrue(bo_added_event.payload.is_ubo)
        self.assertEqual(bo_added_event.version, 4) # Assuming it's the last event for the company aggregate


        self.assertEqual(mock_dispatch_projectors.call_count, mock_save_event.call_count)
        dispatched_events = [call_obj.args[0] for call_obj in mock_dispatch_projectors.call_args_list]
        for saved_event in saved_events:
            self.assertIn(saved_event, dispatched_events)

    @patch('case_management_service.core.commands.handlers.dispatch_event_to_projectors', new_callable=AsyncMock)
    @patch('case_management_service.core.commands.handlers.save_event', new_callable=AsyncMock)
    async def test_handle_create_case_command_kyc_only_person(self, mock_save_event, mock_dispatch_projectors):
        # Arrange - Test existing KYC path still works
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

        # Act
        returned_case_id_str = await command_handlers.handle_create_case_command(cmd)

        # Assert
        self.assertIsNotNone(returned_case_id_str)
        # Expected events for KYC with 1 person: CaseCreated (v1 on case), PersonAddedToCase (v2 on case)
        self.assertEqual(mock_save_event.call_count, 2)

        saved_events = [call_obj.args[0] for call_obj in mock_save_event.call_args_list]

        case_created_event = next(e for e in saved_events if isinstance(e, domain_events.CaseCreatedEvent))
        self.assertEqual(case_created_event.payload.traitement_type, "KYC")
        self.assertIsNone(case_created_event.payload.company_id)
        self.assertEqual(case_created_event.version, 1) # Case aggregate version 1

        person_added_event = next(e for e in saved_events if isinstance(e, domain_events.PersonAddedToCaseEvent))
        self.assertEqual(person_added_event.aggregate_id, returned_case_id_str)
        self.assertEqual(person_added_event.payload.firstname, "Simple")
        self.assertEqual(person_added_event.version, 2) # Case aggregate version 2

        self.assertEqual(mock_dispatch_projectors.call_count, 2)

# To run these tests (after all test files are created):
# Ensure PYTHONPATH includes the root directory of the project (e.g., parent of case_management_service)
# python -m unittest case_management_service.tests.core.commands.test_command_handlers
# Or using pytest: pytest case_management_service/tests/core/commands/test_command_handlers.py
