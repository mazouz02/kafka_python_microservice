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
from opentelemetry.trace.status import StatusCode # For checking span status

class TestEventProjectors(unittest.IsolatedAsyncioTestCase):

    # Test project_case_created (which updates read model)
    @patch('case_management_service.infrastructure.database.read_models.upsert_case_read_model', new_callable=AsyncMock)
    async def test_project_case_created(self, mock_upsert_case_rm):
        # Arrange
        case_id = str(uuid.uuid4())
        client_id = "client_efg"
        event_timestamp = datetime.datetime.utcnow()
        event_payload = domain_events.CaseCreatedEventPayload(
            client_id=client_id, case_type="KYC_LIGHT", case_version="1.0"
        )
        # Ensure the event_type is explicitly set if not defaulted by Pydantic model
        event = domain_events.CaseCreatedEvent(
            aggregate_id=case_id, payload=event_payload, version=1, timestamp=event_timestamp, event_type="CaseCreated"
        )

        # Act
        await event_projectors.project_case_created(event)

        # Assert
        mock_upsert_case_rm.assert_called_once()
        called_arg = mock_upsert_case_rm.call_args.args[0]
        self.assertIsInstance(called_arg, db_schemas.CaseManagementDB)
        self.assertEqual(called_arg.id, case_id)
        self.assertEqual(called_arg.client_id, client_id)
        self.assertEqual(called_arg.type, "KYC_LIGHT")
        self.assertEqual(called_arg.created_at, event_timestamp) # Check timestamps are passed
        self.assertEqual(called_arg.updated_at, event_timestamp)

    # Test project_person_added_to_case
    @patch('case_management_service.infrastructure.database.read_models.upsert_person_read_model', new_callable=AsyncMock)
    async def test_project_person_added_to_case(self, mock_upsert_person_rm):
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
        self.assertEqual(called_arg.case_id, case_id)
        self.assertEqual(called_arg.firstname, "Test")
        self.assertEqual(called_arg.created_at, event_timestamp)

    # Test the dispatch_event_to_projectors logic
    @patch('case_management_service.core.events.projectors.project_event_with_tracing_and_metrics', new_callable=AsyncMock)
    async def test_dispatch_event_to_projectors_known_events(self, mock_project_wrapper):
        # Arrange
        case_id = str(uuid.uuid4())
        cc_payload = domain_events.CaseCreatedEventPayload(client_id="c1", case_type="t1", case_version="v1")
        case_event = domain_events.CaseCreatedEvent(aggregate_id=case_id, payload=cc_payload, event_type="CaseCreated")

        pa_payload = domain_events.PersonAddedToCaseEventPayload(person_id=str(uuid.uuid4()), firstname="f", lastname="l")
        person_event = domain_events.PersonAddedToCaseEvent(aggregate_id=case_id, payload=pa_payload, event_type="PersonAddedToCase")

        # Use a concrete payload model for BaseEvent if its payload is BaseModel
        # For this test, using a simple dict that fits BaseModel's general expectation or a MagicMock
        unknown_event_payload_mock = MagicMock(spec=domain_events.BaseModel)
        unknown_event = domain_events.BaseEvent(
            aggregate_id=case_id,
            event_type="UnknownEvent",
            payload=unknown_event_payload_mock # Needs to be a BaseModel instance
        )

        # Act
        await event_projectors.dispatch_event_to_projectors(case_event)
        await event_projectors.dispatch_event_to_projectors(person_event)
        await event_projectors.dispatch_event_to_projectors(unknown_event)

        # Assert
        expected_calls = [
            call(event_projectors.project_case_created, case_event),
            call(event_projectors.project_person_added_to_case, person_event)
        ]
        mock_project_wrapper.assert_has_calls(expected_calls, any_order=True)
        self.assertEqual(mock_project_wrapper.call_count, 2)

    @patch('case_management_service.core.events.projectors.domain_events_processed_counter')
    @patch('case_management_service.core.events.projectors.domain_events_by_type_counter')
    @patch('case_management_service.core.events.projectors.tracer')
    async def test_project_event_with_tracing_and_metrics_wrapper_success(
        self, mock_tracer, mock_by_type_counter, mock_processed_counter
    ):
        # Arrange
        mock_projector_func = AsyncMock(name="mock_actual_projector")

        case_id = str(uuid.uuid4())
        event_payload = domain_events.CaseCreatedEventPayload(client_id="c1", case_type="t1", case_version="v1")
        event_to_project = domain_events.CaseCreatedEvent(aggregate_id=case_id, payload=event_payload, event_type="CaseCreated")

        mock_span = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

        # Act
        await event_projectors.project_event_with_tracing_and_metrics(mock_projector_func, event_to_project)

        # Assert
        mock_projector_func.assert_called_once_with(event_to_project)
        mock_tracer.start_as_current_span.assert_called_once()
        mock_span.set_attribute.assert_any_call("event.type", "CaseCreated")
        # Check for OK status
        mock_span.set_status.assert_called_once_with(Status(StatusCode.OK))

        mock_processed_counter.add.assert_called_once_with(1, {"projector.name": "mock_actual_projector"})
        mock_by_type_counter.add.assert_called_once_with(1, {"event.type": "CaseCreated", "projector.name": "mock_actual_projector"})

    @patch('case_management_service.core.events.projectors.tracer')
    async def test_project_event_with_tracing_and_metrics_wrapper_failure(self, mock_tracer):
        # Arrange
        mock_projector_func = AsyncMock(name="mock_failing_projector", side_effect=ValueError("Projection failed"))

        case_id = str(uuid.uuid4())
        event_payload = domain_events.CaseCreatedEventPayload(client_id="c1", case_type="t1", case_version="v1")
        event_to_project = domain_events.CaseCreatedEvent(aggregate_id=case_id, payload=event_payload, event_type="CaseCreated")

        mock_span = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = mock_span

        # Act & Assert
        with self.assertRaises(ValueError) as cm:
            await event_projectors.project_event_with_tracing_and_metrics(mock_projector_func, event_to_project)

        self.assertEqual(str(cm.exception), "Projection failed")
        mock_projector_func.assert_called_once_with(event_to_project)
        mock_span.record_exception.assert_called_once()
        # Check for ERROR status
        mock_span.set_status.assert_called_once_with(Status(StatusCode.ERROR, description="Projector Error: ValueError"))
