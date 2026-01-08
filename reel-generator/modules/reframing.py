"""
Reframing Module - Auto-reframe video to follow faces (OpusClip style)
Uses MediaPipe Face Detection to track faces and dynamically crop.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional
import subprocess
import tempfile


def detect_faces_in_video(
    video_path: Path,
    sample_interval: float = 0.5
) -> List[Tuple[float, Optional[Tuple[int, int]]]]:
    """
    Sample video at intervals and detect face center positions.
    
    Args:
        video_path: Path to video file
        sample_interval: Seconds between samples (default 0.5s for performance)
        
    Returns:
        List of (timestamp, (x_center, y_center)) or (timestamp, None) if no face
    """
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    
    # Download model if not exists
    import urllib.request
    import os
    
    model_path = Path(__file__).parent / "face_detector.tflite"
    if not model_path.exists():
        print("    Downloading face detection model...")
        url = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
        urllib.request.urlretrieve(url, str(model_path))
    
    # Create face detector
    base_options = python.BaseOptions(model_asset_path=str(model_path))
    options = vision.FaceDetectorOptions(base_options=base_options)
    detector = vision.FaceDetector.create_from_options(options)
    
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = int(fps * sample_interval)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    face_positions = []
    frame_idx = 0
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        
        if frame_idx % frame_interval == 0:
            timestamp = frame_idx / fps
            
            # Convert BGR to RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            
            results = detector.detect(mp_image)
            
            if results.detections:
                # Use the largest/most prominent face
                best_detection = max(
                    results.detections,
                    key=lambda d: d.bounding_box.width * d.bounding_box.height
                )
                
                bbox = best_detection.bounding_box
                # Calculate center in pixels
                x_center = bbox.origin_x + bbox.width // 2
                y_center = bbox.origin_y + bbox.height // 2
                
                face_positions.append((timestamp, (x_center, y_center)))
            else:
                face_positions.append((timestamp, None))
        
        frame_idx += 1
    
    cap.release()
    detector.close()
    return face_positions


def smooth_positions(
    positions: List[Tuple[float, Optional[Tuple[int, int]]]],
    video_width: int,
    window_size: int = 15,
    dead_zone_percent: float = 0.15,
    max_pan_per_second: float = 0.1
) -> List[Tuple[float, int]]:
    """
    Smooth face X positions with dead zone and max pan speed for natural movement.
    
    Args:
        positions: List of (timestamp, (x, y) or None)
        video_width: Original video width for bounds
        window_size: Moving average window size (larger = smoother)
        dead_zone_percent: Only pan if face moves beyond this % of frame width
        max_pan_per_second: Maximum pan speed as fraction of frame width per second
        
    Returns:
        List of (timestamp, smoothed_x_center)
    """
    if not positions:
        return []
    
    # Extract x positions, using video center for missing detections
    default_x = video_width // 2
    x_values = []
    timestamps = []
    
    for ts, pos in positions:
        timestamps.append(ts)
        if pos is not None:
            x_values.append(pos[0])
        elif x_values:  # Use last known position
            x_values.append(x_values[-1])
        else:
            x_values.append(default_x)
    
    # Step 1: Apply moving average for initial smoothing
    smoothed_x = []
    for i in range(len(x_values)):
        start = max(0, i - window_size // 2)
        end = min(len(x_values), i + window_size // 2 + 1)
        avg = int(sum(x_values[start:end]) / (end - start))
        smoothed_x.append(avg)
    
    # Step 2: Apply dead zone - only update target if face moved significantly
    dead_zone_px = int(video_width * dead_zone_percent)
    current_target = smoothed_x[0] if smoothed_x else default_x
    targets = []
    
    for x in smoothed_x:
        if abs(x - current_target) > dead_zone_px:
            current_target = x  # Update target only if moved beyond dead zone
        targets.append(current_target)
    
    # Step 3: Apply max pan speed - limit how fast we can move
    max_pan_px = int(video_width * max_pan_per_second)
    final_positions = []
    current_pos = targets[0] if targets else default_x
    
    for i, (ts, target) in enumerate(zip(timestamps, targets)):
        if i == 0:
            final_positions.append((ts, target))
            current_pos = target
        else:
            # Calculate time delta
            dt = ts - timestamps[i - 1]
            max_move = int(max_pan_px * dt)
            
            # Move towards target, but limited by max speed
            diff = target - current_pos
            if abs(diff) <= max_move:
                current_pos = target
            else:
                current_pos = current_pos + (max_move if diff > 0 else -max_move)
            
            final_positions.append((ts, current_pos))
    
    return final_positions


def generate_crop_keyframes(
    smoothed_positions: List[Tuple[float, int]],
    video_width: int,
    video_height: int,
    output_width: int = 1080,
    output_height: int = 1920
) -> List[Tuple[float, int]]:
    """
    Generate FFmpeg-compatible crop X positions for each keyframe.
    
    Args:
        smoothed_positions: List of (timestamp, smoothed_x_center)
        video_width: Original video width
        video_height: Original video height
        output_width: Target crop width (9:16 = 1080)
        output_height: Target crop height (9:16 = 1920)
        
    Returns:
        List of (timestamp, crop_x) where crop_x is the left edge of crop window
    """
    # Calculate the crop width needed to get 9:16 from the source
    # We scale to fit height, then crop width
    scale_factor = output_height / video_height
    scaled_width = int(video_width * scale_factor)
    
    # The crop width at the scaled resolution
    crop_width_at_scale = output_width
    
    # Convert back to original resolution
    crop_width_original = int(crop_width_at_scale / scale_factor)
    
    keyframes = []
    for ts, x_center in smoothed_positions:
        # Calculate crop X (left edge) centered on face
        crop_x = x_center - crop_width_original // 2
        
        # Clamp to video bounds
        crop_x = max(0, min(crop_x, video_width - crop_width_original))
        
        keyframes.append((ts, crop_x))
    
    return keyframes


def create_reframe_filter(
    keyframes: List[Tuple[float, int]],
    video_width: int,
    video_height: int
) -> str:
    """
    Create FFmpeg filter_complex string for dynamic cropping.
    
    Uses sendcmd to update crop X position over time.
    """
    # Calculate crop width for 9:16 aspect
    target_aspect = 9 / 16
    crop_height = video_height
    crop_width = int(crop_height * target_aspect)
    
    if len(keyframes) < 2:
        # Static center crop if not enough keyframes
        crop_x = (video_width - crop_width) // 2
        return f"crop={crop_width}:{crop_height}:{crop_x}:0,scale=1080:1920"
    
    # Build expression for X position using linear interpolation
    # FFmpeg expression: between(t,start,end)*(x0 + (x1-x0)*(t-start)/(end-start))
    expr_parts = []
    for i in range(len(keyframes) - 1):
        t0, x0 = keyframes[i]
        t1, x1 = keyframes[i + 1]
        
        # Linear interpolation between keyframes
        part = f"between(t,{t0:.2f},{t1:.2f})*({x0}+({x1}-{x0})*(t-{t0:.2f})/({t1:.2f}-{t0:.2f}))"
        expr_parts.append(part)
    
    # Add final segment (hold last position)
    last_t, last_x = keyframes[-1]
    expr_parts.append(f"gte(t,{last_t:.2f})*{last_x}")
    
    x_expr = "+".join(expr_parts)
    
    return f"crop={crop_width}:{crop_height}:'{x_expr}':0,scale=1080:1920"


def cut_clip_with_reframe(
    video_path: Path,
    start: float,
    end: float,
    output_path: Path,
    trim_bottom: int = 0
) -> Path:
    """
    Cut a clip with auto-reframing (face following).
    
    Args:
        video_path: Source video
        start: Start time in seconds
        end: End time in seconds
        output_path: Output path
        trim_bottom: Pixels to trim from bottom before processing
        
    Returns:
        Path to output clip
    """
    duration = end - start
    
    # First, extract the segment to analyze
    temp_segment = output_path.parent / f"_temp_segment_{output_path.stem}.mp4"
    
    # Extract segment for face detection
    extract_cmd = [
        'ffmpeg', '-y',
        '-ss', str(start),
        '-i', str(video_path),
        '-t', str(duration),
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-c:a', 'aac',
        str(temp_segment)
    ]
    
    subprocess.run(extract_cmd, capture_output=True, check=True)
    
    # Detect faces in segment
    face_positions = detect_faces_in_video(temp_segment, sample_interval=0.25)
    
    # Get video dimensions
    cap = cv2.VideoCapture(str(temp_segment))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) - trim_bottom
    cap.release()
    
    # Smooth positions
    smoothed = smooth_positions(face_positions, width, window_size=7)
    
    # Generate keyframes
    keyframes = generate_crop_keyframes(smoothed, width, height)
    
    # Create filter
    reframe_filter = create_reframe_filter(keyframes, width, height)
    
    # Apply pre-crop for trim_bottom if needed
    if trim_bottom > 0:
        full_filter = f"crop=iw:ih-{trim_bottom}:0:0,{reframe_filter}"
    else:
        full_filter = reframe_filter
    
    # Final encode with reframing
    final_cmd = [
        'ffmpeg', '-y',
        '-i', str(temp_segment),
        '-vf', full_filter,
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-c:a', 'aac',
        '-b:a', '128k',
        str(output_path)
    ]
    
    result = subprocess.run(final_cmd, capture_output=True)
    
    # Cleanup temp file
    if temp_segment.exists():
        temp_segment.unlink()
    
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg reframe failed: {result.stderr.decode()}")
    
    return output_path
