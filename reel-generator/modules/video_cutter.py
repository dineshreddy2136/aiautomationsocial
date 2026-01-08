"""
Video Cutter Module
Uses FFmpeg to cut clips and stitch them into reels
"""

import subprocess
import json
from pathlib import Path
from typing import List
from dataclasses import dataclass

from modules.reframing import cut_clip_with_reframe
from modules.smart_reframe import cut_clip_with_smart_reframe


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
    output_path: Path,
    vertical: bool = True,
    crop_style: str = "blur",
    trim_bottom: int = 0
) -> Path:
    """
    Cut a single clip from the video and optionally convert to vertical format.
    
    Args:
        video_path: Source video path
        start: Start time in seconds
        end: End time in seconds
        output_path: Output clip path
        vertical: If True, convert to 9:16 vertical format (1080x1920)
        crop_style: How to convert to vertical format:
            - 'blur': Fit video in center with blurred background (default)
            - 'crop-center': Center crop to 9:16 (cuts off sides)
            - 'crop-top': Crop with focus on top (cuts off bottom)
            - 'crop-bottom': Crop with focus on bottom (cuts off top)
        trim_bottom: Pixels to crop from bottom of source video (for removing watermarks)
        
    Returns:
        Path to the cut clip
    """
    duration = end - start
    
    # Pre-crop filter to trim bottom pixels (if specified)
    precrop = f"crop=iw:ih-{trim_bottom}:0:0," if trim_bottom > 0 else ""
    
    if vertical:
        if crop_style == "blur":
            # Convert landscape to vertical with blurred background
            filter_complex = (
                f"[0:v]{precrop}split[a][b];"
                "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg];"
                "[b]scale=1080:-1:force_original_aspect_ratio=decrease[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2"
            )
        elif crop_style == "crop-center":
            # Center crop - cuts off sides, keeps center
            filter_complex = (
                f"[0:v]{precrop}scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920:(iw-1080)/2:(ih-1920)/2"
            )
        elif crop_style == "crop-top":
            # Top crop - focus on top of video, cuts off bottom
            filter_complex = (
                f"[0:v]{precrop}scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920:(iw-1080)/2:0"
            )
        elif crop_style == "crop-bottom":
            # Bottom crop - focus on bottom of video, cuts off top
            filter_complex = (
                f"[0:v]{precrop}scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920:(iw-1080)/2:ih-1920"
            )
        else:
            raise ValueError(f"Invalid crop_style: {crop_style}")
        
        cmd = [
            'ffmpeg', '-y',
            '-ss', str(start),
            '-i', str(video_path),
            '-t', str(duration),
            '-filter_complex', filter_complex,
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-c:a', 'aac',
            '-b:a', '128k',
            str(output_path)
        ]
    else:
        # Keep original format (landscape), but apply trim if specified
        if trim_bottom > 0:
            vf = f"crop=iw:ih-{trim_bottom}:0:0"
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(start),
                '-i', str(video_path),
                '-t', str(duration),
                '-vf', vf,
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-c:a', 'aac',
                '-b:a', '128k',
                str(output_path)
            ]
        else:
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
    temp_dir: Path,
    vertical: bool = True,
    crop_style: str = "blur",
    trim_bottom: int = 0,
    auto_reframe: bool = False,
    smart_reframe: bool = False,
    api_key: str = "",
    reel_narration: str = "",
    reframe_style: str = "reactive"
) -> Path:
    """
    Generate a single reel video from clips.
    
    Args:
        video_path: Source video path
        clips: List of clip dictionaries with 'start' and 'end'
        output_path: Output reel video path
        temp_dir: Temporary directory for intermediate files
        vertical: If True, convert to 9:16 vertical format
        crop_style: Crop style for vertical: 'blur', 'crop-center', 'crop-top', 'crop-bottom'
        trim_bottom: Pixels to trim from bottom of source video
        auto_reframe: If True, use face detection to dynamically crop (basic)
        smart_reframe: If True, use intelligent reframing
        api_key: Gemini API key (deprecated)
        reel_narration: Narration script for context
        reframe_style: 'reactive' (hold-and-snap) or 'smooth' (continuous interpolation)
        
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
        
        if smart_reframe and vertical:
            # Use intelligent reframing with shot type
            shot_type = clip.get('shot_type', 'focus')
            cut_clip_with_smart_reframe(
                video_path, clip['start'], clip['end'], clip_output,
                transcript_context=reel_narration,
                trim_bottom=trim_bottom,
                reframe_style=reframe_style,
                shot_type=shot_type
            )
        elif auto_reframe and vertical:
            # Use face detection for dynamic cropping (basic)
            cut_clip_with_reframe(video_path, clip['start'], clip['end'], clip_output, trim_bottom=trim_bottom)
        else:
            # Use static cropping
            cut_clip(video_path, clip['start'], clip['end'], clip_output, vertical=vertical, crop_style=crop_style, trim_bottom=trim_bottom)
        
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
    temp_dir: Path,
    vertical: bool = True,
    crop_style: str = "blur",
    trim_bottom: int = 0,
    auto_reframe: bool = False,
    smart_reframe: bool = False,
    api_key: str = "",
    reframe_style: str = "reactive"
) -> List[Path]:
    """
    Generate all reel videos from a reel plans JSON file.
    
    Args:
        video_path: Source video path
        reel_plans_path: Path to reel plans JSON
        output_dir: Directory for output reel videos
        temp_dir: Temporary directory for intermediate files
        vertical: If True, convert to 9:16 vertical format
        crop_style: Crop style for vertical
        trim_bottom: Pixels to trim from bottom of source video
        auto_reframe: If True, use face detection for dynamic cropping (basic)
        smart_reframe: If True, use intelligent reframing
        api_key: Gemini API key (deprecated)
        reframe_style: 'reactive' (hold-and-snap) or 'smooth' (continuous interpolation)
        
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
        
        # Get narration for context
        narration = reel.get('narration_script', '')
        
        print(f"\n  📹 Generating Reel {reel_num}: {reel['title']}")
        if smart_reframe:
            print(f"    🧠 Using Smart Reframe ({reframe_style})")
        elif auto_reframe:
            print(f"    🎯 Using Auto Reframe (face detection)")
        
        generate_reel_video(
            video_path=video_path,
            clips=reel['clips'],
            output_path=output_path,
            temp_dir=temp_dir / f"reel_{reel_num}",
            vertical=vertical,
            crop_style=crop_style,
            trim_bottom=trim_bottom,
            auto_reframe=auto_reframe,
            smart_reframe=smart_reframe,
            api_key=api_key,
            reel_narration=narration,
            reframe_style=reframe_style
        )
        
        print(f"    ✓ Saved: {output_path.name}")
        reel_videos.append(output_path)
    
    return reel_videos

