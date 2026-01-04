#!/usr/bin/env python3
"""
YouTube Telugu Dubber CLI
Downloads YouTube videos and creates Telugu dubbed versions.
"""

import click
from pathlib import Path
import sys
import shutil

from config import (
    GEMINI_API_KEY,
    ELEVENLABS_API_KEY,
    DEFAULT_VOICE_ID,
    TEMP_DIR,
    OUTPUT_DIR,
    WHISPER_MODEL,
    validate_config
)
from modules.downloader import download_video, download_subtitles
from modules.transcript import extract_transcript
from modules.translator import translate_to_telugu
from modules.tts import generate_audio
from modules.video_processor import merge_audio_video


@click.command()
@click.option('--url', '-u', required=True, help='YouTube video URL')
@click.option('--output', '-o', default=None, help='Output file path (optional)')
@click.option('--voice', '-v', default=None, help='Eleven Labs voice ID (optional)')
@click.option('--keep-temp', is_flag=True, help='Keep temporary files')
def main(url: str, output: str, voice: str, keep_temp: bool):
    """
    Dub a YouTube video into Telugu.
    
    Downloads the video, extracts transcript, translates to Telugu,
    generates voiceover with Eleven Labs, and creates the final dubbed video.
    """
    print("=" * 50)
    print("🎬 YouTube Telugu Dubber")
    print("=" * 50)
    
    # Validate configuration
    try:
        validate_config()
    except ValueError as e:
        click.echo(f"\n❌ Configuration Error:\n{e}", err=True)
        click.echo("\nPlease copy .env.example to .env and add your API keys.", err=True)
        sys.exit(1)
    
    # Use provided voice or default
    voice_id = voice or DEFAULT_VOICE_ID
    
    try:
        # Step 1: Download video
        print("\n📥 Step 1/5: Downloading video...")
        video_path, video_title = download_video(url, TEMP_DIR)
        
        # Step 2: Download/extract subtitles
        print("\n📄 Step 2/5: Extracting transcript...")
        subtitle_path = download_subtitles(url, TEMP_DIR)
        
        # Step 3: Extract transcript
        segments = extract_transcript(
            video_path=video_path,
            subtitle_path=subtitle_path,
            whisper_model=WHISPER_MODEL
        )
        
        if not segments:
            click.echo("❌ Could not extract any transcript from the video", err=True)
            sys.exit(1)
        
        print(f"   Found {len(segments)} transcript segments")
        
        # Step 4: Translate to Telugu
        print("\n🌐 Step 3/5: Translating to Telugu...")
        telugu_segments = translate_to_telugu(segments, GEMINI_API_KEY)
        
        # Step 5: Generate Telugu audio
        print("\n🎙️ Step 4/5: Generating Telugu voiceover...")
        audio_path = TEMP_DIR / "telugu_audio.mp3"
        generate_audio(telugu_segments, ELEVENLABS_API_KEY, voice_id, audio_path)
        
        # Step 6: Merge audio with video
        print("\n🎬 Step 5/5: Creating final video...")
        
        # Determine output path
        if output:
            output_path = Path(output)
        else:
            safe_title = "".join(c for c in video_title if c.isalnum() or c in ' -_')[:40]
            output_path = OUTPUT_DIR / f"{safe_title}_telugu.mp4"
        
        final_video = merge_audio_video(video_path, audio_path, output_path)
        
        # Save audio file to output folder
        audio_output_path = output_path.with_suffix('.mp3')
        shutil.copy(audio_path, audio_output_path)
        print(f"✓ Saved audio: {audio_output_path}")
        
        # Cleanup temp files
        if not keep_temp:
            print("\n🧹 Cleaning up temporary files...")
            shutil.rmtree(TEMP_DIR, ignore_errors=True)
            TEMP_DIR.mkdir(exist_ok=True)
        
        print("\n" + "=" * 50)
        print("✅ Success!")
        print(f"📁 Video: {final_video}")
        print(f"🎵 Audio: {audio_output_path}")
        print("=" * 50)
        
    except Exception as e:
        click.echo(f"\n❌ Error: {e}", err=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
