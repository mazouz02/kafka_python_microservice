from case_management_service.app.config import settings # Added import
import logging
import os # os is no longer needed for MONGO_DETAILS
from pymongo import MongoClient
from typing import Optional

logger = logging.getLogger(__name__)

# MONGO_DETAILS is now sourced from settings
# Global client and db variables, managed by connect/close functions
client: Optional[MongoClient] = None
db = None # Will hold the database instance

def connect_to_mongo():
    global client, db
    if client and db:
        logger.info("MongoDB connection already established.")
        return

    try:
        logger.info(f"Attempting to connect to MongoDB at {settings.MONGO_DETAILS}...")
        client = MongoClient(settings.MONGO_DETAILS)
        # Verify connection by pinging the admin database
        client.admin.command('ping')
        # Use DB_NAME from settings
        db = client[settings.DB_NAME]
        logger.info(f"Successfully connected to MongoDB and database '{settings.DB_NAME}' is set.")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}", exc_info=True)
        client = None
        db = None
        raise ConnectionError(f"Failed to connect to MongoDB: {e}")

def close_mongo_connection():
    global client, db
    if client:
        client.close()
        client = None
        db = None
        logger.info("MongoDB connection closed.")

async def get_db(): # Renamed and modified to be a generator
    global db, client
    if db is None:
        logger.warning("Database not initialized. Attempting to connect via get_db().")
        connect_to_mongo() # Ensure connection is attempted if not already up

    if db is None:
        # This case should ideally not be reached if connect_to_mongo succeeds
        # or if startup events correctly establish the connection.
        logger.error("Failed to get database instance in get_db.")
        raise ConnectionError("Database client is not available. Connection might have failed or was not established.")

    try:
        yield db
    finally:
        # In this specific global connection model, we don't close the connection here
        # as it's managed by application startup/shutdown events.
        # If using a per-request connection model, cleanup would happen here.
        pass
