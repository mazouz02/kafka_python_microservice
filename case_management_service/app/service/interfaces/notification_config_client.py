from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

# Forward declaration for NotificationRule if it's a Pydantic model defined elsewhere
# to avoid circular imports. If it's simple enough, define here or import directly.
# For now, assuming it's defined in infrastructure.config_service_client
# and we might need to move its definition or use a more generic type hint here.
# Let's use a forward reference string for now if NotificationRule is complex.
class NotificationRule: # Placeholder if not imported
    rule_id: str
    is_active: bool
    notification_type: str
    template_id: str
    language_code: str


class AbstractNotificationConfigClient(ABC):
    @abstractmethod
    async def get_config(
        self,
        event_trigger: str,
        context: Dict[str, Any]
    ) -> Optional[NotificationRule]:
        """
        Retrieves notification configuration based on an event trigger and context.

        Args:
            event_trigger: A string identifying the event that triggers the notification.
            context: A dictionary containing contextual data for rule evaluation.

        Returns:
            A NotificationRule object if a matching active rule is found, otherwise None.
        """
        pass
