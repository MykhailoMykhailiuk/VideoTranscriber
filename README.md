# Video Transcriber

A Django application for transcribing video and audio files, generating summaries, and extracting highlights using AI/ML models.

## Features

- Video and audio file upload (local or URL)
- Automatic video metadata extraction (thumbnails, titles)
- Audio extraction from video files
- Speech-to-text transcription using OpenAI Whisper
- Automatic transcription summarization
- Real-time WebSocket notifications for upload status
- User authentication and file management

## Installation

1. Install dependencies:
   ```bash
   poetry install
   ```

2. Set up environment variables:
   ```bash
   cp .env.example .env
   ```

3. Run migrations:
   ```bash
   python manage.py migrate
   ```

4. Start Celery worker:
   ```bash
   celery -A video_transcriber worker -l info
   ```

5. Run development server:
   ```bash
   python manage.py runserver
   ```

## Technology Stack

- Django 5.2
- Django Channels for WebSocket support
- Celery for async task processing
- Redis for message queue and WebSocket channel layer
- Whisper (OpenAI) for transcription
- Transformers library for summarization
- MoviePy for video processing
