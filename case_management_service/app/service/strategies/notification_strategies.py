import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase

from case_management_service.app.service.commands.models import CreateCaseCommand
from case_management_service.app.service.events import models as domain_event_models
from case_management_service.app.service.interfaces.notification_config_client import AbstractNotificationConfigClient

logger = logging.getLogger(__name__)

class NotificationStrategy(ABC):
    @abstractmethod
    async def prepare_notification(
        self,
        command: CreateCaseCommand,
        case_id: str,
        # config_service_context: Dict[str, Any], # This can be constructed within the strategy
        config_client: AbstractNotificationConfigClient,
        db: AsyncIOMotorDatabase # db might be needed for more complex strategies later
    ) -> Optional[domain_event_models.NotificationRequiredEventPayload]:
        """
        Prepares the payload for a NotificationRequiredEvent based on the command and configuration.

        Args:
            command: The input CreateCaseCommand.
            case_id: The generated ID for the new case.
            config_client: The client to fetch notification rules.
            db: Database instance, in case strategies need to query for more data.

        Returns:
            A NotificationRequiredEventPayload if a notification should be sent, otherwise None.
        """
        pass

class StandardNotificationStrategy(NotificationStrategy):
    async def prepare_notification(
        self,
        command: CreateCaseCommand,
        case_id: str,
        config_client: AbstractNotificationConfigClient,
        db: AsyncIOMotorDatabase # Included for interface consistency, not used in this basic version
    ) -> Optional[domain_event_models.NotificationRequiredEventPayload]:

        config_service_event_trigger = f"CASE_CREATED_{command.traitement_type}_{command.case_type}".upper().replace("-", "_")
        config_service_context: Dict[str, Any] = {
            "case_id": case_id,
            "client_id": command.client_id,
            "traitement_type": command.traitement_type,
            "case_type": command.case_type,
        }

        logger.debug(f"StandardNotificationStrategy: Fetching notification rule for trigger '{config_service_event_trigger}' with context {config_service_context}")
        notification_rule = await config_client.get_config(config_service_event_trigger, config_service_context)

        primary_person_for_notification = command.persons[0] if command.persons else None
        recipient_details_for_notification: Dict[str, Any] = {
            "case_id": case_id,
            "client_id": command.client_id
        }
        if primary_person_for_notification:
            recipient_details_for_notification["primary_contact_name"] = f"{primary_person_for_notification.firstname} {primary_person_for_notification.lastname}"
            # In a real system, you'd fetch/pass actual contact details like email/phone from command or db.

        if notification_rule and notification_rule.is_active:
            logger.info(f"StandardNotificationStrategy: Active notification rule '{notification_rule.rule_id}' matched for case {case_id}.")

            # Construct context data for the notification template itself
            template_context_data = {
                "case_id": case_id,
                "client_name": f"{primary_person_for_notification.firstname if primary_person_for_notification else 'N/A'}",
                "case_type": command.case_type,
                "traitement_type": command.traitement_type,
                # Add any other details from `command` or `notification_rule.additional_context` if available
            }

            return domain_event_models.NotificationRequiredEventPayload(
                notification_type=notification_rule.notification_type,
                recipient_details=recipient_details_for_notification,
                template_id=notification_rule.template_id,
                language_code=notification_rule.language_code,
                context_data=template_context_data
            )
        elif notification_rule: # Rule exists but is_active is False
            logger.info(f"StandardNotificationStrategy: Matching notification rule ({notification_rule.rule_id}) found for case {case_id} but it is inactive.")
            return None
        else: # Rule is None (no match or config service issue)
            logger.info(f"StandardNotificationStrategy: No notification rule found or config service unavailable for case {case_id} (trigger: {config_service_event_trigger}).")
            return None

class NoNotificationStrategy(NotificationStrategy):
    async def prepare_notification(
        self,
        command: CreateCaseCommand,
        case_id: str,
        config_client: AbstractNotificationConfigClient,
        db: AsyncIOMotorDatabase
    ) -> Optional[domain_event_models.NotificationRequiredEventPayload]:
        logger.info(f"NoNotificationStrategy: Notification explicitly disabled for case {case_id}.")
        return None

# Factory function (optional, can also instantiate directly in handler if logic is simple)
def get_notification_strategy(command: CreateCaseCommand) -> NotificationStrategy:
    # Example: Could base strategy on command.case_type or other flags
    # if command.case_type == "INTERNAL_TEST_CASE_NO_NOTIFICATIONS":
    #     return NoNotificationStrategy()
    return StandardNotificationStrategy()
