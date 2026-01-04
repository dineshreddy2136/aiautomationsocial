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
    AUDIO_DIR,
    WHISPER_MODEL,
    validate_config
)
from modules.downloader import download_video, download_subtitles
from modules.transcript import extract_transcript
from modules.translator import translate_to_telugu
from modules.tts import generate_audio
from modules.video_processor import merge_audio_video


@click.command()
@click.option('--url', '-u', default=None, help='YouTube video URL')
@click.option('--output', '-o', default=None, help='Output file path (optional)')
@click.option('--voice', '-v', default=None, help='Eleven Labs voice ID (optional)')
@click.option('--audio-only', '-a', is_flag=True, help='Only generate Telugu audio, skip video merge')
@click.option('--download-audio', '-d', is_flag=True, help='Only download original audio from YouTube (no dubbing)')
@click.option('--add-music', '-m', default=None, help='Add background music to a video (provide video path)')
@click.option('--music-file', default=None, help='Path to music file (from audio/ folder)')
@click.option('--music-volume', default=0.3, type=float, help='Background music volume (0.0-1.0, default: 0.3)')
@click.option('--keep-temp', is_flag=True, help='Keep temporary files')
def main(url: str, output: str, voice: str, audio_only: bool, download_audio: bool, 
         add_music: str, music_file: str, music_volume: float, keep_temp: bool):
    """
    Dub a YouTube video into Telugu.
    
    Downloads the video, extracts transcript, translates to Telugu,
    generates voiceover with Eleven Labs, and creates the final dubbed video.
    """
    print("=" * 50)
    print("🎬 YouTube Telugu Dubber")
    print("=" * 50)
    
    # Add background music mode
    if add_music:
        from modules.video_processor import add_background_music
        
        video_path = Path(add_music)
        if not video_path.exists():
            click.echo(f"❌ Video file not found: {video_path}", err=True)
            sys.exit(1)
        
        # Find music file
        if music_file:
            music_path = Path(music_file)
            if not music_path.exists():
                music_path = AUDIO_DIR / music_file
        else:
            # List available music files
            music_files = list(AUDIO_DIR.glob("*.mp3"))
            if not music_files:
                click.echo("❌ No music files in audio/ folder. Use --download-audio first.", err=True)
                sys.exit(1)
            
            print("\n🎵 Available music files:")
            for i, f in enumerate(music_files, 1):
                print(f"  {i}. {f.name}")
            
            # Use first file by default
            music_path = music_files[0]
            print(f"\n  Using: {music_path.name}")
        
        if not music_path.exists():
            click.echo(f"❌ Music file not found: {music_path}", err=True)
            sys.exit(1)
        
        print(f"\n🎵 Adding background music...")
        print(f"  Video: {video_path}")
        print(f"  Music: {music_path.name}")
        print(f"  Volume: {music_volume:.0%}")
        
        if output:
            output_path = Path(output)
        else:
            output_path = OUTPUT_DIR / f"{video_path.stem}_with_music.mp4"
        
        result = add_background_music(video_path, music_path, output_path, music_volume)
        print(f"\n✅ Output: {result}")
        return
    
    # Check URL is provided for other modes
    if not url:
        click.echo("❌ Error: --url is required for dubbing or download modes", err=True)
        sys.exit(1)
    
    # Download audio only mode - no API keys needed
    if download_audio:
        from modules.downloader import download_audio_only
        print("\n📥 Downloading audio from YouTube...")
        
        if output:
            output_path = Path(output)
        else:
            output_path = AUDIO_DIR
        
        audio_file = download_audio_only(url, output_path)
        print(f"\n✅ Downloaded: {audio_file}")
        return
    
    # Validate configuration (only for dubbing)
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
        
        # Determine output path
        if output:
            output_path = Path(output)
        else:
            safe_title = "".join(c for c in video_title if c.isalnum() or c in ' -_')[:40]
            if audio_only:
                output_path = OUTPUT_DIR / f"{safe_title}_telugu.mp3"
            else:
                output_path = OUTPUT_DIR / f"{safe_title}_telugu.mp4"
        
        if audio_only:
            # Audio only mode - skip video merge
            print("\n🎵 Saving audio file (audio-only mode)...")
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
            print(f"🎵 Audio: {audio_output_path}")
            print("=" * 50)
        else:
            # Full mode - merge audio with video
            print("\n🎬 Step 5/5: Creating final video...")
            
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
