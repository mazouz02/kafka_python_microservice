# MongoDB Client Factory and Utilities
import logging
from typing import Optional
from pymongo import MongoClient
from pymongo.database import Database

# Assuming infra.config.settings is the source of MONGO_URI and DB_NAME
from ..config import settings # Relative import from infra.config

logger = logging.getLogger(__name__)

_mongo_client: Optional[MongoClient] = None
_mongo_db: Optional[Database] = None

def get_mongo_client() -> MongoClient:
    """Returns a MongoClient instance, initializing if necessary."""
    global _mongo_client
    if _mongo_client is None:
        if not settings.MONGO_URI: # MONGO_URI needs to be added to AppSettings in config.py
            logger.error("settings.MONGO_URI not configured. Cannot create MongoDB client.")
            raise ValueError("settings.MONGO_URI is not set in application settings.")
        try:
            logger.info(f"Initializing MongoDB client for URI: {settings.MONGO_URI}")
            _mongo_client = MongoClient(settings.MONGO_URI)
            # Optional: Ping server to confirm connection early
            # _mongo_client.admin.command('ping')
            # logger.info("MongoDB client initialized and ping successful.")
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB client: {e}", exc_info=True)
            _mongo_client = None
            raise
    return _mongo_client

def get_mongo_database() -> Database:
    """Returns a MongoDB Database instance, initializing client and DB if necessary."""
    global _mongo_db
    client = get_mongo_client()
    if _mongo_db is None:
        if not settings.DB_NAME: # DB_NAME needs to be added to AppSettings in config.py
            logger.error("settings.DB_NAME not configured. Cannot get MongoDB database.")
            raise ValueError("settings.DB_NAME is not set in application settings.")
        logger.info(f"Getting MongoDB database: {settings.DB_NAME}")
        _mongo_db = client[settings.DB_NAME]
    return _mongo_db

def close_mongo_client():
    """Closes the MongoDB client connection if it's open."""
    global _mongo_client, _mongo_db
    if _mongo_client:
        logger.info("Closing MongoDB client connection.")
        _mongo_client.close()
        _mongo_client = None
        _mongo_db = None

# Example FastAPI dependency provider for a DB session (can be added to infra/di.py)
# async def db_session_dependency() -> Database:
#     try:
#         db = get_mongo_database()
#         # Optional: Ping DB at start of session if needed by specific logic
#         # await db.command('ping') # db.command is async with Motor, sync with PyMongo direct.
#         # For PyMongo, direct operations are synchronous.
#         # This template doesn't install pymongo/motor by default.
#         # If using Motor, get_mongo_database would return an AsyncIOMotorDatabase.
#         return db
#     except Exception as e:
#         logger.error(f"Failed to provide DB session: {e}", exc_info=True)
#         raise HTTPException(status_code=503, detail="Database not available")

# For this template, we won't add pymongo/motor yet.
# This mongo.py is a placeholder for connection logic.
# The /health endpoint will not use this initially to keep template minimal.
