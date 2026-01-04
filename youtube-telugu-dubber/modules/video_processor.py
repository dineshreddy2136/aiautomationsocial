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


def add_background_music(
    video_path: Path,
    music_path: Path,
    output_path: Path,
    volume: float = 0.3
) -> Path:
    """
    Add background music to a video.
    
    Args:
        video_path: Path to video file
        music_path: Path to music file
        output_path: Path for output video
        volume: Volume of background music (0.0 to 1.0)
        
    Returns:
        Path to output video
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Get durations
    video_duration = get_video_duration(video_path)
    
    # Inputs
    video = ffmpeg.input(str(video_path))
    music = ffmpeg.input(str(music_path))
    
    # Determine if music needs looping
    music_probe = ffmpeg.probe(str(music_path))
    music_duration = float(music_probe['format']['duration'])
    
    if music_duration < video_duration:
        # Loop music stream
        music = ffmpeg.input(str(music_path), stream_loop=-1)
    
    # Create audio mix:
    # [0:a] is original video audio (keep it)
    # [1:a] is background music (lowered volume)
    # We mix them together
    
    # Adjust music volume and trim to video length
    bg_music = (
        music.audio
        .filter('volume', volume)
        .filter('atrim', duration=video_duration)
    )
    
    # Combine original audio with background music
    # "amix" mixes multiple audio streams. 
    # inputs=2: mix original + bg music
    # duration=first: match duration of first input (video)
    # dropout_transition=0: smooth transition
    mixed_audio = ffmpeg.filter([video.audio, bg_music], 'amix', inputs=2, duration='first', dropout_transition=0)
    
    (
        ffmpeg
        .output(
            video.video,
            mixed_audio,
            str(output_path),
            vcodec='copy',          # Copy video stream
            acodec='aac',           # Re-encode audio
            audio_bitrate='192k',
            shortest=None
        )
        .overwrite_output()
        .run(quiet=True)
    )
    
    return output_path
