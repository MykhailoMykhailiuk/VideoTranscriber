import os
import shutil
import tempfile

import yt_dlp
from moviepy import VideoFileClip


def get_audio_from_video_file(video_path: str, output_path: str) -> str:
    '''
    Extracts audio from a video file and saves it to the specified output path.

    video_path: Path to the input video file.
    output_path: Path where the extracted audio file will be saved.
    Returns the path to the extracted audio file.
    '''
    with VideoFileClip(video_path) as clip:
        clip.audio.write_audiofile(output_path)
    
    return output_path


def get_audio_from_url(url: str, upload_id: int) -> str:
    '''
    Extracts audio from a video URL and saves it as an MP3 file.

    url: The URL of the video to extract audio from.
    upload_id: A unique identifier for the upload, used to name the output file.
    Returns the path to the extracted audio file.
    '''
    output_dir = tempfile.gettempdir()
    downloaded_file = os.path.join(output_dir, f"audio_{upload_id}.mp3")

    ydl_opts = {
            'format': 'bestaudio/best',
            'ffmpeg_location': shutil.which('ffmpeg'), 
            'retries': 3,
            'outtmpl': os.path.join(output_dir, f"audio_{upload_id}.%(ext)s"),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }],
            'quiet': True,
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)

    if not os.path.exists(downloaded_file):
            raise FileNotFoundError(f"Expected audio file not found: {downloaded_file}")

    return downloaded_file


def get_video_info(url: str) -> str:
    '''
    Retrieves information about a video from a given URL without downloading it.

    url: The URL of the video to retrieve information from.
    '''
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'noplaylist': True,
        'extract_flat': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)