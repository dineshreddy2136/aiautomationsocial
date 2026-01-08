#!/usr/bin/env python3
"""
Cut reels from an existing JSON plan and video file.
Usage: python cut_reels.py --video <path> --plan <json_path>
"""

import click
from pathlib import Path
from modules.video_cutter import generate_all_reels
from config import TEMP_DIR, OUTPUT_DIR, GEMINI_API_KEY


CROP_STYLES = ['blur', 'crop-center', 'crop-top', 'crop-bottom']


@click.command()
@click.option('--video', '-v', required=True, help='Path to source video file')
@click.option('--plan', '-p', required=True, help='Path to reel plans JSON file')
@click.option('--output', '-o', default=None, help='Output directory for reel videos')
@click.option('--vertical/--landscape', default=True, 
              help='Output format: --vertical (9:16 default) or --landscape (16:9)')
@click.option('--crop-style', '-c', type=click.Choice(CROP_STYLES), default='blur',
              help='Vertical crop style: blur (default), crop-center, crop-top, crop-bottom')
@click.option('--auto-reframe', '-a', is_flag=True,
              help='Use face detection to dynamically follow speaker (basic)')
@click.option('--smart-reframe', '-s', is_flag=True,
              help='Use intelligent reframing with YOLO (recommended)')
@click.option('--reframe-style', type=click.Choice(['reactive', 'smooth']), default='reactive',
              help='Reframe style: reactive (hold-and-snap, default) or smooth (continuous interpolation)')
@click.option('--trim-bottom', '-t', default=0, type=int,
              help='Pixels to trim from bottom of source video (for removing watermarks)')
def main(video: str, plan: str, output: str, vertical: bool, crop_style: str, 
         auto_reframe: bool, smart_reframe: bool, reframe_style: str, trim_bottom: int):
    """Cut and stitch reel videos from an existing plan."""
    
    video_path = Path(video)
    plan_path = Path(plan)
    
    if not video_path.exists():
        click.echo(f"❌ Video not found: {video_path}", err=True)
        return
    
    if not plan_path.exists():
        click.echo(f"❌ Plan not found: {plan_path}", err=True)
        return
    
    # Determine output directory
    if output:
        output_dir = Path(output)
    else:
        output_dir = plan_path.parent / "reels"
    
    print("=" * 50)
    print("🎬 Cutting Reels from Plan")
    print("=" * 50)
    print(f"\n📹 Video: {video_path}")
    print(f"📋 Plan: {plan_path}")
    print(f"📁 Output: {output_dir}")
    print(f"📐 Format: {'Vertical (9:16)' if vertical else 'Landscape (16:9)'}")
    if vertical:
        if smart_reframe:
            print(f"🧠 Mode: Smart Reframe ({reframe_style})")
        elif auto_reframe:
            print(f"🎯 Mode: Auto-Reframe (Face Detection)")
        else:
            print(f"✂️  Crop Style: {crop_style}")
    if trim_bottom > 0:
        print(f"✂️  Trim Bottom: {trim_bottom}px")
    
    print("\n🎬 Cutting and stitching reel videos...")
    
    reel_videos = generate_all_reels(
        video_path=video_path,
        reel_plans_path=plan_path,
        output_dir=output_dir,
        temp_dir=TEMP_DIR / "clips",
        vertical=vertical,
        crop_style=crop_style,
        trim_bottom=trim_bottom,
        auto_reframe=auto_reframe,
        smart_reframe=smart_reframe,
        api_key=GEMINI_API_KEY,
        reframe_style=reframe_style
    )
    
    print("\n" + "=" * 50)
    print("✅ Done!")
    print("=" * 50)
    print(f"\n📁 Output: {output_dir}")
    print(f"🎬 Generated {len(reel_videos)} reels:")
    
    for reel in reel_videos:
        print(f"   • {reel.name}")


if __name__ == "__main__":
    main()
