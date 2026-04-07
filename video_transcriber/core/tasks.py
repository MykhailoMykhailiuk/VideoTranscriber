import os
import tempfile
import logging

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from celery import shared_task, chain


from .models import Upload, Output, OutputType, UploadStatus
from .utils import send_upload_notification
from processing.thumbnail import get_thumbnail_and_title
from processing.audio import get_audio_from_url, get_audio_from_video_file
from processing.transcription import transcribe_audio
from processing.summarization import summarize_text

logger = logging.getLogger(__name__)

def check_existing(upload, output_type, required_file=False):
    '''
    Check if an output of the given type already exists for the upload.
    If required_file is True, it will only return True if the output has a file associated with it.

    upload: Upload object to check for
    output_type: OutputType to check for
    required_file: If True, only return True if the output has a file associated with it
    return: True if an output of the given type already exists for the upload, False otherwise
    '''
    query = Output.objects.filter(upload=upload, output_type=output_type)
    if required_file:
        query = query.filter(file__isnull=False)
    return query.exists()

def set_upload_status(upload_id: int, status: str):
    '''
    Update the status of the upload and send a WebSocket notification to the user.

    upload_id: ID of the Upload object to update
    status: New status to set for the upload
    '''
    try:
        upload = Upload.objects.get(id=upload_id)
        upload.status = status
        upload.save()
        
        # Send WebSocket notification
        status_messages = {
            UploadStatus.PENDING: "📋 Upload created",
            UploadStatus.PROCESSING: "⏳ Processing started",
            UploadStatus.COMPLETED: "✅ Processing completed",
            UploadStatus.FAILED: "❌ Processing failed",
        }
        
        message = status_messages.get(status, f"Status: {status}")
        send_upload_notification(upload.user_id, upload_id, status, message)
    except Upload.DoesNotExist:
        logger.error(f"Upload with id {upload_id} does not exist")


