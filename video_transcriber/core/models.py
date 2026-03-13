from pathlib import Path

from django.db import models
from django.contrib.auth.models import User


VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
TEXT_EXTENSIONS  = {'.txt', '.pdf', '.docx', '.srt', '.vtt'}

def get_upload_folder(ext: str) -> str:
    ext = ext.lower()
    if ext in VIDEO_EXTENSIONS:
        return 'video'
    elif ext in AUDIO_EXTENSIONS:
        return 'audio'
    elif ext in IMAGE_EXTENSIONS:
        return 'image'
    elif ext in TEXT_EXTENSIONS:
        return 'docs'
    return 'other'

def file_path(instance, filename):
    ext = Path(filename).suffix
    base_name = Path(filename).stem

    if isinstance(instance, Upload):
        folder = get_upload_folder(ext)
        return f"{instance.user.username}/uploads/{folder}/{base_name}{ext}"
    
    elif isinstance(instance, Output):
        stem = Path(instance.upload.get_filename()).stem
        type_folder = {
            OutputType.AUDIO: 'audio',
            OutputType.TRANSCRIPTION: 'docs',
            OutputType.SUMMARY: 'docs',
            OutputType.HIGHLIGHTS: 'docs',
        }.get(instance.output_type, 'other')

        return f"{instance.upload.user.username}/outputs/{type_folder}/{stem}_{instance.output_type}{ext}"


class Upload(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file = models.FileField(upload_to=file_path, blank=True, null=True)
    file_url = models.URLField(blank=True, null=True)
    thumbnail = models.ImageField(upload_to=file_path, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def get_filename(self):
        if self.file:
            return Path(self.file.name).name
        elif self.file_url:
            return Path(self.file_url).stem or f"video_{self.id}"
        return f"file_{self.id}"


class OutputType(models.TextChoices):
    '''Processing results types'''

    TRANSCRIPTION = 'transcript'
    SUMMARY = 'summary'
    HIGHLIGHTS = 'highlights'
    AUDIO = 'audio'


class Output(models.Model):
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE)
    output_type = models.CharField(max_length=20, choices=OutputType.choices)
    content = models.TextField(blank=True, null=True)
    file = models.FileField(upload_to=file_path, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['upload', 'output_type']