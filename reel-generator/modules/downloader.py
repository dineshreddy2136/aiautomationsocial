"""
YouTube video and subtitle downloader module
"""

import yt_dlp
from pathlib import Path
from typing import Optional, Tuple
import re


def sanitize_filename(title: str) -> str:
    """Sanitize video title for use as filename"""
    sanitized = re.sub(r'[<>:"/\\|?*]', '', title)
    return sanitized[:50].strip()


def download_video(url: str, output_dir: Path) -> Tuple[Path, str]:
    """
    Download YouTube video.
    
    Args:
        url: YouTube video URL
        output_dir: Directory to save the video
        
    Returns:
        Tuple of (video_path, video_title)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': str(output_dir / '%(id)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info['id']
        video_title = info.get('title', video_id)
        ext = info.get('ext', 'mp4')
        video_path = output_dir / f"{video_id}.{ext}"
        
    print(f"✓ Downloaded video: {video_title}")
    return video_path, video_title


def download_subtitles(url: str, output_dir: Path) -> Optional[Path]:
    """
    Download YouTube subtitles/captions.
    
    Args:
        url: YouTube video URL
        output_dir: Directory to save subtitles
        
    Returns:
        Path to subtitle file, or None if not available
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en', 'en-US', 'en-GB'],
        'subtitlesformat': 'vtt',
        'outtmpl': str(output_dir / '%(id)s'),
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info['id']
    
    # Check for subtitle files
    for lang in ['en', 'en-US', 'en-GB']:
        subtitle_path = output_dir / f"{video_id}.{lang}.vtt"
        if subtitle_path.exists():
            print(f"✓ Downloaded subtitles: {subtitle_path.name}")
            return subtitle_path
    
    # Check for auto-generated subtitles
    for file in output_dir.glob(f"{video_id}*.vtt"):
        print(f"✓ Downloaded auto-generated subtitles: {file.name}")
        return file
    
    print("⚠ No subtitles available, will use Whisper fallback")
    return None
