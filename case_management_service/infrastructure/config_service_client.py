# Client for interacting with an external Configuration Microservice
import logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, HttpUrl # HttpUrl not directly used in this version but good for future
import httpx # For async HTTP calls

# Import settings for the service URL
from case_management_service.app.config import settings

logger = logging.getLogger(__name__)

# Pydantic model for the expected rule structure from the config service
class NotificationRule(BaseModel):
    rule_id: str
    is_active: bool = True
    notification_type: str # e.g., EMAIL_WELCOME_KYC
    template_id: Optional[str] = None
    language_code: Optional[str] = None
    # Add any other fields the config service might provide for a rule
    # E.g., priority, channel_preference (EMAIL, SMS)

async def get_notification_config(
    event_trigger: str, # e.g., "CASE_CREATED_KYC_INDIVIDUAL"
    context: Dict[str, Any] # e.g., { "case_type": "STANDARD", "client_jurisdiction": "US" }
) -> Optional[NotificationRule]:
    """
    Fetches notification configuration for a given trigger and context.
    Returns a NotificationRule if a matching active rule is found, otherwise None.
    """
    if not settings.CONFIG_SERVICE_URL:
        logger.warning("CONFIG_SERVICE_URL not set. Cannot fetch notification rules. Returning None.")
        # For development, could return a default/hardcoded rule if desired
        # return NotificationRule(rule_id="dev_default", notification_type="EMAIL_WELCOME_KYC_DEV", template_id="dev_welcome_tpl")
        return None

    # Construct the request payload or query parameters for the config service
    # This depends on the config service's API contract
    request_url = f"{settings.CONFIG_SERVICE_URL}/rules/match" # Example endpoint
    payload = {
        "event_trigger": event_trigger,
        "context": context
    }

    logger.debug(f"Querying config service for notification rule: {request_url} with payload {payload}")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client: # 5 second timeout
            response = await client.post(request_url, json=payload)
            response.raise_for_status() # Raise an exception for 4xx/5xx status codes

            rule_data_list = response.json() # Assuming service might return a list of rules
            if rule_data_list:
                # If it returns a list, take the first active rule or apply priority logic.
                # For simplicity, taking the first active one.
                for rule_data in rule_data_list:
                    if isinstance(rule_data, dict): # Ensure it's a dict before parsing
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
    except Exception as e: # Includes Pydantic ValidationError if response structure is wrong
        logger.error(f"Error parsing notification rule from config service or other unexpected error: {e}", exc_info=True)
        return None
