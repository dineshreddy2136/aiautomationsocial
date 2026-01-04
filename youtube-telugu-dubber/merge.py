#!/usr/bin/env python3
"""
Merge Tool - Re-merge video and audio with different speed settings
Use this to adjust audio sync without calling paid APIs
"""

import click
from pathlib import Path
from modules.video_processor import merge_audio_video


@click.command()
@click.option('--video', '-v', required=True, help='Path to video file')
@click.option('--audio', '-a', required=True, help='Path to audio file (MP3)')
@click.option('--output', '-o', required=True, help='Output video path')
@click.option('--speed', '-s', default=1.0, type=float, help='Audio speed (1.0=normal, 1.5=faster, 0.8=slower)')
def main(video: str, audio: str, output: str, speed: float):
    """
    Re-merge video and audio with adjustable speed.
    
    Use this tool to adjust audio sync without re-running the full pipeline.
    
    Examples:
        # Make audio 1.6x faster to sync with video
        python merge.py -v video.mp4 -a audio.mp3 -o output.mp4 --speed 1.6
        
        # Slow down audio to 0.9x
        python merge.py -v video.mp4 -a audio.mp3 -o output.mp4 --speed 0.9
    """
    print("=" * 50)
    print("🔧 Audio-Video Merge Tool")
    print("=" * 50)
    
    video_path = Path(video)
    audio_path = Path(audio)
    output_path = Path(output)
    
    if not video_path.exists():
        click.echo(f"❌ Video not found: {video_path}", err=True)
        return
    
    if not audio_path.exists():
        click.echo(f"❌ Audio not found: {audio_path}", err=True)
        return
    
    print(f"\n📹 Video: {video_path}")
    print(f"🎵 Audio: {audio_path}")
    print(f"⚡ Speed: {speed}x")
    print(f"📁 Output: {output_path}\n")
    
    merge_audio_video(video_path, audio_path, output_path, audio_speed=speed)
    
    print("\n" + "=" * 50)
    print("✅ Done!")
    print(f"📁 Output: {output_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
