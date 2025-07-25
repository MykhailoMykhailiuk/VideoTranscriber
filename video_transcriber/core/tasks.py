import os
import tempfile
import logging

import yt_dlp
import requests
import torch
import torchaudio
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from celery import shared_task, chain
from moviepy import VideoFileClip
from transformers import pipeline, WhisperForConditionalGeneration, WhisperProcessor

from .models import Upload, Output, OutputType

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def exctract_thumbnail_and_title(self, upload_id, *args, **kwargs):
    logger.info(f"[{self.__name__}] started")

    try:
        upload = Upload.objects.get(id=upload_id)

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
        self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def extract_audio_from_file(self, upload_id, *args, **kwargs):
    logger.info(f"[{self.__name__}] started")

    temp_file = None

    try:    
        upload = Upload.objects.get(id=upload_id)

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
        raise self.retry(exc=e)

    finally:
        if temp_file and os.path.exists(temp_file.name):
            os.remove(temp_file.name)


@shared_task(bind=True)
def extract_audio_from_url(self, upload_id, *args, **kwargs):
    logger.info(f"[{self.__name__}] started")

    try:        
        upload = Upload.objects.get(id=upload_id)

        output_dir = tempfile.gettempdir()

        ydl_opts = {
            'format': 'bestaudio/best',
            'retries': 3,
            'outtmpl': os.path.join(output_dir, f"audio_{upload.id}.%(ext)s"),
            'ffmpeg_location': 'C:/ffmpeg/bin/ffmpeg.exe',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }],
            'quiet': True,
        }

        downloaded_file = None

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(upload.file_url, download=True)
            downloaded_file = ydl.prepare_filename(info_dict).replace('.webm', '.mp3').replace('.m4a', '.mp3')

        if downloaded_file and os.path.exists(downloaded_file):
            output = Output.objects.create(
                    upload=upload,
                    output_type=OutputType.AUDIO
                )
        
            with open(downloaded_file, 'rb') as audio_file:  
                output.file.save(
                    f"audio_{upload.id}.mp3",
                    ContentFile(audio_file.read()),
                )
                output.save()
            os.remove(downloaded_file)

    except Exception as e:
        logger.error(f"[{self.__name__}] Media Processing Error for {upload.file_url} {e}")
        self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def transcribe_media(self, upload_id, *args, **kwargs):
    logger.info(f"[{self.__name__}] started")
    try:
        upload = Upload.objects.get(id=upload_id)

        audio = Output.objects.filter(
            upload=upload,
            output_type=OutputType.AUDIO,
            file__isnull=False
        ).first()

        if not audio and not audio.file:
            logger.warning(f"Audio for {upload.id} not found, retrying...")
            raise self.retry(countdown=30)

        if not default_storage.exists(audio.file.name):
            logger.error(f"File {audio.file.name} not found in the storage!")
            raise self.retry(countdown=60)
        
        device = "cuda" if torch.cuda.is_available() else "cpu"

        model = WhisperForConditionalGeneration.from_pretrained("openai/whisper-small").to(device)
        processor = WhisperProcessor.from_pretrained("openai/whisper-small")
        audio_path = default_storage.path(audio.file.name)
        waveform, sample_rate = torchaudio.load(audio_path)
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)

        waveform = waveform[0].numpy()
        chunk_size = 16000 * 30
        total_length = waveform.shape[0]
        num_chunks = (total_length + chunk_size - 1) // chunk_size

        all_text = []

        for i in range(num_chunks):
            start = i * chunk_size
            end = min((i + 1) * chunk_size, total_length)
            chunk = waveform[start:end]

            inputs = processor(
                chunk, 
                return_tensors="pt",
                sampling_rate=16000
            ).input_features.to(device)

            generated_ids = model.generate(
                inputs,
                language="uk",
                task="transcribe"
            )

            text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            all_text.append(text.strip())

        full_transcript = "".join(all_text)

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
        raise self.retry(exc=e, countdown=120)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def process_media_from_file(self, upload_id, output_types):
    logger.info(f"[{self.__name__}] started")

    try:
        upload = Upload.objects.get(id=upload_id)

        if not upload.file:
            logger.error(f"File {upload.id} not found!")
        
        if OutputType.AUDIO in output_types:
            extract_audio_from_file.delay(upload.id)
        elif OutputType.TRANSCRIPTION in output_types:
            chain(
                extract_audio_from_file.s(upload.id),
                transcribe_media.si(upload.id)
            ).apply_async()

    except Exception as e:
        logger.error(f"[{self.__name__}] Media Processing Error for {upload.file} {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def process_media_from_url(self, upload_id, output_types):
    logger.info(f"[{self.__name__}] started")

    try:
        upload = Upload.objects.get(id=upload_id)

        if not upload.file_url:
            logger.error(f"File {upload.id} not found!")
        
        exctract_thumbnail_and_title.delay(upload.id)

        if OutputType.AUDIO in output_types:
            extract_audio_from_url.delay(upload.id)
        elif OutputType.TRANSCRIPTION in output_types:
            chain(
                extract_audio_from_url.s(upload.id),
                transcribe_media.si(upload.id)
            ).apply_async()

    except Exception as e:
        logger.error(f"[{self.__name__}] Media Processing Error for {upload.file_url} {e}")
        raise self.retry(exc=e, countdown=120)
