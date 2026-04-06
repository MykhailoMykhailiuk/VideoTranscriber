import os
import tempfile
import logging
import shutil

import yt_dlp
import requests
import torch
import torchaudio
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from celery import shared_task, chain
from moviepy import VideoFileClip
from transformers import (
    WhisperForConditionalGeneration,
    WhisperProcessor,
    pipeline, 
    AutoTokenizer
)
from deepmultilingualpunctuation import PunctuationModel

from .models import Upload, Output, OutputType, UploadStatus
from .utils import send_upload_notification

logger = logging.getLogger(__name__)

def check_existing(upload, output_type, required_file=False):
    query = Output.objects.filter(upload=upload, output_type=output_type)
    if required_file:
        query = query.filter(file__isnull=False)
    return query.exists()

def set_upload_status(upload_id: int, status: str):
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
    logger.info(f"[{self.__name__}] started")

    try:
        upload = Upload.objects.get(id=upload_id)

        if upload.thumbnail:
            logger.info(f"Thumbnail already exists for Upload {upload.id}, skipping extraction")
            return

        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'noplaylist': True,
            'extract_flat': True,
            'referer': upload.file_url,
            'http_headers': {'User-Agent': 'Mozilla/5.0'},
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(upload.file_url, download=False)

            upload.file = info.get('title') or (info.get('description', '')[:100] if info.get('description') else f"video_{upload.id}")

            thumbnails = info.get('thumbnail', [])
            thumbnail_url = (
                info.get('thumbnail') or
                (thumbnails[-1]['url'] if thumbnails else None) or
                (info.get('avatar', {}).get('url'))
            )

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
    logger.info(f"[{self.__name__}] started")

    temp_file = None

    try:    
        upload = Upload.objects.get(id=upload_id)

        if check_existing(upload=upload, output_type=OutputType.AUDIO, required_file=True):
            logger.info(f"Audio for Upload {upload.id} already exists, skipping extraction")
            return

        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
            with VideoFileClip(upload.file.path) as clip:
                clip.audio.write_audiofile(temp_file.name)

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
    logger.info(f"[{self.__name__}] started")

    output_dir = tempfile.gettempdir()
    downloaded_file = os.path.join(output_dir, f"audio_{upload_id}.mp3")

    try:        
        upload = Upload.objects.get(id=upload_id)

        if check_existing(upload=upload, output_type=OutputType.AUDIO, required_file=True):
            logger.info(f"Audio for Upload {upload.id} already exists, skipping extraction")
            return

        ydl_opts = {
            'format': 'bestaudio/best',
            'ffmpeg_location': shutil.which('ffmpeg'), 
            'retries': 3,
            'outtmpl': os.path.join(output_dir, f"audio_{upload.id}.%(ext)s"),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }],
            'quiet': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(upload.file_url, download=True)

        if not os.path.exists(downloaded_file):
            raise FileNotFoundError(f"Expected audio file not found: {downloaded_file}")
        
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

def get_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    elif torch.cuda.is_available():
        return "cuda"
    return "cpu"

WHISPER_MODEL = None
WHISPER_PROCESSOR = None

def get_whisper_model_and_processor(device: str):
    global WHISPER_MODEL, WHISPER_PROCESSOR
    if WHISPER_MODEL is None or WHISPER_PROCESSOR is None:
        WHISPER_MODEL = WhisperForConditionalGeneration.from_pretrained("openai/whisper-small").to(device)
        WHISPER_PROCESSOR = WhisperProcessor.from_pretrained("openai/whisper-small")
    return WHISPER_MODEL, WHISPER_PROCESSOR


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def transcribe_media(self, upload_id, *args, **kwargs):
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

        device = get_device()
        model, processor = get_whisper_model_and_processor(device)
        audio_path = default_storage.path(audio.file.name)

        waveform, sample_rate = torchaudio.load(audio_path)
        if sample_rate != 16000:
            waveform = torchaudio.transforms.Resample(sample_rate, 16000)(waveform)

        # mix down to mono if necessary
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)
        waveform = waveform[0].numpy()

        # transcribe in chunks
        chunk_size = 16000 * 30  # 30 seconds
        overlap = 16000 * 2  # 2 seconds overlap
        total_length = waveform.shape[0]
        num_chunks = (total_length + chunk_size - 1) // chunk_size
        all_text = []

        for i in range(num_chunks):
            start = max(0, i * chunk_size - overlap)
            end = min((i + 1) * chunk_size, total_length)
            chunk = waveform[start:end]

            inputs = processor(
                chunk, 
                return_tensors="pt",
                sampling_rate=16000
            ).input_features.to(device)

            with torch.no_grad():
                generated_ids = model.generate(
                    inputs,
                    task="transcribe",
                    repetition_penalty=1.3,
                )

            text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            all_text.append(text.strip())
            logger.info(f"[{self.__name__}] chunk {i + 1}/{num_chunks} done")

        punct_model = PunctuationModel()
        full_transcript = " ".join(all_text)
        full_transcript = punct_model.restore_punctuation(full_transcript)

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
        import traceback
        logger.error(f"[{self.__name__}] Transcribing error for {upload_id} {e}\n{traceback.format_exc()}")
        set_upload_status(upload_id, UploadStatus.FAILED)
        raise self.retry(exc=e, countdown=120)

SUMMARIZER = None
SUMMARIZER_TOKENIZER = None

def get_summarizer():
    global SUMMARIZER, SUMMARIZER_TOKENIZER
    if SUMMARIZER is None:
        model_name = "google/mt5-small"
        SUMMARIZER_TOKENIZER = AutoTokenizer.from_pretrained(
            model_name,
            model_max_length=512
        )
        SUMMARIZER = pipeline(
            "summarization",
            model=model_name,
            tokenizer=SUMMARIZER_TOKENIZER
        )
    return SUMMARIZER

def chunk_text(text: str, max_words: int) -> list[str]:
    words = text.split()
    chunks = []

    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i:i + max_words]))
    
    return chunks

@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def summarize_transcription(self, upload_id, *args, **kwargs):
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
        summarizer = get_summarizer()
        chunks = chunk_text(transcript.content, max_words=150)

        chunk_summaries = []
        for chunk in chunks:
            result = summarizer(
                chunk,
                max_length=200,
                min_length=50,
                do_sample=False,
                truncation=True
            )
            chunk_summaries.append(result[0]['summary_text'])
            logger.info(f"[{self.__name__}] chunk {chunks.index(chunk) + 1}/{len(chunks)} done")

        if len(chunk_summaries) > 1:
            combined = " ".join(chunk_summaries)
            combined = " ".join(combined.split()[:700])

            final_summary = summarizer(
                combined,
                max_length=150,
                min_length=30,
                do_sample=False,
                truncation=True
            )[0]['summary_text']

        else:
            final_summary = chunk_summaries[0]

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
    set_upload_status(upload_id, UploadStatus.COMPLETED)
    logger.info(f"Upload {upload_id} marked as COMPLETED")


def build_pipeline(upload_id: int, output_types: list, source: str) -> list:
    '''Returns a list of tasks to be executed for the given upload and output types
    
    upload_id: int: ID of the Upload object
    output_types: list: List of OutputType values to be generated
    source: str: 'file' or 'url' indicating the source of the media  
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
