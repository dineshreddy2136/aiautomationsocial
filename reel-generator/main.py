#!/usr/bin/env python3
"""
Reel Generator CLI
Converts movie recap videos into short-form reels.
"""

import click
import json
import subprocess
import shutil
from pathlib import Path

from config import (
    GEMINI_API_KEY,
    TEMP_DIR,
    OUTPUT_DIR,
    VIDEOS_DIR,
    WHISPER_MODEL,
    DEFAULT_REEL_DURATION,
    validate_config
)
from modules.downloader import download_video
from modules.transcript import extract_transcript
from modules.reel_planner import plan_reels, save_reel_plans
from modules.video_cutter import generate_all_reels


def get_video_duration(video_path: Path) -> float:
    """Get video duration using ffprobe"""
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', str(video_path)],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


@click.command()
@click.option('--url', '-u', required=True, help='YouTube video URL')
@click.option('--reel-duration', '-d', default=DEFAULT_REEL_DURATION, 
              help='Target duration for each reel in seconds (default: 60)')
@click.option('--output', '-o', default=None, help='Output directory for reels')
@click.option('--generate-videos', '-g', is_flag=True, 
              help='Generate reel videos (cut & stitch clips)')
@click.option('--vertical/--landscape', default=True,
              help='Output format: --vertical (9:16 default) or --landscape (16:9)')
@click.option('--crop-style', '-c', 
              type=click.Choice(['blur', 'crop-center', 'crop-top', 'crop-bottom']), 
              default='blur',
              help='Vertical crop style: blur (default), crop-center, crop-top, crop-bottom')
@click.option('--auto-reframe', '-a', is_flag=True,
              help='Use face detection to dynamically follow speaker (basic)')
@click.option('--smart-reframe', '-s', is_flag=True,
              help='Use intelligent reframing with YOLO (recommended)')
@click.option('--reframe-style', type=click.Choice(['reactive', 'smooth']), default='reactive',
              help='Reframe style: reactive (hold-and-snap, default) or smooth (continuous interpolation)')
@click.option('--trim-bottom', '-t', default=0, type=int,
              help='Pixels to trim from bottom of source video (for removing watermarks)')
@click.option('--keep-temp', is_flag=True, help='Keep temporary files')
def main(url: str, reel_duration: int, output: str, generate_videos: bool, vertical: bool, 
         crop_style: str, auto_reframe: bool, smart_reframe: bool, reframe_style: str, 
         trim_bottom: int, keep_temp: bool):
    """
    Generate reels from a YouTube video.
    
    Downloads the video, extracts transcript, uses AI to create reel plans,
    and optionally generates the actual reel videos.
    """
    print("=" * 50)
    print("🎬 Reel Generator")
    print("=" * 50)
    
    # Validate configuration
    try:
        validate_config()
    except ValueError as e:
        click.echo(f"\n❌ Configuration Error:\n{e}", err=True)
        click.echo("\nPlease copy .env.example to .env and add your API keys.", err=True)
        return
    
    try:
        # Step 1: Download video
        print("\n📥 Step 1/4: Downloading video...")
        video_path, video_title = download_video(url, TEMP_DIR)
        video_duration = get_video_duration(video_path)
        print(f"   Duration: {video_duration/60:.1f} minutes")
        
        # Step 2: Extract transcript with stable-ts
        print("\n📄 Step 2/4: Extracting transcript with stable-ts...")
        segments = extract_transcript(video_path=video_path)
        
        if not segments:
            click.echo("❌ Could not extract any transcript from the video", err=True)
            return
        
        print(f"   Found {len(segments)} transcript segments")
        
        # Step 3: Generate reel plans
        print("\n🎯 Step 3/4: Generating reel plans with AI...")
        reel_plans = plan_reels(
            segments=segments,
            api_key=GEMINI_API_KEY,
            video_duration=video_duration,
            target_reel_duration=reel_duration
        )
        
        # Determine output directory
        safe_title = "".join(c for c in video_title if c.isalnum() or c in ' -_')[:30]
        if output:
            output_dir = Path(output)
        else:
            output_dir = OUTPUT_DIR / safe_title
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save reel plans JSON
        plans_path = output_dir / "reel_plans.json"
        save_reel_plans(reel_plans, plans_path)
        
        # Step 4: Generate reel videos (optional)
        reel_videos = []
        if generate_videos:
            print("\n🎬 Step 4/4: Cutting and stitching reel videos...")
            reel_videos = generate_all_reels(
                video_path=video_path,
                reel_plans_path=plans_path,
                output_dir=output_dir / "reels",
                temp_dir=TEMP_DIR / "clips",
                vertical=vertical,
                crop_style=crop_style,
                trim_bottom=trim_bottom,
                auto_reframe=auto_reframe,
                smart_reframe=smart_reframe,
                api_key=GEMINI_API_KEY,
                reframe_style=reframe_style
            )
        else:
            print("\n⏭️  Step 4/4: Skipped (use --generate-videos to create reel videos)")
        
        # Print summary
        print("\n" + "=" * 50)
        print("✅ Complete!")
        print("=" * 50)
        print(f"\n📁 Output Directory: {output_dir}")
        print(f"📋 Reel Plans: {plans_path}")
        print(f"🎬 Total Reels: {len(reel_plans)}")
        
        for i, reel in enumerate(reel_plans):
            print(f"\n  📹 {reel.title}")
            print(f"     🔥 Virality: {reel.virality_score}/100")
            print(f"     🤔 Reasoning: {reel.reasoning}")
            print(f"     Clips: {len(reel.clips)} | Duration: {reel.total_duration:.1f}s")
            if reel_videos and i < len(reel_videos):
                print(f"     Video: {reel_videos[i].name}")
            print(f"     Narration: {reel.narration_script[:60]}...")
        
        # Save downloaded video to videos folder
        saved_video_path = VIDEOS_DIR / video_path.name
        if video_path.exists() and not saved_video_path.exists():
            shutil.copy2(video_path, saved_video_path)
            print(f"\n💾 Saved video to: {saved_video_path}")
        
        # Cleanup temp files
        if not keep_temp:
            print("🧹 Cleaning up temporary files...")
            shutil.rmtree(TEMP_DIR, ignore_errors=True)
            TEMP_DIR.mkdir(exist_ok=True)
        
    except Exception as e:
        click.echo(f"\n❌ Error: {e}", err=True)
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
