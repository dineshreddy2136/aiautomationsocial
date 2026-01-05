"""
Video Cutter Module
Uses FFmpeg to cut clips and stitch them into reels
"""

import subprocess
import json
from pathlib import Path
from typing import List
from dataclasses import dataclass


@dataclass 
class ClipInfo:
    """Info for a single clip to cut"""
    start: float
    end: float
    description: str = ""


def cut_clip(
    video_path: Path,
    start: float,
    end: float,
    output_path: Path
) -> Path:
    """
    Cut a single clip from the video.
    
    Args:
        video_path: Source video path
        start: Start time in seconds
        end: End time in seconds
        output_path: Output clip path
        
    Returns:
        Path to the cut clip
    """
    duration = end - start
    
    # Use FFmpeg to cut the clip
    # -ss before -i for fast seeking
    # Re-encode for frame-accurate cuts
    cmd = [
        'ffmpeg', '-y',
        '-ss', str(start),
        '-i', str(video_path),
        '-t', str(duration),
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-c:a', 'aac',
        '-b:a', '128k',
        str(output_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg clip cut failed: {result.stderr.decode()}")
    
    return output_path


def stitch_clips(
    clip_paths: List[Path],
    output_path: Path
) -> Path:
    """
    Stitch multiple clips together using FFmpeg concat.
    
    Args:
        clip_paths: List of clip file paths
        output_path: Output stitched video path
        
    Returns:
        Path to the stitched video
    """
    # Create a concat file list
    concat_file = output_path.parent / "concat_list.txt"
    with open(concat_file, 'w') as f:
        for clip_path in clip_paths:
            f.write(f"file '{clip_path}'\n")
    
    # Use FFmpeg concat demuxer
    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat',
        '-safe', '0',
        '-i', str(concat_file),
        '-c', 'copy',
        str(output_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True)
    
    # Cleanup concat file
    concat_file.unlink()
    
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg concat failed: {result.stderr.decode()}")
    
    return output_path


def generate_reel_video(
    video_path: Path,
    clips: List[dict],
    output_path: Path,
    temp_dir: Path
) -> Path:
    """
    Generate a single reel video from clips.
    
    Args:
        video_path: Source video path
        clips: List of clip dictionaries with 'start' and 'end'
        output_path: Output reel video path
        temp_dir: Temporary directory for intermediate files
        
    Returns:
        Path to the generated reel video
    """
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    clip_paths = []
    
    # Cut each clip
    for i, clip in enumerate(clips):
        clip_output = temp_dir / f"clip_{i:03d}.mp4"
        print(f"    Cutting clip {i+1}/{len(clips)}: {clip['start']:.1f}s - {clip['end']:.1f}s")
        cut_clip(video_path, clip['start'], clip['end'], clip_output)
        clip_paths.append(clip_output)
    
    # Stitch clips together
    print(f"    Stitching {len(clip_paths)} clips...")
    stitch_clips(clip_paths, output_path)
    
    # Cleanup temp clips
    for clip_path in clip_paths:
        clip_path.unlink()
    
    return output_path


def generate_all_reels(
    video_path: Path,
    reel_plans_path: Path,
    output_dir: Path,
    temp_dir: Path
) -> List[Path]:
    """
    Generate all reel videos from a reel plans JSON file.
    
    Args:
        video_path: Source video path
        reel_plans_path: Path to reel plans JSON
        output_dir: Directory for output reel videos
        temp_dir: Temporary directory for intermediate files
        
    Returns:
        List of paths to generated reel videos
    """
    # Load reel plans
    with open(reel_plans_path, 'r') as f:
        data = json.load(f)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    reel_videos = []
    
    for reel in data['reels']:
        reel_num = reel['reel_number']
        title = reel['title'].replace(' ', '_').replace('-', '_')
        output_path = output_dir / f"reel_{reel_num:02d}_{title[:30]}.mp4"
        
        print(f"\n  📹 Generating Reel {reel_num}: {reel['title']}")
        
        generate_reel_video(
            video_path=video_path,
            clips=reel['clips'],
            output_path=output_path,
            temp_dir=temp_dir / f"reel_{reel_num}"
        )
        
        print(f"    ✓ Saved: {output_path.name}")
        reel_videos.append(output_path)
    
    return reel_videos
