import yt_dlp

def get_thumbnail_and_title(url: str, upload_id: int) -> tuple[str, str]:
    
    ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'noplaylist': True,
            'extract_flat': True,
            'referer': url,
            'http_headers': {'User-Agent': 'Mozilla/5.0'},
        }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            title = info.get('title') or (info.get('description', '')[:100] if info.get('description') else f"video_{upload_id}")

            thumbnails = info.get('thumbnail', [])
            thumbnail_url = (
                info.get('thumbnail') or
                (thumbnails[-1]['url'] if thumbnails else None) or
                (info.get('avatar', {}).get('url'))
            )
    
    return title, thumbnail_url