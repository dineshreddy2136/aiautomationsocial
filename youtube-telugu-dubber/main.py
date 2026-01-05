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
    VIDEOS_DIR,
    WHISPER_MODEL,
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    validate_config
)
from modules.downloader import download_video, download_subtitles
from modules.transcript import extract_transcript
from modules.translator import translate_text
from modules.tts import generate_audio
from modules.video_processor import merge_audio_video


@click.command()
@click.option('--url', '-u', default=None, help='YouTube video URL')
@click.option('--output', '-o', default=None, help='Output file path (optional)')
@click.option('--voice', '-v', default=None, help='Eleven Labs voice ID (optional)')
@click.option('--audio-only', '-a', is_flag=True, help='Only generate Telugu audio, skip video merge')
@click.option('--download-audio', '-d', is_flag=True, help='Only download original audio from YouTube (no dubbing)')
@click.option('--add-music', '-m', is_flag=True, help='Add background music to video (flag for pipeline, or standalone if input provided)')
@click.option('--input-video', '-i', default=None, help='Input video file for standalone background music mode')
@click.option('--music-file', default=None, help='Path to music file (from audio/ folder)')
@click.option('--music-volume', default=0.3, type=float, help='Background music volume (0.0-1.0, default: 0.3)')
@click.option('--language', '-l', default=DEFAULT_LANGUAGE, 
              type=click.Choice(list(SUPPORTED_LANGUAGES.keys())), 
              help='Target language for dubbing (default: tel)')
@click.option('--keep-temp', is_flag=True, help='Keep temporary files')
def main(url: str, output: str, voice: str, audio_only: bool, download_audio: bool, 
         add_music: bool, input_video: str, music_file: str, music_volume: float, 
         language: str, keep_temp: bool):
    """
    Dub a YouTube video into Telugu.
    
    Downloads the video, extracts transcript, translates to Telugu,
    generates voiceover with Eleven Labs, and creates the final dubbed video.
    """
    print("=" * 50)
    print("🎬 YouTube Telugu Dubber")
    print("=" * 50)
    
    # Standalone Background Music Mode
    # Triggered if input_video is provided, OR if add_music flag is set AND no URL is provided
    if input_video or (add_music and not url):
        from modules.video_processor import add_background_music
        
        # Determine input video path
        # Check if user passed video path to --add-music (handling legacy usage just in case, though click types changed)
        # Since add_music is now is_flag=True, it won't capture string. 
        # So we look at input_video.
        
        target_video = None
        if input_video:
            target_video = Path(input_video)
        
        if not target_video or not target_video.exists():
             click.echo(f"❌ Input video not found. Use --input-video to specify the file.", err=True)
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
            
            # Use first file by default
            music_path = music_files[0]
            print(f"\n🎵 Using default music: {music_path.name}")
        
        if not music_path.exists():
            click.echo(f"❌ Music file not found: {music_path}", err=True)
            sys.exit(1)
        
        print(f"\n🎵 Adding background music...")
        print(f"  Video: {target_video}")
        print(f"  Music: {music_path.name}")
        print(f"  Volume: {music_volume:.0%}")
        
        if output:
            output_path = Path(output)
        else:
            output_path = OUTPUT_DIR / f"{target_video.stem}_with_music.mp4"
        
        result = add_background_music(target_video, music_path, output_path, music_volume)
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
        
        # Get language name for display
        lang_name = SUPPORTED_LANGUAGES.get(language, "Telugu")
        
        # Step 4: Translate to target language
        print(f"\n🌐 Step 3/5: Translating to {lang_name}...")
        translated_segments = translate_text(segments, GEMINI_API_KEY, language)
        
        # Step 5: Generate voiceover
        print(f"\n🎙️ Step 4/5: Generating {lang_name} voiceover...")
        audio_path = TEMP_DIR / "dubbed_audio.mp3"
        generate_audio(translated_segments, ELEVENLABS_API_KEY, voice_id, audio_path)
        
        # Determine output path
        if output:
            output_path = Path(output)
        else:
            safe_title = "".join(c for c in video_title if c.isalnum() or c in ' -_')[:40]
            if audio_only:
                output_path = OUTPUT_DIR / f"{safe_title}_{language}.mp3"
            else:
                output_path = VIDEOS_DIR / f"{safe_title}_{language}.mp4"
        
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
            # Full-mode - merge audio with video
            print("\n🎬 Step 5/5: Creating final video...")
            
            final_video = merge_audio_video(video_path, audio_path, output_path)
            
            # Step 6: Add background music (Optional)
            if add_music:
                print("\n🎵 Step 6/6: Adding background music...")
                from modules.video_processor import add_background_music
                
                 # Find music file
                if music_file:
                    music_path = Path(music_file)
                    if not music_path.exists():
                        music_path = AUDIO_DIR / music_file
                else:
                    # List available music files
                    music_files = list(AUDIO_DIR.glob("*.mp3"))
                    if not music_files:
                        print("⚠ No music files found in audio/ folder, skipping background music.")
                        music_path = None
                    else:
                        music_path = music_files[0]
                        print(f"  Using default music: {music_path.name}")
                
                if music_path and music_path.exists():
                    # Create temporary path for intermediate video
                    temp_final = output_path.with_name(f"{output_path.stem}_temp{output_path.suffix}")
                    shutil.move(output_path, temp_final)
                    
                    try:
                        add_background_music(temp_final, music_path, output_path, music_volume)
                        print(f"✓ Added background music (Volume: {music_volume:.0%})")
                    except Exception as e:
                        print(f"⚠ Failed to add background music: {e}")
                        # Restore original if failed
                        shutil.move(temp_final, output_path)
                    finally:
                        if temp_final.exists():
                            temp_final.unlink()
            
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
