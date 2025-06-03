# Unit Tests for Database Functions (Refactored Structure)
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock, call
import datetime
import uuid

# Modules to test - new locations
from case_management_service.infrastructure.database import connection as db_connection
from case_management_service.infrastructure.database import event_store as db_event_store
from case_management_service.infrastructure.database import read_models as db_read_models
from case_management_service.infrastructure.database import raw_event_store as db_raw_event_store
from case_management_service.infrastructure.database import schemas as db_schemas
from case_management_service.core.events import models as domain_event_models # For domain event types
from case_management_service.app import config # For settings access if needed by db modules

# Helper to reset global db client in database.connection module
def reset_db_connection_module_state():
    db_connection.client = None
    db_connection.db = None

class TestDatabaseInfrastructure(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Ensure a clean state for db_connection globals before each test
        reset_db_connection_module_state()
        # Patch settings to use a test DB name if necessary, or ensure config is test-friendly
        # For now, assume default config is used by db_connection.py
        self.test_db_name = config.settings.DB_NAME # Use the configured DB name

    def tearDown(self):
        reset_db_connection_module_state()

    # --- Tests for infrastructure.database.connection ---
    @patch('case_management_service.infrastructure.database.connection.MongoClient')
    async def test_connect_to_mongo_success(self, mock_mongo_client_cls):
        mock_client_instance = MagicMock()
        # mock_client_instance.admin.command = AsyncMock(return_value={"ok": 1}) # MongoClient's command is not async by default
        mock_client_instance.admin.command.return_value = {"ok": 1} # Synchronous mock for standard PyMongo
        mock_mongo_client_cls.return_value = mock_client_instance

        db_connection.connect_to_mongo()

        mock_mongo_client_cls.assert_called_once_with(config.settings.MONGO_DETAILS) # Use settings via config
        mock_client_instance.admin.command.assert_called_once_with('ping')
        self.assertEqual(db_connection.db, mock_client_instance[self.test_db_name])

        db_instance = await db_connection.get_database() # Should return existing
        self.assertEqual(db_instance, mock_client_instance[self.test_db_name])
        # Ensure connect_to_mongo was not called again by get_database if already connected
        self.assertEqual(mock_mongo_client_cls.call_count, 1)


    @patch('case_management_service.infrastructure.database.connection.MongoClient', side_effect=ConnectionError("Mock Connection Error"))
    async def test_connect_to_mongo_failure(self, mock_mongo_client_cls):
        with self.assertRaisesRegex(ConnectionError, "Failed to connect to MongoDB: Mock Connection Error"):
            db_connection.connect_to_mongo()
        # Because connect_to_mongo failed and raised, db is still None.
        # get_database will try to connect again.
        with self.assertRaisesRegex(ConnectionError, "Failed to connect to MongoDB: Mock Connection Error"):
            await db_connection.get_database()


    # --- Tests for infrastructure.database.event_store ---
    @patch('case_management_service.infrastructure.database.event_store.get_database')
    async def test_save_event_new_aggregate(self, mock_get_db_for_event_store):
        mock_db_instance = AsyncMock()
        mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].find_one = AsyncMock(return_value=None)
        mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].insert_one = AsyncMock()
        mock_get_db_for_event_store.return_value = mock_db_instance

        agg_id = str(uuid.uuid4())
        event_payload_model = domain_event_models.CaseCreatedEventPayload(client_id="c1", case_type="t1", case_version="v1")
        event_to_save = domain_event_models.CaseCreatedEvent(
            aggregate_id=agg_id, payload=event_payload_model, version=1, event_type="CaseCreated"
        )

        returned_event = await db_event_store.save_event(event_to_save)

        mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].insert_one.assert_called_once()
        inserted_doc = mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].insert_one.call_args.args[0]
        self.assertIsInstance(inserted_doc, dict)
        self.assertEqual(inserted_doc["aggregate_id"], agg_id)
        self.assertEqual(inserted_doc["event_type"], "CaseCreated")
        self.assertEqual(inserted_doc["payload"]["client_id"], "c1")
        self.assertEqual(returned_event, event_to_save)

    @patch('case_management_service.infrastructure.database.event_store.get_database')
    async def test_get_events_for_aggregate_deserialization(self, mock_get_db_for_event_store):
        mock_db_instance = AsyncMock()
        agg_id = str(uuid.uuid4())
        person_id = str(uuid.uuid4())

        # Ensure stored metadata is a dict when creating StoredEventDB for test data
        meta_dict = domain_event_models.EventMetaData().model_dump()

        event_docs_from_db = [
            db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="CaseCreated", aggregate_id=agg_id, timestamp=datetime.datetime.utcnow(), version=1, payload={"client_id": "c1", "case_type": "t1", "case_version": "v1"}, metadata=meta_dict).model_dump(),
            db_schemas.StoredEventDB(event_id=str(uuid.uuid4()), event_type="PersonAddedToCase", aggregate_id=agg_id, timestamp=datetime.datetime.utcnow(), version=2, payload={"person_id": person_id, "firstname": "Test", "lastname": "User", "birthdate": "2000-01-01"}, metadata=meta_dict).model_dump()
        ]

        # Mocking async cursor
        mock_cursor = MagicMock()
        mock_cursor.__aiter__.return_value = iter(event_docs_from_db) # For async for loop

        mock_db_instance[db_event_store.EVENT_STORE_COLLECTION].find.return_value.sort.return_value = mock_cursor
        mock_get_db_for_event_store.return_value = mock_db_instance

        retrieved_events = await db_event_store.get_events_for_aggregate(agg_id)

        self.assertEqual(len(retrieved_events), 2)
        self.assertIsInstance(retrieved_events[0], domain_event_models.CaseCreatedEvent)
        self.assertIsInstance(retrieved_events[0].payload, domain_event_models.CaseCreatedEventPayload)
        self.assertEqual(retrieved_events[0].payload.client_id, "c1")
        self.assertIsInstance(retrieved_events[1], domain_event_models.PersonAddedToCaseEvent)
        self.assertIsInstance(retrieved_events[1].payload, domain_event_models.PersonAddedToCaseEventPayload)
        self.assertEqual(retrieved_events[1].payload.firstname, "Test")

    # --- Tests for infrastructure.database.read_models ---
    @patch('case_management_service.infrastructure.database.read_models.get_database')
    async def test_upsert_case_read_model(self, mock_get_db_for_read_models):
        mock_db_instance = AsyncMock()
        mock_db_instance.cases.replace_one = AsyncMock()
        mock_get_db_for_read_models.return_value = mock_db_instance

        case_data = db_schemas.CaseManagementDB(id="case001", client_id="client001", version="1", type="T")
        await db_read_models.upsert_case_read_model(case_data)

        mock_db_instance.cases.replace_one.assert_called_once()
        filter_arg = mock_db_instance.cases.replace_one.call_args.args[0]
        doc_arg = mock_db_instance.cases.replace_one.call_args.args[1]
        upsert_flag = mock_db_instance.cases.replace_one.call_args.kwargs.get('upsert')
        self.assertEqual(filter_arg, {"id": "case001"})
        self.assertEqual(doc_arg["client_id"], "client001")
        self.assertTrue(upsert_flag)

    @patch('case_management_service.infrastructure.database.read_models.get_database')
    async def test_get_case_by_id_from_read_model(self, mock_get_db_for_read_models):
        mock_db_instance = AsyncMock()
        now = datetime.datetime.utcnow()
        case_doc_from_db = {"id": "foundcase", "client_id": "c1", "version": "v1", "type": "t1",
                            "created_at": now, "updated_at": now}
        mock_db_instance.cases.find_one = AsyncMock(return_value=case_doc_from_db)
        mock_get_db_for_read_models.return_value = mock_db_instance

        result = await db_read_models.get_case_by_id_from_read_model("foundcase")
        self.assertIsInstance(result, db_schemas.CaseManagementDB)
        self.assertEqual(result.id, "foundcase")

        mock_db_instance.cases.find_one = AsyncMock(return_value=None)
        result_none = await db_read_models.get_case_by_id_from_read_model("notfoundcase")
        self.assertIsNone(result_none)

    # --- Tests for infrastructure.database.raw_event_store ---
    @patch('case_management_service.infrastructure.database.raw_event_store.get_database')
    async def test_add_raw_event_to_store(self, mock_get_db_for_raw_store):
        mock_db_instance = AsyncMock()
        mock_db_instance.raw_events.insert_one = AsyncMock()
        mock_get_db_for_raw_store.return_value = mock_db_instance

        raw_payload = {"key": "value"}
        event_type = "RAW_TEST_EVENT"

        returned_event = await db_raw_event_store.add_raw_event_to_store(raw_payload, event_type)

        self.assertIsInstance(returned_event, db_schemas.RawEventDB)
        self.assertEqual(returned_event.payload, raw_payload)
        self.assertEqual(returned_event.event_type, event_type)
        mock_db_instance.raw_events.insert_one.assert_called_once()
        inserted_doc = mock_db_instance.raw_events.insert_one.call_args.args[0]
        self.assertEqual(inserted_doc["payload"], raw_payload)
