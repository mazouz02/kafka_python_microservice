# case_management_service/app/__init__.py
import logging

# For now, let's keep it simple
logger = logging.getLogger(__name__)
logger.info("Case Management App Initialized")

# Make components easily importable if desired (optional)
# from . import commands
# from . import domain_events
# from . import command_handlers
# from . import kafka_models
# from .database import get_database, save_event, add_raw_event # etc.
# from .kafka_consumer import consume_events
# from .main import app as fastapi_app
