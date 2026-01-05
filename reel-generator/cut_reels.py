#!/usr/bin/env python3
"""
Cut reels from an existing JSON plan and video file.
Usage: python cut_reels.py --video <path> --plan <json_path>
"""

import click
from pathlib import Path
from modules.video_cutter import generate_all_reels
from config import TEMP_DIR, OUTPUT_DIR


@click.command()
@click.option('--video', '-v', required=True, help='Path to source video file')
@click.option('--plan', '-p', required=True, help='Path to reel plans JSON file')
@click.option('--output', '-o', default=None, help='Output directory for reel videos')
def main(video: str, plan: str, output: str):
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
    
    print("\n🎬 Cutting and stitching reel videos...")
    
    reel_videos = generate_all_reels(
        video_path=video_path,
        reel_plans_path=plan_path,
        output_dir=output_dir,
        temp_dir=TEMP_DIR / "clips"
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
