import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


class UploadNotificationConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for upload status notifications"""

    async def connect(self):
        """Connect handler - add user to notification group"""
        if self.scope["user"].is_authenticated:
            self.user = self.scope["user"]
            self.group_name = f"upload_notifications_{self.user.id}"

            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )
            await self.accept()
            logger.info(f"User {self.user.username} connected to notifications")
        else:
            await self.close()

    async def disconnect(self, close_code):
        """Disconnect handler - remove user from group"""
        if self.scope["user"].is_authenticated:
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
            logger.info(f"User {self.scope['user'].username} disconnected from notifications")

    async def upload_notification(self, event):
        """Receive upload notification and send to WebSocket"""
        await self.send(text_data=json.dumps(event["message"]))
