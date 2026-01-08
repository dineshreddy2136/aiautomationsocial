"""
Smart Reframing Module - Intelligent auto-reframe
Uses YOLO object detection and motion analysis for context-aware framing decisions.
"""

import cv2
import json
import re
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
import subprocess

from modules.scene_analyzer import SceneAnalyzer, FrameAnalysis, SceneType



# Global analyzer cache to avoid reloading YOLO model for each clip
_analyzer_cache: Optional[SceneAnalyzer] = None


def get_scene_analyzer(model_size: str = "x") -> SceneAnalyzer:
    """Get or create a cached SceneAnalyzer instance"""
    global _analyzer_cache
    if _analyzer_cache is None:
        _analyzer_cache = SceneAnalyzer(model_size=model_size)
    return _analyzer_cache


@dataclass
class SmartKeyframe:
    """A keyframe with intelligent focus information"""
    timestamp: float
    focus_x: int  # pixel position
    focus_y: int
    source: str  # 'face', 'person', 'motion', 'center'
    confidence: float
    is_scene_change: bool = False


@dataclass
class Anchor:
    """Locked crop position for static-reactive mode"""
    focus_x: int
    focus_y: int
    locked_box: Tuple[int, int, int, int]  # x1, y1, x2, y2 of 9:16 crop area
    source: str  # 'face', 'person', 'motion', 'center'
    start_time: float
    confidence: float


def generate_smart_keyframes(
    video_path: Path,
    start: float,
    end: float,
    transcript_context: str = "",
    api_key: str = "",
    sample_interval: float = 0.5,
    use_llm: bool = False,  # Deprecated, kept for compatibility
    llm_threshold: float = 0.6  # Deprecated, kept for compatibility
) -> List[SmartKeyframe]:
    """
    Generate intelligent keyframes for dynamic cropping.
    Uses YOLO + motion detection (no LLM API calls).
    
    Args:
        video_path: Source video
        start: Start time in seconds
        end: End time in seconds
        transcript_context: Unused, kept for compatibility
        api_key: Unused, kept for compatibility
        sample_interval: Seconds between keyframes
        use_llm: Deprecated, always False
        llm_threshold: Deprecated, unused
        
    Returns:
        List of SmartKeyframe objects
    """
    # Extract segment first for analysis
    temp_segment = video_path.parent / f"_temp_smart_{video_path.stem}_{start:.0f}.mp4"
    duration = end - start
    
    extract_cmd = [
        'ffmpeg', '-y',
        '-ss', str(start),
        '-i', str(video_path),
        '-t', str(duration),
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-an',  # No audio for analysis
        str(temp_segment)
    ]
    subprocess.run(extract_cmd, capture_output=True, check=True)
    
    # Get video dimensions
    cap = cv2.VideoCapture(str(temp_segment))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    
    # Analyze video with cached scene analyzer (avoids YOLO reload)
    analyzer = get_scene_analyzer(model_size="x")
    print(f"      Analyzing {duration:.1f}s clip with YOLO + motion detection...")
    analyses = analyzer.analyze_video_segment(
        temp_segment, 
        start=0, 
        end=duration,
        sample_interval=sample_interval
    )
    
    # Convert analyses to keyframes (no LLM, pure YOLO + motion)
    keyframes = []
    
    for analysis in analyses:
        focus_x, focus_y = analysis.suggested_focus
        source = "scene_analysis"
        confidence = analysis.confidence
        
        # Determine source based on what drove the decision
        if analysis.scene_type == SceneType.DIALOGUE and analysis.faces:
            source = "face"
        elif analysis.scene_type == SceneType.ACTION:
            source = "motion"
        elif analysis.scene_type == SceneType.TEXT:
            source = "center"
        
        keyframes.append(SmartKeyframe(
            timestamp=analysis.timestamp,
            focus_x=focus_x,
            focus_y=focus_y,
            source=source,
            confidence=confidence,
            is_scene_change=analysis.is_scene_change
        ))
    
    # CRITICAL: Prepend t=0 keyframe for instant centering on first frame
    if keyframes and keyframes[0].timestamp > 0:
        # Insert a t=0 keyframe with the same position as first detected keyframe
        t0_keyframe = SmartKeyframe(
            timestamp=0.0,
            focus_x=keyframes[0].focus_x,
            focus_y=keyframes[0].focus_y,
            source=keyframes[0].source,
            confidence=keyframes[0].confidence,
            is_scene_change=True  # Treat start as a scene cut to force reset
        )
        keyframes.insert(0, t0_keyframe)
    
    # Cleanup temp file
    if temp_segment.exists():
        temp_segment.unlink()
    
    return keyframes



