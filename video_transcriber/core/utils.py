import asyncio
import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def send_upload_notification(user_id: int, upload_id: int, status: str, message: str):
    """
    Send WebSocket notification to a user about upload status.
    
    Args:
        user_id: User ID to send notification to
        upload_id: Upload ID that the notification is about
        status: Upload status (pending, processing, completed, failed)
        message: Notification message to display
    """
    try:
        channel_layer = get_channel_layer()
        group_name = f"upload_notifications_{user_id}"
        
        notification_data = {
            "type": "upload_notification",
            "message": {
                "upload_id": upload_id,
                "status": status,
                "message": message,
                "icon": get_icon_for_status(status),
                "alert_type": get_alert_type_for_status(status),
            }
        }
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            notification_data
        )
        logger.info(f"Notification sent to user {user_id} for upload {upload_id}: {message}")
    except Exception as e:
        logger.error(f"Error sending notification to user {user_id}: {e}")


def get_icon_for_status(status: str) -> str:
    """Get Bootstrap icon class for status"""
    icons = {
        "pending": "hourglass-split",
        "processing": "arrow-repeat",
        "completed": "check-circle",
        "failed": "exclamation-triangle",
    }
    return icons.get(status, "info-circle")


def get_alert_type_for_status(status: str) -> str:
    """Get Bootstrap alert type for status"""
    alert_types = {
        "pending": "info",
        "processing": "info",
        "completed": "success",
        "failed": "danger",
    }
    return alert_types.get(status, "info")
