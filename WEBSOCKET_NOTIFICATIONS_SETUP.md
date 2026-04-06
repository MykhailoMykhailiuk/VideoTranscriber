# Django Channels WebSocket Notifications Setup

## Overview
Real-time WebSocket notifications have been implemented to show upload status changes (Pending, Processing, Completed, Failed) to users in real-time.

## Changes Made

### 1. **Dependencies Added** (`pyproject.toml`)
- `channels = "^4.0.0"` - Django Channels framework
- `channels-redis = "^4.1.0"` - Redis backend for channel layers
- `daphne = "^4.0.0"` - ASGI server for production use

### 2. **Django Configuration** (`settings.py`)
- Added `'daphne'` to INSTALLED_APPS (must be first)
- Configured CHANNEL_LAYERS to use Redis backend
- Set ASGI_APPLICATION to use Channels

### 3. **ASGI Configuration** (`asgi.py`)
- Updated to use Channels' ProtocolTypeRouter
- Configured WebSocket routing with AuthMiddlewareStack
- Maintains HTTP support through Django's ASGI app

### 4. **WebSocket Consumer** (`core/consumers.py`)
- Created `UploadNotificationConsumer` to handle WebSocket connections
- Manages user groups for targeted notifications
- Authenticates users before accepting connections

### 5. **WebSocket Routing** (`core/routing.py`)
- Defined WebSocket URL pattern: `/ws/notifications/`
- Maps to UploadNotificationConsumer

### 6. **Notification Utilities** (`core/utils.py`)
- `send_upload_notification()` - Main function to send notifications
- Helper functions for icon and alert type mapping
- Uses async_to_sync to send messages from Celery tasks

### 7. **Celery Tasks** (`core/tasks.py`)
- Updated `set_upload_status()` to send WebSocket notifications
- Imported and integrated `send_upload_notification()`
- Sends status messages: "Upload created", "Processing started", "Processing completed", "Processing failed"

### 8. **Frontend - Base Template** (`templates/base.html`)
- Added notifications container with fixed positioning
- Included Bootstrap Icons CSS
- Added CSS animations for sliding notifications
- Implemented WebSocket client that:
  - Connects to `/ws/notifications/` endpoint
  - Displays notifications with auto-dismiss after 5 seconds
  - Shows upload ID, status message, and status icon

### 9. **Frontend - Dashboard** (`templates/core/dashboard.html`)
- Added status badges to upload cards
- Color-coded status indicators:
  - Blue (Info): Pending
  - Yellow (Warning): Processing
  - Green (Success): Completed
  - Red (Danger): Failed
- Added auto-refresh when uploads are processing

## How It Works

1. **User logs in** → WebSocket connection established via `/ws/notifications/`
2. **User uploads a file** → Upload created with PENDING status
3. **Status changes** (via Celery) → `set_upload_status()` called
4. **Notification sent** → `send_upload_notification()` sends to user's group
5. **User receives notification** → Real-time toast appears on page
6. **Dashboard updates** → Status badge updates in real-time

## Architecture Flow

```
User Uploads File
    ↓
Celery Task Starts (process_media_from_file/url)
    ↓
Status Changes (PROCESSING → COMPLETED/FAILED)
    ↓
set_upload_status() called
    ↓
send_upload_notification() queued to user's WebSocket group
    ↓
UploadNotificationConsumer receives message
    ↓
WebSocket broadcasts to user's browser
    ↓
JavaScript displays toast notification
    ↓
Dashboard badge updates
```

## Running with Channels

### Development
```bash
# Terminal 1: Start Daphne ASGI server
poetry run daphne -b 0.0.0.0 -p 8000 video_transcriber.asgi:application

# Terminal 2: Start Celery worker
poetry run celery -A video_transcriber worker -l info

# Terminal 3: Start Celery beat (if scheduled tasks used)
poetry run celery -A video_transcriber beat -l info
```

### Docker
Update docker-compose.yml to use Daphne instead of Django's development server:
```bash
docker-compose up
```

## Configuration

### Redis Connection
Update in production with appropriate Redis URL:
```python
# In .env file
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
```

## Troubleshooting

### WebSocket Not Connecting
- Check Redis is running and accessible
- Verify CHANNEL_LAYERS configuration
- Check browser console for error messages
- Ensure user is authenticated

### Notifications Not Sending
- Verify Celery worker is running
- Check Celery task logs for errors in `set_upload_status()`
- Ensure user_id is correctly passed
- Check Redis connection

### Performance
- Notifications are async (non-blocking)
- Multiple users can receive notifications simultaneously
- Redis handles scaling to multiple server instances

## Security Considerations

✅ **Implemented:**
- User authentication required for WebSocket connection
- Users only receive notifications for their own uploads (via user_id grouping)
- CSRF protection maintained

⚠️ **TODO (if scaling):**
- Add rate limiting for WebSocket messages
- Consider messages expiration settings
- Monitor Redis memory usage with many concurrent connections

## Notification Messages

| Event | Message | Icon | Color |
|-------|---------|------|-------|
| Upload created | 📋 Upload created | hourglass-split | info |
| Processing started | ⏳ Processing started | arrow-repeat | info |
| Processing complete | ✅ Processing completed | check-circle | success |
| Processing failed | ❌ Processing failed | exclamation-triangle | danger |

## Future Enhancements

- Add progress percentage for long-running tasks
- Store notification history in database
- Add notification preferences (email, SMS, push)
- Implement notification badges in navbar
- Add sound notifications option
- Create notification center/history page