@shared_task(bind=True)
def exctract_thumbnail_and_title(self, upload_id, *args, **kwargs):
    '''
    Extract the thumbnail and title from the video URL and save them to the Upload object.
    This task is only executed for uploads with a file_url (i.e., media from URLs like YouTube).

    upload_id: ID of the Upload object to update
    '''
    logger.info(f"[{self.__name__}] started")

    try:
        upload = Upload.objects.get(id=upload_id)

        if upload.thumbnail:
            logger.info(f"Thumbnail already exists for Upload {upload.id}, skipping extraction")
            return

        title, thumbnail_url = get_thumbnail_and_title(upload.file_url, upload.id)
        upload.file = title

        if thumbnail_url:
            try:
                response = requests.get(thumbnail_url, timeout=10)
                if response.status_code == 200:
                    upload.thumbnail.save(
                        f"thumb_{upload.id}.jpg",
                        ContentFile(response.content),
                        save=True
                    )
            except Exception as e:
                print(f"[Thumbnail Download Error] {e}")

        upload.save()

    except Exception as e:
        logger.error(f"[{self.__name__}] Media Processing Error for {upload.file_url} {e}")
        set_upload_status(upload_id, UploadStatus.FAILED)
        self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def extract_audio_from_file(self, upload_id, *args, **kwargs):
    '''
    Extract the audio from the uploaded video file and save it as an Output of type AUDIO.
    This task is only executed for uploads with a file (i.e., media uploaded directly to the platform).
        - A temporary file is created to store the extracted audio, which is then saved to the Output model.
        - The temporary file is deleted after the audio has been saved to ensure that no unnecessary files are left on the server.
    
    upload_id: ID of the Upload object to process
    '''
    logger.info(f"[{self.__name__}] started")

    temp_file = None

    try:    
        upload = Upload.objects.get(id=upload_id)

        if check_existing(upload=upload, output_type=OutputType.AUDIO, required_file=True):
            logger.info(f"Audio for Upload {upload.id} already exists, skipping extraction")
            return

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
            get_audio_from_video_file(upload.file.path, temp_file.name)

        output = Output.objects.create(
                upload=upload,
                output_type=OutputType.AUDIO
            )

        with open(temp_file.name, 'rb') as audio_file:  
            output.file.save(
                f"audio_{upload.id}.mp3",
                ContentFile(audio_file.read()),
            )
            output.save()

    except Exception as e:
        logger.error(f"[{self.__name__}] Media Processing Error for {upload.file} {e}")
        set_upload_status(upload_id, UploadStatus.FAILED)
        raise self.retry(exc=e)

    finally:
        if temp_file and os.path.exists(temp_file.name):
            os.remove(temp_file.name)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def extract_audio_from_url(self, upload_id, *args, **kwargs):
    '''
    Extract the audio from the video URL and save it as an Output of type AUDIO.
    This task is only executed for uploads with a file_url (i.e., media from URLs like YouTube).
        - The audio is downloaded directly from the URL and saved to the Output model 
        without the need for a temporary file, as the audio is streamed and saved in chunks 
        to handle large files efficiently.
    
    upload_id: ID of the Upload object to process
    '''
    logger.info(f"[{self.__name__}] started")

    try:        
        upload = Upload.objects.get(id=upload_id)

        if check_existing(upload=upload, output_type=OutputType.AUDIO, required_file=True):
            logger.info(f"Audio for Upload {upload.id} already exists, skipping extraction")
            return

        downloaded_file = get_audio_from_url(upload.file_url, upload.id)
        
        output = Output.objects.create(
            upload=upload,
            output_type=OutputType.AUDIO
            )
        
        with open(downloaded_file, 'rb') as audio_file:  
            output.file.save(
                f"audio_{upload.id}.mp3",
                ContentFile(audio_file.read()),
            )

    except Exception as e:
        logger.error(f"[{self.__name__}] Media Processing Error for {upload.file_url} {e}")
        set_upload_status(upload_id, UploadStatus.FAILED)
        raise self.retry(exc=e, countdown=60)
    
    finally:
        if os.path.exists(downloaded_file):
            os.remove(downloaded_file)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def transcribe_media(self, upload_id, *args, **kwargs):
    '''
    Transcribe the audio from the media and save it as an Output of type TRANSCRIPTION.
        - The audio file is retrieved from the Output model, 
        and the transcription is performed using the transcribe_audio function.
        - The resulting transcription is saved as a new Output of type TRANSCRIPTION 
        associated with the same Upload.   
    
    upload_id: ID of the Upload object to process
    '''
    logger.info(f"[{self.__name__}] started")
    try:
        upload = Upload.objects.get(id=upload_id)

        if check_existing(upload=upload, output_type=OutputType.TRANSCRIPTION):
            logger.info(f"Transcription already exists for {upload_id}, skipping")
            return
        
        audio = Output.objects.filter(
            upload=upload,
            output_type=OutputType.AUDIO,
            file__isnull=False
        ).first()

        if not audio or not audio.file:
            logger.warning(f"Audio for {upload.id} not found, retrying...")
            raise self.retry(countdown=30)

        if not default_storage.exists(audio.file.name):
            logger.error(f"File {audio.file.name} not found in the storage!")
            raise self.retry(countdown=60)

        audio_path = default_storage.path(audio.file.name)
        full_transcript = transcribe_audio(audio_path)
        
        output = Output.objects.create(
            upload=upload,
            output_type=OutputType.TRANSCRIPTION,
            content=full_transcript
        )
        print(f"[Transcription saved for Upload {upload.id} with Output {output.id}]")
    
    except Upload.DoesNotExist:
        logger.error(f"Upload with id {upload_id} does not exist")
        raise self.retry(countdown=120)

    except Exception as e:
        logger.error(f"[{self.__name__}] Transcribing error for {upload_id} {e}")
        set_upload_status(upload_id, UploadStatus.FAILED)
        raise self.retry(exc=e, countdown=120)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def summarize_transcription(self, upload_id, *args, **kwargs):
    '''
    Summarize the transcription of the media and save it as an Output of type SUMMARY.
        - The transcription text is retrieved from the Output model, 
        and the summarization is performed using the summarize_text function.
        - The resulting summary is saved as a new Output of type SUMMARY 
        associated with the same Upload. 
        - The summarization process includes dynamic adjustment of the max_length 
        and min_length parameters based on the token count of the input text to ensure 
        that the summarization is effective and does not exceed the model input limits. 
        - The final summary is truncated to 700 characters to ensure it is concise and suitable for display.
    
    upload_id: ID of the Upload object to process
    '''
    logger.info(f"[{self.__name__}] started")

    try:
        upload = Upload.objects.get(id=upload_id)
    
        if check_existing(upload=upload, output_type=OutputType.SUMMARY):
            logger.info(f"Summary already exists for {upload_id}, skipping")
            return
        
        transcript = Output.objects.filter(
            upload=upload,
            output_type=OutputType.TRANSCRIPTION
        ).first()

        if not transcript or not transcript.content:
            logger.warning(f"Transcription for {upload_id} not found, retrying...")
            raise self.retry(countdown=30)
        
        if len(transcript.content.strip()) < 50:
            logger.warning(f"Transcription for {upload_id} is too short to summarize: '{transcript.content}'")
            return
        
        logger.info(f"Transcript length for {upload_id}: {len(transcript.content)} chars, {len(transcript.content.split())} words")

        final_summary = summarize_text(transcript.content)

        output = Output.objects.create(
            upload=upload,
            output_type=OutputType.SUMMARY,
            content=final_summary
        )

        logger.info(f"[Summary saved for Upload {upload.id} with Output {output.id}]")

    except Exception as e:
        logger.error(f"[{self.__name__}] Summarizing error for {upload_id} {e}")
        set_upload_status(upload_id, UploadStatus.FAILED)
        raise self.retry(exc=e, countdown=120)



