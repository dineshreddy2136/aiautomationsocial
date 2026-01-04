"""
Video processing module using FFmpeg
"""

import ffmpeg
from pathlib import Path


def merge_audio_video(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    audio_speed: float = None
) -> Path:
    """
    Merge Telugu audio with video, replacing original audio.
    
    Args:
        video_path: Path to original video
        audio_path: Path to Telugu audio file
        output_path: Path for output video
        audio_speed: Speed multiplier for audio (1.0 = normal). 
                     NOTE: Speed is now handled by Eleven Labs directly, 
                     this parameter is for post-processing adjustments only.
        
    Returns:
        Path to merged video
    """
    # Default to no speed change (speed is handled by Eleven Labs now)
    speed = audio_speed if audio_speed is not None else 1.0
    
    if speed != 1.0:
        print(f"⏳ Merging audio with video (additional audio speed adjustment: {speed}x)...")
    else:
        print("⏳ Merging audio with video...")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Get video stream (without audio)
    video = ffmpeg.input(str(video_path))
    audio = ffmpeg.input(str(audio_path))
    
    # Apply audio speed filter if needed (for post-processing adjustments)
    if speed != 1.0:
        # atempo filter (valid range: 0.5 to 2.0)
        audio_stream = audio.audio
        remaining_speed = speed
        while remaining_speed > 2.0:
            audio_stream = audio_stream.filter('atempo', 2.0)
            remaining_speed /= 2.0
        if remaining_speed < 0.5:
            audio_stream = audio_stream.filter('atempo', 0.5)
        else:
            audio_stream = audio_stream.filter('atempo', remaining_speed)
    else:
        audio_stream = audio.audio
    
    # Combine video (muted) with new audio
    (
        ffmpeg
        .output(
            video.video,
            audio_stream,
            str(output_path),
            vcodec='copy',          # Copy video codec (fast)
            acodec='aac',           # Re-encode audio to AAC
            audio_bitrate='192k'
        )
        .overwrite_output()
        .run(quiet=True)
    )
    
    print(f"✓ Created dubbed video: {output_path}")
    return output_path


def get_video_duration(video_path: Path) -> float:
    """Get duration of video in seconds"""
    probe = ffmpeg.probe(str(video_path))
    duration = float(probe['format']['duration'])
    return duration
