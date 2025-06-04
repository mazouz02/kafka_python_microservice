# Unit Tests for Event Projectors (Refactored Structure)
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock, call
import datetime
import uuid

# Modules to test and their new locations
from case_management_service.core.events import models as domain_events
from case_management_service.core.events import projectors as event_projectors
from case_management_service.infrastructure.database import schemas as db_schemas # Read models for verification
# AddressData is available via domain_events (imported from kafka.schemas there)
from opentelemetry.trace.status import StatusCode, Status # For checking span status

class TestEventProjectors(unittest.IsolatedAsyncioTestCase):

    # --- Tests for New Projectors ---

    @patch('case_management_service.infrastructure.database.read_models.upsert_company_read_model', new_callable=AsyncMock)
    async def test_project_company_profile_created(self, mock_upsert_company_rm):
        # Arrange
        company_id = str(uuid.uuid4())
        event_timestamp = datetime.datetime.utcnow()
        addr_data = domain_events.AddressData(street="Main St 123", city="ACity", country="US", postal_code="12345")
        payload = domain_events.CompanyProfileCreatedEventPayload(
            registered_name="Test Ltd",
            registration_number="REG123",
            country_of_incorporation="US",
            registered_address=addr_data
        )
        event = domain_events.CompanyProfileCreatedEvent(
            aggregate_id=company_id, payload=payload, timestamp=event_timestamp, version=1, event_type="CompanyProfileCreated"
        )

        # Act
        await event_projectors.project_company_profile_created(event)

        # Assert
        mock_upsert_company_rm.assert_called_once()
        called_arg = mock_upsert_company_rm.call_args.args[0]
        self.assertIsInstance(called_arg, db_schemas.CompanyProfileDB)
        self.assertEqual(called_arg.id, company_id)
        self.assertEqual(called_arg.registered_name, "Test Ltd")
        self.assertEqual(called_arg.registered_address.street, "Main St 123")
        self.assertEqual(called_arg.created_at, event_timestamp)
        self.assertEqual(called_arg.updated_at, event_timestamp)


    @patch('case_management_service.infrastructure.database.read_models.upsert_beneficial_owner_read_model', new_callable=AsyncMock)
    async def test_project_beneficial_owner_added(self, mock_upsert_bo_rm):
        # Arrange
        company_id = str(uuid.uuid4())
        bo_id = str(uuid.uuid4())
        event_timestamp = datetime.datetime.utcnow()
        bo_person_details = domain_events.PersonData(firstname="BO", lastname="One", birthdate="1980-01-01")
        payload = domain_events.BeneficialOwnerAddedEventPayload(
            beneficial_owner_id=bo_id,
            person_details=bo_person_details,
            ownership_percentage=75.0,
            is_ubo=True,
            types_of_control=["Voting Rights"]
        )
        event = domain_events.BeneficialOwnerAddedEvent(
            aggregate_id=company_id, payload=payload, timestamp=event_timestamp, version=2, event_type="BeneficialOwnerAdded"
        )

        # Act
        await event_projectors.project_beneficial_owner_added(event)

        # Assert
        mock_upsert_bo_rm.assert_called_once()
        called_arg = mock_upsert_bo_rm.call_args.args[0]
        self.assertIsInstance(called_arg, db_schemas.BeneficialOwnerDB)
        self.assertEqual(called_arg.id, bo_id)
        self.assertEqual(called_arg.company_id, company_id)
        self.assertEqual(called_arg.firstname, "BO")
        self.assertEqual(called_arg.is_ubo, True)
        self.assertEqual(called_arg.ownership_percentage, 75.0)
        self.assertEqual(called_arg.types_of_control, ["Voting Rights"])
        self.assertEqual(called_arg.created_at, event_timestamp)

    @patch('case_management_service.infrastructure.database.read_models.upsert_person_read_model', new_callable=AsyncMock)
    async def test_project_person_linked_to_company(self, mock_upsert_person_rm):
        # Arrange
        company_id = str(uuid.uuid4())
        person_id_linked = str(uuid.uuid4())
        event_timestamp = datetime.datetime.utcnow()
        payload = domain_events.PersonLinkedToCompanyEventPayload(
            person_id=person_id_linked,
            firstname="Director",
            lastname="Smith",
            birthdate="1975-05-15",
            role_in_company="Director"
        )
        event = domain_events.PersonLinkedToCompanyEvent(
            aggregate_id=company_id, payload=payload, timestamp=event_timestamp, version=3, event_type="PersonLinkedToCompany"
        )

        # Act
        await event_projectors.project_person_linked_to_company(event)

        # Assert
        mock_upsert_person_rm.assert_called_once()
        called_arg = mock_upsert_person_rm.call_args.args[0]
        self.assertIsInstance(called_arg, db_schemas.PersonDB)
        self.assertEqual(called_arg.id, person_id_linked)
        self.assertEqual(called_arg.company_id, company_id)
        self.assertEqual(called_arg.firstname, "Director")
        self.assertEqual(called_arg.role_in_company, "Director")
        self.assertEqual(called_arg.created_at, event_timestamp)

    # --- Modify existing tests ---

    @patch('case_management_service.infrastructure.database.read_models.upsert_case_read_model', new_callable=AsyncMock)
    async def test_project_case_created_with_kyb_link(self, mock_upsert_case_rm): # Renamed from original
        # Arrange
        case_id = str(uuid.uuid4())
        company_id_linked = str(uuid.uuid4())
        event_timestamp = datetime.datetime.utcnow()
        payload = domain_events.CaseCreatedEventPayload(
            client_id="client_xyz", case_type="KYB_CASE", case_version="1.0",
            traitement_type="KYB", company_id=company_id_linked
        )
        event = domain_events.CaseCreatedEvent(
            aggregate_id=case_id, payload=payload, timestamp=event_timestamp, version=1, event_type="CaseCreated"
        )
        # Act
        await event_projectors.project_case_created(event)
        # Assert
        mock_upsert_case_rm.assert_called_once()
        called_arg = mock_upsert_case_rm.call_args.args[0]
        self.assertIsInstance(called_arg, db_schemas.CaseManagementDB)
        self.assertEqual(called_arg.id, case_id)
        self.assertEqual(called_arg.traitement_type, "KYB")
        self.assertEqual(called_arg.company_id, company_id_linked)
        self.assertEqual(called_arg.status, "OPEN")

    @patch('case_management_service.infrastructure.database.read_models.upsert_person_read_model', new_callable=AsyncMock)
    async def test_project_person_added_to_case_kyc(self, mock_upsert_person_rm): # Clarified name for KYC
        # Arrange
        case_id = str(uuid.uuid4())
        person_id = str(uuid.uuid4())
        event_timestamp = datetime.datetime.utcnow()
        event_payload = domain_events.PersonAddedToCaseEventPayload(
            person_id=person_id, firstname="Test", lastname="Person", birthdate="2000-01-01"
        )
        event = domain_events.PersonAddedToCaseEvent(
            aggregate_id=case_id, payload=event_payload, version=2, timestamp=event_timestamp, event_type="PersonAddedToCase"
        )
        # Act
        await event_projectors.project_person_added_to_case(event)
        # Assert
        mock_upsert_person_rm.assert_called_once()
        called_arg = mock_upsert_person_rm.call_args.args[0]
        self.assertIsInstance(called_arg, db_schemas.PersonDB)
        self.assertEqual(called_arg.id, person_id)
        self.assertEqual(called_arg.case_id, case_id) # Check it's linked to case_id
        self.assertIsNone(called_arg.company_id) # Should be None for this event type
        self.assertIsNone(called_arg.role_in_company) # Should be None

    @patch('case_management_service.core.events.projectors.project_event_with_tracing_and_metrics', new_callable=AsyncMock)
    async def test_dispatch_event_to_projectors_all_event_types(self, mock_project_wrapper):
        # Arrange
        case_id = str(uuid.uuid4())
        company_id = str(uuid.uuid4())
        addr_data = domain_events.AddressData(street="s", city="c", country="US", postal_code="pc")

        events_to_test = [
            domain_events.CaseCreatedEvent(aggregate_id=case_id, payload=domain_events.CaseCreatedEventPayload(client_id="c1", case_type="t1", case_version="v1", traitement_type="KYC"), event_type="CaseCreated"),
            domain_events.CompanyProfileCreatedEvent(aggregate_id=company_id, payload=domain_events.CompanyProfileCreatedEventPayload(registered_name="Comp", registration_number="R1", country_of_incorporation="US", registered_address=addr_data), event_type="CompanyProfileCreated"),
            domain_events.BeneficialOwnerAddedEvent(aggregate_id=company_id, payload=domain_events.BeneficialOwnerAddedEventPayload(beneficial_owner_id=str(uuid.uuid4()), person_details=domain_events.PersonData(firstname="bo", lastname="p")), event_type="BeneficialOwnerAdded"),
            domain_events.PersonLinkedToCompanyEvent(aggregate_id=company_id, payload=domain_events.PersonLinkedToCompanyEventPayload(person_id=str(uuid.uuid4()), firstname="pf", lastname="pl", role_in_company="Dir"), event_type="PersonLinkedToCompany"),
            domain_events.PersonAddedToCaseEvent(aggregate_id=case_id, payload=domain_events.PersonAddedToCaseEventPayload(person_id=str(uuid.uuid4()), firstname="pac_f", lastname="pac_l"), event_type="PersonAddedToCase")
        ]

        # Act
        for event in events_to_test:
            await event_projectors.dispatch_event_to_projectors(event)

        # Assert
        expected_projector_map = {
            "CaseCreated": event_projectors.project_case_created,
            "CompanyProfileCreated": event_projectors.project_company_profile_created,
            "BeneficialOwnerAdded": event_projectors.project_beneficial_owner_added,
            "PersonLinkedToCompany": event_projectors.project_person_linked_to_company,
            "PersonAddedToCase": event_projectors.project_person_added_to_case
        }
        expected_calls = [call(expected_projector_map[event.event_type], event) for event in events_to_test]

        mock_project_wrapper.assert_has_calls(expected_calls, any_order=False) # Order of dispatch matters
        self.assertEqual(mock_project_wrapper.call_count, len(events_to_test))

    @patch('case_management_service.core.events.projectors.domain_events_processed_counter')
    @patch('case_management_service.core.events.projectors.domain_events_by_type_counter')
    @patch('case_management_service.core.events.projectors.tracer')
    async def test_project_event_with_tracing_and_metrics_wrapper_success(
        self, mock_tracer, mock_by_type_counter, mock_processed_counter
    ):
        mock_projector_func = AsyncMock(name="mock_actual_projector")
        event_payload = domain_events.CaseCreatedEventPayload(client_id="c1", case_type="t1", case_version="v1", traitement_type="KYC")
        event_to_project = domain_events.CaseCreatedEvent(aggregate_id=str(uuid.uuid4()), payload=event_payload, event_type="CaseCreated")
        mock_span = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

        await event_projectors.project_event_with_tracing_and_metrics(mock_projector_func, event_to_project)

        mock_projector_func.assert_called_once_with(event_to_project)
        mock_span.set_status.assert_called_once_with(Status(StatusCode.OK))
        mock_processed_counter.add.assert_called_once_with(1, {"projector.name": "mock_actual_projector"})
        mock_by_type_counter.add.assert_called_once_with(1, {"event.type": "CaseCreated", "projector.name": "mock_actual_projector"})

    @patch('case_management_service.core.events.projectors.tracer')
    async def test_project_event_with_tracing_and_metrics_wrapper_failure(self, mock_tracer):
        mock_projector_func = AsyncMock(name="mock_failing_projector", side_effect=ValueError("Projection failed"))
        event_payload = domain_events.CaseCreatedEventPayload(client_id="c1", case_type="t1", case_version="v1", traitement_type="KYC")
        event_to_project = domain_events.CaseCreatedEvent(aggregate_id=str(uuid.uuid4()), payload=event_payload, event_type="CaseCreated")
        mock_span = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

        with self.assertRaisesRegex(ValueError, "Projection failed"):
            await event_projectors.project_event_with_tracing_and_metrics(mock_projector_func, event_to_project)

        mock_projector_func.assert_called_once_with(event_to_project)
        mock_span.record_exception.assert_called_once()
        mock_span.set_status.assert_called_once_with(Status(StatusCode.ERROR, description="Projector Error: ValueError"))