def smooth_keyframes(
    keyframes: List[SmartKeyframe],
    video_width: int,
    window_size: int = 5,
    dead_zone_percent: float = 0.12,
    max_pan_per_second: float = 0.15
) -> List[SmartKeyframe]:
    """
    Apply smoothing to keyframes for natural camera movement.
    Now respects scene cuts to prevent smoothing across different scenes.
    """
    if len(keyframes) < 2:
        return keyframes
    
    # Extract data
    x_values = [kf.focus_x for kf in keyframes]
    timestamps = [kf.timestamp for kf in keyframes]
    is_cut_flags = [kf.is_scene_change for kf in keyframes]
    
    # Step 1: Moving average (scene-aware)
    smoothed_x = []
    for i in range(len(x_values)):
        if is_cut_flags[i]:
            # Scene cut: use exact position, no smoothing
            smoothed_x.append(x_values[i])
            continue
            
        # Determine valid window that doesn't cross scene cuts
        # Look back
        start_search = max(0, i - window_size // 2)
        valid_start = i
        for idx in range(i - 1, start_search - 1, -1):
            if is_cut_flags[idx + 1]: # If idx+1 is a cut start, stopping at idx
                valid_start = idx + 1
                break
            valid_start = idx
            
        # Look forward
        end_search = min(len(x_values), i + window_size // 2 + 1)
        valid_end = i + 1
        for idx in range(i + 1, end_search):
            if is_cut_flags[idx]: # If idx is a cut, don't include it
                break
            valid_end = idx + 1
            
        # Compute avg
        avg = int(sum(x_values[valid_start:valid_end]) / (valid_end - valid_start))
        smoothed_x.append(avg)
    
    # Step 2: Dead zone (reset on cut)
    dead_zone_px = int(video_width * dead_zone_percent)
    current_target = smoothed_x[0]
    targets = []
    
    for i, x in enumerate(smoothed_x):
        if is_cut_flags[i]:
            # Hard reset target on cut
            current_target = x
            targets.append(current_target)
        elif abs(x - current_target) > dead_zone_px:
            current_target = x
            targets.append(current_target)
        else:
            targets.append(current_target)
    
    # Step 3: Max pan speed (reset on cut)
    max_pan_px = int(video_width * max_pan_per_second)
    final_x = []
    current_pos = targets[0]
    
    for i in range(len(targets)):
        if is_cut_flags[i] or i == 0:
            # Instant jump on cut or start
            final_x.append(targets[i])
            current_pos = targets[i]
        else:
            dt = timestamps[i] - timestamps[i - 1]
            max_move = int(max_pan_px * dt)
            diff = targets[i] - current_pos
            
            if abs(diff) <= max_move:
                current_pos = targets[i]
            else:
                current_pos = current_pos + (max_move if diff > 0 else -max_move)
            
            final_x.append(current_pos)
    
    # Create new smoothed keyframes
    new_keyframes = []
    for i in range(len(keyframes)):
        new_keyframes.append(SmartKeyframe(
            timestamp=keyframes[i].timestamp,
            focus_x=int(final_x[i]),
            focus_y=keyframes[i].focus_y,
            source=keyframes[i].source,
            confidence=keyframes[i].confidence,
            is_scene_change=keyframes[i].is_scene_change
        ))
        
    return new_keyframes


def create_smart_reframe_filter(
    keyframes: List[SmartKeyframe],
    video_width: int,
    video_height: int,
    trim_bottom: int = 0
) -> str:
    """
    Create FFmpeg filter string for dynamic cropping based on keyframes.
    Uses 'hold' logic for scene cuts to prevent swooshing.
    """
    # Apply trim if needed
    effective_height = video_height - trim_bottom
    
    # Calculate crop dimensions for 9:16
    target_aspect = 9 / 16
    crop_height = effective_height
    crop_width = int(crop_height * target_aspect)
    
    # Ensure crop fits
    if crop_width > video_width:
        crop_width = video_width
        crop_height = int(crop_width / target_aspect)
    
    if len(keyframes) < 2:
        # Static center crop
        crop_x = (video_width - crop_width) // 2
        filter_str = f"crop={crop_width}:{crop_height}:{crop_x}:0"
        if trim_bottom > 0:
            filter_str = f"crop=iw:ih-{trim_bottom}:0:0," + filter_str
        return filter_str + ",scale=1080:1920"
    
    # Build interpolated X expression
    expr_parts = []
    
    # CRITICAL FIX: Hold first keyframe position from t=0 until first keyframe
    first_x = keyframes[0].focus_x - crop_width // 2
    first_x = max(0, min(first_x, video_width - crop_width))
    first_t = keyframes[0].timestamp
    
    if first_t > 0:
        # Add expression to hold first position from t=0 to first keyframe
        expr_parts.append(f"lt(t,{first_t:.2f})*{first_x}")
    
    for i in range(len(keyframes) - 1):
        t0 = keyframes[i].timestamp
        t1 = keyframes[i + 1].timestamp
        x0 = keyframes[i].focus_x - crop_width // 2
        x1 = keyframes[i + 1].focus_x - crop_width // 2
        
        # Clamp to bounds
        x0 = max(0, min(x0, video_width - crop_width))
        x1 = max(0, min(x1, video_width - crop_width))
        
        # Check if next frame is a scene change
        # If t1 starts a new scene, we should HOLD x0 until t1, then jump
        if keyframes[i + 1].is_scene_change:
            # Hold x0 for the entire duration (t0 -> t1)
            # The jump happens at t1 when the NEXT segment starts (or explicitly here)
            # Actually, the expression is summing parts. 
            # Part for [t0, t1]: just equal x0
            part = f"between(t,{t0:.2f},{t1:.2f})*{x0}"
        else:
            # Normal interpolation (pan)
            part = f"between(t,{t0:.2f},{t1:.2f})*({x0}+({x1}-{x0})*(t-{t0:.2f})/({t1:.2f}-{t0:.2f}+0.001))"
            
        expr_parts.append(part)
    
    # Hold last position
    last_x = keyframes[-1].focus_x - crop_width // 2
    last_x = max(0, min(last_x, video_width - crop_width))
    expr_parts.append(f"gte(t,{keyframes[-1].timestamp:.2f})*{last_x}")
    
    x_expr = "+".join(expr_parts)
    
    filter_str = f"crop={crop_width}:{crop_height}:'{x_expr}':0"
    if trim_bottom > 0:
        filter_str = f"crop=iw:ih-{trim_bottom}:0:0," + filter_str
    
    return filter_str + ",scale=1080:1920"


# =============================================================================
# STATIC-REACTIVE REFRAME MODE
# =============================================================================

def select_focus(
    analysis: FrameAnalysis,
    video_width: int,
    video_height: int
) -> Tuple[Tuple[int, int], str, float]:
    """
    Select focus point with priority: faces > persons > text > motion > center
    
    Returns:
        ((x, y), source, confidence)
    """
    center = (video_width // 2, video_height // 2)
    
    if analysis.faces:
        return analysis.faces[0].center, 'face', 0.95
    elif analysis.persons:
        return analysis.persons[0].center, 'person', 0.85
    elif analysis.scene_type == SceneType.TEXT:
        return center, 'center', 0.8
    elif analysis.motion_direction and analysis.motion_magnitude > 0.3:
        # Motion-weighted center
        dx, dy = analysis.motion_direction
        motion_x = int(center[0] + dx * video_width * 0.3)
        motion_y = int(center[1] + dy * video_height * 0.3)
        return (motion_x, motion_y), 'motion', 0.6
    else:
        return center, 'center', 0.5


def check_event_triggers(
    current_anchor: Anchor,
    analysis: FrameAnalysis,
    crop_width: int,
    video_width: int,
    video_height: int,
    margin_percent: float = 0.15
) -> Tuple[bool, Optional[Tuple[int, int]], str, float]:
    """
    Check if any event trigger fires requiring crop position change.
    
    Event triggers:
    1. Scene cut detected
    2. Primary subject exits current crop box
    3. New subject appears and is significantly different
    4. High motion burst
    
    Returns:
        (should_move, new_focus, source, confidence)
    """
    margin = int(crop_width * margin_percent)
    box = current_anchor.locked_box
    
    # Event 1: Scene cut - always triggers
    if analysis.is_scene_change:
        new_focus, source, confidence = select_focus(analysis, video_width, video_height)
        return True, new_focus, source, confidence
    
    # Get current best focus
    new_focus, source, confidence = select_focus(analysis, video_width, video_height)
    
    # Event 2: Subject exits locked box
    fx, fy = new_focus
    
    # Check if focus is outside the locked box with margin
    if fx < box[0] - margin or fx > box[2] + margin:
        return True, new_focus, source, confidence
    
    # Event 3: Significant position change (>25% of crop width from anchor center)
    anchor_center_x = (box[0] + box[2]) // 2
    if abs(fx - anchor_center_x) > crop_width * 0.25:
        return True, new_focus, source, confidence
    
    # Event 4: High motion burst (only if motion-driven content)
    if analysis.motion_magnitude > 0.6 and source == 'motion':
        return True, new_focus, source, confidence
    
    # No event triggered
    return False, None, '', 0.0


def generate_reactive_keyframes(
    video_path: Path,
    start: float,
    end: float,
    video_width: int,
    video_height: int,
    transcript_context: str = "",
    fine_interval: float = 0.1,
    min_dwell_time: float = 0.5,
    persistence_frames: int = 3
) -> List[SmartKeyframe]:
    """
    Event-driven keyframe generation for static-reactive mode.
    
    Only emits keyframes when meaningful events trigger crop changes.
    Uses hold-and-snap instead of continuous interpolation.
    
    Args:
        video_path: Source video
        start: Start time in seconds
        end: End time in seconds  
        video_width: Video width
        video_height: Video height
        transcript_context: Context for analysis
        fine_interval: Detection interval (finer than smoothing mode)
        min_dwell_time: Minimum time to hold position before allowing move
        persistence_frames: How many frames a change must persist before triggering
        
    Returns:
        Sparse list of keyframes at event points only
    """
    duration = end - start
    print(f"      Analyzing {duration:.1f}s clip with YOLO + motion detection (reactive mode)...")
    
    # Calculate 9:16 crop dimensions
    target_aspect = 9 / 16
    crop_height = video_height
    crop_width = int(crop_height * target_aspect)
    if crop_width > video_width:
        crop_width = video_width
        crop_height = int(crop_width / target_aspect)
    
    # Extract segment for analysis
    temp_segment = Path(f"/tmp/reactive_segment_{start:.1f}_{end:.1f}.mp4")
    
    extract_cmd = [
        'ffmpeg', '-y',
        '-ss', str(start),
        '-i', str(video_path),
        '-t', str(duration),
        '-c', 'copy',
        str(temp_segment)
    ]
    subprocess.run(extract_cmd, capture_output=True)
    
    # Get analyzer
    analyzer = get_scene_analyzer()
    
    # Fine-grained analysis for event detection
    cap = cv2.VideoCapture(str(temp_segment))
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    keyframes = []
    current_anchor = None
    last_keyframe_time = -min_dwell_time  # Allow first keyframe immediately
    pending_event = None
    pending_count = 0
    
    current_time = 0.0
    
    while current_time < duration:
        frame_num = int(current_time * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        
        ret, frame = cap.read()
        if not ret:
            break
        
        # Analyze frame
        analysis = analyzer.analyze_frame(frame, current_time)
        
        if current_anchor is None:
            # First frame: establish initial anchor
            focus, source, confidence = select_focus(analysis, video_width, video_height)
            
            # Calculate locked box (the 9:16 crop area)
            box_x1 = focus[0] - crop_width // 2
            box_x2 = focus[0] + crop_width // 2
            box_x1 = max(0, min(box_x1, video_width - crop_width))
            box_x2 = box_x1 + crop_width
            
            current_anchor = Anchor(
                focus_x=focus[0],
                focus_y=focus[1],
                locked_box=(box_x1, 0, box_x2, video_height),
                source=source,
                start_time=0.0,
                confidence=confidence
            )
            
            # Emit first keyframe at t=0
            keyframes.append(SmartKeyframe(
                timestamp=0.0,
                focus_x=focus[0],
                focus_y=focus[1],
                source=source,
                confidence=confidence,
                is_scene_change=True
            ))
            last_keyframe_time = 0.0
            
        else:
            # Check event triggers
            should_move, new_focus, source, confidence = check_event_triggers(
                current_anchor, analysis, crop_width, video_width, video_height
            )
            
            if should_move and new_focus:
                # Check persistence (require N consecutive frames with same event)
                if pending_event and abs(pending_event[0] - new_focus[0]) < crop_width * 0.1:
                    pending_count += 1
                else:
                    pending_event = new_focus
                    pending_count = 1
                
                # Check if event persists AND min dwell time has passed
                if pending_count >= persistence_frames and (current_time - last_keyframe_time) >= min_dwell_time:
                    # Event confirmed - emit keyframe
                    box_x1 = new_focus[0] - crop_width // 2
                    box_x2 = new_focus[0] + crop_width // 2
                    box_x1 = max(0, min(box_x1, video_width - crop_width))
                    box_x2 = box_x1 + crop_width
                    
                    current_anchor = Anchor(
                        focus_x=new_focus[0],
                        focus_y=new_focus[1],
                        locked_box=(box_x1, 0, box_x2, video_height),
                        source=source,
                        start_time=current_time,
                        confidence=confidence
                    )
                    
                    keyframes.append(SmartKeyframe(
                        timestamp=current_time,
                        focus_x=new_focus[0],
                        focus_y=new_focus[1],
                        source=source,
                        confidence=confidence,
                        is_scene_change=analysis.is_scene_change
                    ))
                    
                    last_keyframe_time = current_time
                    pending_event = None
                    pending_count = 0
            else:
                # No event - reset pending
                pending_event = None
                pending_count = 0
        
        current_time += fine_interval
    
    cap.release()
    
    # Cleanup temp file
    if temp_segment.exists():
        temp_segment.unlink()
    
    # Ensure we have at least one keyframe
    if not keyframes:
        keyframes.append(SmartKeyframe(
            timestamp=0.0,
            focus_x=video_width // 2,
            focus_y=video_height // 2,
            source='center',
            confidence=0.5,
            is_scene_change=True
        ))
    
    print(f"      Reactive mode: {len(keyframes)} keyframes (vs ~{int(duration/0.5)} in smooth mode)")
    return keyframes


def create_reactive_filter(
    keyframes: List[SmartKeyframe],
    video_width: int,
    video_height: int,
    trim_bottom: int = 0,
    snap_duration: float = 0.15
) -> str:
    """
    Create FFmpeg filter with hold-and-snap logic for reactive mode.
    
    For each keyframe pair:
    - Hold previous position until snap_duration before next keyframe
    - Snap to new position over snap_duration
    
    This creates intentional, decisive movements instead of slow creeps.
    """
    effective_height = video_height - trim_bottom
    
    target_aspect = 9 / 16
    crop_height = effective_height
    crop_width = int(crop_height * target_aspect)
    
    if crop_width > video_width:
        crop_width = video_width
        crop_height = int(crop_width / target_aspect)
    
    if len(keyframes) < 2:
        # Static crop
        crop_x = keyframes[0].focus_x - crop_width // 2 if keyframes else (video_width - crop_width) // 2
        crop_x = max(0, min(crop_x, video_width - crop_width))
        filter_str = f"crop={crop_width}:{crop_height}:{crop_x}:0"
        if trim_bottom > 0:
            filter_str = f"crop=iw:ih-{trim_bottom}:0:0," + filter_str
        return filter_str + ",scale=1080:1920"
    
    expr_parts = []
    
    for i in range(len(keyframes) - 1):
        t0 = keyframes[i].timestamp
        t1 = keyframes[i + 1].timestamp
        x0 = keyframes[i].focus_x - crop_width // 2
        x1 = keyframes[i + 1].focus_x - crop_width // 2
        
        x0 = max(0, min(x0, video_width - crop_width))
        x1 = max(0, min(x1, video_width - crop_width))
        
        # Calculate snap timing
        t_snap_start = max(t0, t1 - snap_duration)
        
        if t_snap_start > t0:
            # Hold phase: [t0, t_snap_start] -> hold x0
            expr_parts.append(f"between(t,{t0:.3f},{t_snap_start:.3f})*{x0}")
        
        # Snap phase: [t_snap_start, t1] -> interpolate x0 to x1
        snap_dur = t1 - t_snap_start
        if snap_dur > 0.001:
            expr_parts.append(
                f"between(t,{t_snap_start:.3f},{t1:.3f})*"
                f"({x0}+({x1}-{x0})*(t-{t_snap_start:.3f})/({snap_dur:.3f}+0.001))"
            )
    
    # Hold last position
    last_x = keyframes[-1].focus_x - crop_width // 2
    last_x = max(0, min(last_x, video_width - crop_width))
    expr_parts.append(f"gte(t,{keyframes[-1].timestamp:.3f})*{last_x}")
    
    x_expr = "+".join(expr_parts)
    
    filter_str = f"crop={crop_width}:{crop_height}:'{x_expr}':0"
    if trim_bottom > 0:
        filter_str = f"crop=iw:ih-{trim_bottom}:0:0," + filter_str
    
    return filter_str + ",scale=1080:1920"


# =============================================================================
# SHOT TYPE FILTERS (Hybrid Framing)
# =============================================================================

def create_letterbox_filter(
    video_width: int,
    video_height: int,
    trim_bottom: int = 0
) -> str:
    """
    Create letterbox filter for wide shots.
    Fits 16:9 content into 9:16 frame with black bars top/bottom.
    """
    effective_height = video_height - trim_bottom
    
    # Calculate the height of the letterboxed content in 1920 tall frame
    # 16:9 content at 1080 wide = 607.5 tall
    content_height = int(1080 * (9/16))  # ~607
    padding_top = (1920 - content_height) // 2
    
    if trim_bottom > 0:
        filter_str = f"crop=iw:ih-{trim_bottom}:0:0,"
    else:
        filter_str = ""
    
    # Scale to 1080 width, then pad to 1080x1920
    filter_str += f"scale=1080:-1,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
    return filter_str


def create_closeup_filter(
    video_width: int,
    video_height: int,
    focus_x: int,
    focus_y: int,
    trim_bottom: int = 0,
    zoom_factor: float = 1.3
) -> str:
    """
    Create closeup filter with tighter zoom on subject.
    Zooms 1.3x into the focus point.
    """
    effective_height = video_height - trim_bottom
    
    # Standard 9:16 crop dimensions
    target_aspect = 9 / 16
    base_crop_height = effective_height
    base_crop_width = int(base_crop_height * target_aspect)
    
    # Tighter crop (zoom in)
    crop_width = int(base_crop_width / zoom_factor)
    crop_height = int(base_crop_height / zoom_factor)
    
    # Ensure it fits
    crop_width = min(crop_width, video_width)
    crop_height = min(crop_height, effective_height)
    
    # Center on focus point
    crop_x = focus_x - crop_width // 2
    crop_y = focus_y - crop_height // 2
    
    # Clamp to bounds
    crop_x = max(0, min(crop_x, video_width - crop_width))
    crop_y = max(0, min(crop_y, effective_height - crop_height))
    
    if trim_bottom > 0:
        filter_str = f"crop=iw:ih-{trim_bottom}:0:0,"
    else:
        filter_str = ""
    
    filter_str += f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y},scale=1080:1920"
    return filter_str


def create_group_filter(
    video_width: int,
    video_height: int,
    trim_bottom: int = 0
) -> str:
    """
    Create group filter with wider center crop to fit multiple people.
    Uses ~75% of frame width instead of tight 9:16 slice.
    """
    effective_height = video_height - trim_bottom
    
    # Standard 9:16 crop
    target_aspect = 9 / 16
    crop_height = effective_height
    base_crop_width = int(crop_height * target_aspect)
    
    # Wider crop (1.3x width) but still 9:16 output
    # We take more width, then scale down, fitting more content
    crop_width = int(base_crop_width * 1.3)
    crop_width = min(crop_width, video_width)
    
    # Calculate proportional height to maintain aspect after scale
    crop_height = int(crop_width / target_aspect)
    crop_height = min(crop_height, effective_height)
    
    # Center crop
    crop_x = (video_width - crop_width) // 2
    crop_y = (effective_height - crop_height) // 2
    
    if trim_bottom > 0:
        filter_str = f"crop=iw:ih-{trim_bottom}:0:0,"
    else:
        filter_str = ""
    
    filter_str += f"crop={crop_width}:{crop_height}:{crop_x}:{crop_y},scale=1080:1920"
    return filter_str


def create_dynamic_filter(
    video_width: int,
    video_height: int,
    focus_x: int,
    focus_y: int,
    duration: float,
    trim_bottom: int = 0,
    start_zoom: float = 1.0,
    end_zoom: float = 1.15
) -> str:
    """
    Create Ken Burns dynamic zoom filter using zoompan.
    Starts at start_zoom and animates to end_zoom over duration.
    
    zoom=1.0 means no zoom (full frame visible)
    zoom=1.15 means 15% zoomed in (tighter on subject)
    """
    effective_height = video_height - trim_bottom
    
    # Calculate the number of frames for the animation
    # Assume 30fps for calculation
    fps = 30
    total_frames = int(duration * fps)
    
    # Zoom expression: linear interpolation from start_zoom to end_zoom
    # 'on' is the current output frame number (0-indexed)
    zoom_expr = f"'{start_zoom}+({end_zoom}-{start_zoom})*on/{total_frames}'"
    
    # Calculate normalized focus point (0-1 range)
    focus_x_norm = focus_x / video_width
    focus_y_norm = focus_y / effective_height
    
    # Pan expressions to keep focus point centered
    # x = (video_width - output_width) * focus_ratio
    # For zoompan, x/y are in input coordinates
    x_expr = f"'(iw-iw/zoom)*{focus_x_norm:.3f}'"
    y_expr = f"'(ih-ih/zoom)*{focus_y_norm:.3f}'"
    
    if trim_bottom > 0:
        filter_str = f"crop=iw:ih-{trim_bottom}:0:0,"
    else:
        filter_str = ""
    
    # Use zoompan for smooth Ken Burns effect
    # Output 9:16 aspect ratio (1080x1920)
    filter_str += (
        f"zoompan=z={zoom_expr}:x={x_expr}:y={y_expr}"
        f":d={total_frames}:s=1080x1920:fps={fps}"
    )
    
    return filter_str


def cut_clip_with_smart_reframe(
    video_path: Path,
    start: float,
    end: float,
    output_path: Path,
    transcript_context: str = "",
    api_key: str = "",
    use_llm: bool = True,
    trim_bottom: int = 0,
    reframe_style: str = "reactive",
    shot_type: str = "focus"
) -> Path:
    """
    Cut a clip with intelligent reframing.
    
    Args:
        video_path: Source video
        start: Start time in seconds
        end: End time in seconds
        output_path: Output path
        transcript_context: Transcript text for context
        api_key: Gemini API key (deprecated, not used)
        use_llm: Whether to use LLM (deprecated, not used)
        trim_bottom: Pixels to trim from bottom
        reframe_style: 'reactive' (hold-and-snap) or 'smooth' (continuous interpolation)
        shot_type: 'closeup', 'wide', 'group', 'dynamic', or 'focus' (default)
        
    Returns:
        Path to output clip
    """
    duration = end - start
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Get video dimensions
    cap = cv2.VideoCapture(str(video_path))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    
    print(f"      Smart reframe: analyzing {duration:.1f}s clip... (Style: {reframe_style}, Shot: {shot_type})")
    
    reframe_filter = None
    
    # Handle explicit shot types first (Hybrid Framing)
    if shot_type == "wide":
        # Letterbox - no subject detection needed
        reframe_filter = create_letterbox_filter(width, height, trim_bottom)
        print(f"      → Using WIDE (letterbox) filter")
        
    elif shot_type == "group":
        # Wider center crop
        reframe_filter = create_group_filter(width, height, trim_bottom)
        print(f"      → Using GROUP (wide crop) filter")
        
    elif shot_type == "closeup":
        # Need to detect subject for focus point
        analyzer = get_scene_analyzer()
        
        # Extract first frame for analysis
        temp_segment = Path(f"/tmp/shot_analysis_{start:.1f}.mp4")
        extract_cmd = [
            'ffmpeg', '-y', '-ss', str(start), '-i', str(video_path),
            '-t', '1', '-c', 'copy', str(temp_segment)
        ]
        subprocess.run(extract_cmd, capture_output=True)
        
        cap = cv2.VideoCapture(str(temp_segment))
        ret, frame = cap.read()
        cap.release()
        
        if ret:
            analysis = analyzer.analyze_frame(frame, 0.0)
            focus, _, _ = select_focus(analysis, width, height)
            focus_x, focus_y = focus
        else:
            focus_x, focus_y = width // 2, height // 2
        
        if temp_segment.exists():
            temp_segment.unlink()
        
        reframe_filter = create_closeup_filter(width, height, focus_x, focus_y, trim_bottom)
        
    elif shot_type == "dynamic":
        # Ken Burns zoom - need focus point
        analyzer = get_scene_analyzer()
        
        temp_segment = Path(f"/tmp/shot_analysis_{start:.1f}.mp4")
        extract_cmd = [
            'ffmpeg', '-y', '-ss', str(start), '-i', str(video_path),
            '-t', '1', '-c', 'copy', str(temp_segment)
        ]
        subprocess.run(extract_cmd, capture_output=True)
        
        cap = cv2.VideoCapture(str(temp_segment))
        ret, frame = cap.read()
        cap.release()
        
        if ret:
            analysis = analyzer.analyze_frame(frame, 0.0)
            focus, _, _ = select_focus(analysis, width, height)
            focus_x, focus_y = focus
        else:
            focus_x, focus_y = width // 2, height // 2
        
        if temp_segment.exists():
            temp_segment.unlink()
        
        reframe_filter = create_dynamic_filter(width, height, focus_x, focus_y, duration, trim_bottom)

    # If no filter yet (shot_type="focus" or unhandled), use standard smart reframing
    if reframe_filter is None:
        if reframe_style == "reactive":
            # Static-reactive mode: event-driven with hold-and-snap
            keyframes = generate_reactive_keyframes(
                video_path=video_path,
                start=start,
                end=end,
                video_width=width,
                video_height=height,
                transcript_context=transcript_context,
                fine_interval=0.1,
                min_dwell_time=0.5,
                persistence_frames=3
            )
            
            # Log keyframe sources
            sources = {}
            for kf in keyframes:
                sources[kf.source] = sources.get(kf.source, 0) + 1
            print(f"      Keyframe sources: {sources}")
            
            # Create reactive filter (hold-and-snap)
            reframe_filter = create_reactive_filter(
                keyframes, width, height, trim_bottom, snap_duration=0.15
            )
        else:
            # Legacy smooth mode: continuous interpolation
            keyframes = generate_smart_keyframes(
                video_path=video_path,
                start=start,
                end=end,
                transcript_context=transcript_context,
                api_key=api_key,
                sample_interval=0.5,
                use_llm=use_llm,
                llm_threshold=0.6
            )
            
            # Smooth keyframes
            smoothed = smooth_keyframes(keyframes, width)
            
            # Log keyframe sources
            sources = {}
            for kf in smoothed:
                sources[kf.source] = sources.get(kf.source, 0) + 1
            print(f"      Keyframe sources: {sources}")
            
            # Create smooth filter
            reframe_filter = create_smart_reframe_filter(
                smoothed, width, height, trim_bottom
            )
    
    # Apply reframing
    cmd = [
        'ffmpeg', '-y',
        '-ss', str(start),
        '-i', str(video_path),
        '-t', str(duration),
        '-vf', reframe_filter,
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-c:a', 'aac',
        '-b:a', '128k',
        str(output_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg smart reframe failed: {result.stderr.decode()}")
    
    return output_path