@shared_task(bind=True)
def set_upload_status_completed(self, upload_id):
    '''
    Mark the upload as completed.
        - This task is executed at the end of the processing pipeline 
        to update the status of the upload to COMPLETED and send a final notification to the user.

    upload_id: ID of the Upload object to update
    '''
    set_upload_status(upload_id, UploadStatus.COMPLETED)
    logger.info(f"Upload {upload_id} marked as COMPLETED")


def build_pipeline(upload_id: int, output_types: list, source: str) -> list:
    '''
    Returns a list of tasks to be executed for the given upload and output types in the correct order.
     - The pipeline is built based on the source of the media (file or URL) 
     and the requested output types (AUDIO, TRANSCRIPTION, SUMMARY).
     - For URL sources, the thumbnail and title extraction task 
     is included at the beginning of the pipeline.
     - The audio extraction task is included if any of the requested output types 
     require audio (AUDIO, TRANSCRIPTION, SUMMARY), with the specific task chosen based on the source type.
     - The transcription task is included if either TRANSCRIPTION or SUMMARY is requested, 
     as both require the transcription to be generated first.
     - The summarization task is included if SUMMARY is requested, 
     and it is placed after the transcription task since it depends on the transcription output.
     - Finally, the task to set the upload status to COMPLETED is included 
     at the end of the pipeline to ensure that the status is only updated 
     after all processing tasks have been executed.
    
    upload_id: int: ID of the Upload object
    output_types: list: List of OutputType values to be generated
    source: str: 'file' or 'url' indicating the source of the media  
    return: List of tasks to be executed
    '''

    tasks = []

    if source == 'url':
        tasks.append(exctract_thumbnail_and_title.si(upload_id))
    
    if any(ot in output_types for ot in [OutputType.AUDIO, OutputType.TRANSCRIPTION, OutputType.SUMMARY]):
        if source == 'url':
            tasks.append(extract_audio_from_url.si(upload_id))
        else:
            tasks.append(extract_audio_from_file.si(upload_id))

    if OutputType.TRANSCRIPTION in output_types or OutputType.SUMMARY in output_types:
        tasks.append(transcribe_media.si(upload_id))

    if OutputType.SUMMARY in output_types:
        tasks.append(summarize_transcription.si(upload_id))

    tasks.append(set_upload_status_completed.si(upload_id))

    return tasks


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def process_media_from_file(self, upload_id, output_types):
    '''
    Entry-point Celery task for processing media uploaded as a file.

    - This task initializes the processing pipeline for a file-based upload.
    - It first validates that the Upload object exists and contains a file.
    - The upload status is then set to PROCESSING to indicate that background 
      processing has started.
    - A pipeline of dependent Celery tasks is dynamically built using 
      the build_pipeline function based on the requested output types 
      (AUDIO, TRANSCRIPTION, SUMMARY).
    - The pipeline is executed asynchronously using a Celery chain, ensuring 
      that tasks run sequentially in the correct order.
    - If any error occurs during setup, the task is retried according to 
      the configured retry policy.

    upload_id: int: ID of the Upload object
    output_types: list: List of OutputType values to be generated
    '''
    logger.info(f"[{self.__name__}] started")

    try:
        upload = Upload.objects.get(id=upload_id)

        if not upload.file:
            logger.error(f"File {upload.id} not found!")
            return
        
        set_upload_status(upload_id, UploadStatus.PROCESSING)
        tasks = build_pipeline(upload_id=upload_id, output_types=output_types, source='file')
        if tasks:
            chain(*tasks).apply_async()

    except Exception as e:
        logger.error(f"[{self.__name__}] Media Processing Error for {upload.file} {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def process_media_from_url(self, upload_id, output_types):
    '''
    Entry-point Celery task for processing media provided via URL.

    - This task initializes the processing pipeline for a URL-based upload.
    - It validates that the Upload object exists and contains a valid file_url.
    - The upload status is set to PROCESSING to indicate that background 
      processing has started.
    - A pipeline of dependent Celery tasks is dynamically built using 
      the build_pipeline function, which includes additional steps specific 
      to URL sources (e.g., thumbnail and metadata extraction).
    - The pipeline is executed asynchronously using a Celery chain, ensuring 
      that all tasks are processed in the correct sequence.
    - If an error occurs during initialization, the task is retried 
      based on the configured retry policy.

    upload_id: int: ID of the Upload object
    output_types: list: List of OutputType values to be generated
    '''
    logger.info(f"[{self.__name__}] started")

    try:
        upload = Upload.objects.get(id=upload_id)

        if not upload.file_url:
            logger.error(f"Upload {upload_id} has no URL!")
            return
        
        set_upload_status(upload_id, UploadStatus.PROCESSING)
        tasks = build_pipeline(upload_id=upload_id, output_types=output_types, source='url')
        if tasks:
            chain(*tasks).apply_async()

    except Exception as e:
        logger.error(f"[{self.__name__}] Media Processing Error for {upload.file_url} {e}")
        raise self.retry(exc=e, countdown=120)
