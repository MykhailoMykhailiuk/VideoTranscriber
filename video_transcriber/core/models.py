from pathlib import Path

from django.db import models
from django.contrib.auth.models import User


def file_path(instance, filename):
    ext = Path(filename).suffix
    base_name = Path(filename).stem

    if isinstance(instance, Upload):
        new_filename = f"{base_name}{ext}"
        return f"{instance.user.username}/uploads/{new_filename}"
    
    elif isinstance(instance, Output):
        output_type = instance.get_output_type_display()
        new_filename = f"{Path(instance.upload.get_filename()).stem}_{output_type}{ext}"
        return f"{instance.upload.user.username}/outputs/{new_filename}"


class Upload(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file = models.FileField(upload_to=file_path, blank=True, null=True)
    file_url = models.URLField(blank=True, null=True)
    thumbnail = models.ImageField(upload_to='thumbnails/', blank=True, null=True)
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