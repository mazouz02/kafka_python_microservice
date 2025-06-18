# Client for interacting with an external Configuration Microservice
import logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
import httpx # For async HTTP calls
from fastapi import Depends # Added for Depends

# Import settings for the service URL
from case_management_service.app.config import settings
# Import the abstract class
from case_management_service.app.service.interfaces.notification_config_client import AbstractNotificationConfigClient, NotificationRule
# Import for http client dependency
from case_management_service.app.dependencies.http_client import get_http_client # Changed import path

logger = logging.getLogger(__name__)

# Pydantic model for the expected rule structure from the config service
# Moved NotificationRule to app.service.interfaces.notification_config_client to avoid circular dependency
# if it were used by other services. For now, it's fine here if only this client uses it.
# To make it available for the interface, it should be in a shared location or the interface
# should use a generic Dict or a more abstract representation.
# For this refactor, assuming NotificationRule definition is usable by the interface.
# If NotificationRule was already defined in the interface file, remove or comment out this one.
# class NotificationRule(BaseModel):
#     rule_id: str
#     is_active: bool = True
#     notification_type: str # e.g., EMAIL_WELCOME_KYC
#     template_id: Optional[str] = None
#     language_code: Optional[str] = None


class NotificationConfigServiceClient(AbstractNotificationConfigClient):
    def __init__(self, http_client: httpx.AsyncClient):
        self.http_client = http_client

    async def get_config(
        self,
        event_trigger: str,
        context: Dict[str, Any]
    ) -> Optional[NotificationRule]:
        if not settings.CONFIG_SERVICE_URL:
            logger.warning("CONFIG_SERVICE_URL not set. Cannot fetch notification rules. Returning None.")
            return None

        request_url = f"{settings.CONFIG_SERVICE_URL}/rules/match"
        payload = {
            "event_trigger": event_trigger,
            "context": context
        }
        logger.debug(f"Querying config service for notification rule: {request_url} with payload {payload}")

        try:
            response = await self.http_client.post(request_url, json=payload)
            response.raise_for_status()

            rule_data_list = response.json()
            if rule_data_list:
                for rule_data in rule_data_list:
                    if isinstance(rule_data, dict):
                        parsed_rule = NotificationRule(**rule_data)
                        if parsed_rule.is_active:
                            logger.info(f"Active notification rule found: {parsed_rule.rule_id} for trigger {event_trigger}")
                            return parsed_rule
                        else:
                            logger.info(f"Matching notification rule found ({parsed_rule.rule_id}) but it is inactive for trigger {event_trigger}.")
                logger.info(f"No *active* notification rule found in the response for trigger {event_trigger}.")
                return None
            else:
                logger.info(f"No matching notification rule found (empty response) for trigger {event_trigger}.")
                return None
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error calling config service: {e.response.status_code} - {e.response.text}", exc_info=True)
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error calling config service: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Error parsing notification rule from config service or other unexpected error: {e}", exc_info=True)
            return None

# DI provider for NotificationConfigServiceClient
def get_notification_config_client(
    http_client: httpx.AsyncClient = Depends(get_http_client) # Depends on get_http_client from main
) -> AbstractNotificationConfigClient:
    return NotificationConfigServiceClient(http_client=http_client)

# Keep the old function for now, marking as deprecated or to be removed.
# Or remove it if confident all call sites will be updated.
async def get_notification_config(
    event_trigger: str,
    context: Dict[str, Any]
) -> Optional[NotificationRule]:
    """
    DEPRECATED: Use dependency injection with NotificationConfigServiceClient instead.
    Fetches notification configuration for a given trigger and context.
    Returns a NotificationRule if a matching active rule is found, otherwise None.
    """
    logger.warning("get_notification_config is deprecated. Use injected NotificationConfigServiceClient.")
    # This function now needs an httpx.AsyncClient to work, or it has to create one ad-hoc.
    # For simplicity during refactor, it can create one, but this is inefficient.
    async with httpx.AsyncClient(timeout=5.0) as client:
        # Temporary NotificationConfigServiceClient for the old function
        temp_config_client = NotificationConfigServiceClient(http_client=client)
        return await temp_config_client.get_config(event_trigger, context)

