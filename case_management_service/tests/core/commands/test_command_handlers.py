# Unit Tests for Command Handlers (Refactored Structure)
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, call
import uuid

# Modules to test and their new locations
from case_management_service.core.commands import models as commands
from case_management_service.core.commands import handlers as command_handlers
from case_management_service.core.events import models as domain_events
from case_management_service.infrastructure.kafka.schemas import PersonData # Used by commands

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
            persons=[person1_data, person2_data]
        )

        # Act
        returned_case_id_str = await command_handlers.handle_create_case_command(cmd)

        # Assert
        self.assertIsNotNone(returned_case_id_str)
        try:
            uuid.UUID(returned_case_id_str)
        except ValueError:
            self.fail("Returned case_id is not a valid UUID string")

        # Verify save_event calls
        self.assertEqual(mock_save_event.call_count, 3) # 1 CaseCreated, 2 PersonAddedToCase

        # Check CaseCreatedEvent
        case_created_event_call = mock_save_event.call_args_list[0]
        saved_event_arg_case = case_created_event_call.args[0]
        self.assertIsInstance(saved_event_arg_case, domain_events.CaseCreatedEvent)
        self.assertEqual(saved_event_arg_case.aggregate_id, returned_case_id_str)
        self.assertEqual(saved_event_arg_case.payload.client_id, client_id)
        self.assertEqual(saved_event_arg_case.version, 1)

        # Check PersonAddedToCaseEvent for person1
        person1_event_call = mock_save_event.call_args_list[1]
        saved_event_arg_person1 = person1_event_call.args[0]
        self.assertIsInstance(saved_event_arg_person1, domain_events.PersonAddedToCaseEvent)
        self.assertEqual(saved_event_arg_person1.aggregate_id, returned_case_id_str)
        self.assertEqual(saved_event_arg_person1.payload.firstname, person1_data.firstname)
        self.assertEqual(saved_event_arg_person1.version, 2)

        # Check PersonAddedToCaseEvent for person2
        person2_event_call = mock_save_event.call_args_list[2]
        saved_event_arg_person2 = person2_event_call.args[0]
        self.assertIsInstance(saved_event_arg_person2, domain_events.PersonAddedToCaseEvent)
        self.assertEqual(saved_event_arg_person2.aggregate_id, returned_case_id_str)
        self.assertEqual(saved_event_arg_person2.payload.firstname, person2_data.firstname)
        self.assertEqual(saved_event_arg_person2.version, 3)

        # Verify dispatch_event_to_projectors calls
        self.assertEqual(mock_dispatch_projectors.call_count, 3)
        # Check that dispatch was called with the events that were saved
        dispatched_events = [call_obj.args[0] for call_obj in mock_dispatch_projectors.call_args_list]
        self.assertIn(saved_event_arg_case, dispatched_events)
        self.assertIn(saved_event_arg_person1, dispatched_events)
        self.assertIn(saved_event_arg_person2, dispatched_events)

# To run these tests (after all test files are created):
# Ensure PYTHONPATH includes the root directory of the project (e.g., parent of case_management_service)
# python -m unittest case_management_service.tests.core.commands.test_command_handlers
# Or using pytest: pytest case_management_service/tests/core/commands/test_command_handlers.py
