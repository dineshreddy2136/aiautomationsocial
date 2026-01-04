"""
Transcript extraction module
Supports YouTube captions (VTT) and Whisper fallback
"""

import re
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class TranscriptSegment:
    """A segment of transcript with timing"""
    text: str
    start: float  # seconds
    end: float    # seconds
    
    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end
        }


def parse_vtt_timestamp(timestamp: str) -> float:
    """Convert VTT timestamp to seconds"""
    # Format: HH:MM:SS.mmm or MM:SS.mmm
    parts = timestamp.strip().split(':')
    
    if len(parts) == 3:
        hours, minutes, seconds = parts
        hours = int(hours)
    else:
        hours = 0
        minutes, seconds = parts
    
    minutes = int(minutes)
    seconds = float(seconds)
    
    return hours * 3600 + minutes * 60 + seconds


def parse_vtt_file(vtt_path: Path) -> List[TranscriptSegment]:
    """
    Parse VTT subtitle file into transcript segments.
    
    Args:
        vtt_path: Path to VTT file
        
    Returns:
        List of TranscriptSegment objects
    """
    segments = []
    content = vtt_path.read_text(encoding='utf-8')
    
    # Remove WEBVTT header and metadata
    lines = content.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Look for timestamp line (e.g., "00:00:01.000 --> 00:00:04.000")
        timestamp_match = re.match(
            r'(\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})',
            line
        )
        
        if timestamp_match:
            start = parse_vtt_timestamp(timestamp_match.group(1))
            end = parse_vtt_timestamp(timestamp_match.group(2))
            
            # Collect text lines until empty line or next timestamp
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r'\d{1,2}:\d{2}', lines[i]):
                # Remove VTT tags like <c> and timing info
                text = re.sub(r'<[^>]+>', '', lines[i].strip())
                if text:
                    text_lines.append(text)
                i += 1
            
            if text_lines:
                # Join and clean text
                full_text = ' '.join(text_lines)
                # Remove duplicate consecutive words (common in auto-subs)
                full_text = re.sub(r'\b(\w+)( \1\b)+', r'\1', full_text)
                
                segments.append(TranscriptSegment(
                    text=full_text,
                    start=start,
                    end=end
                ))
        else:
            i += 1
    
    # Merge very short consecutive segments with same text
    merged = merge_segments(segments)
    
    print(f"✓ Parsed {len(merged)} transcript segments from VTT")
    return merged


def merge_segments(segments: List[TranscriptSegment], gap_threshold: float = 0.5) -> List[TranscriptSegment]:
    """Merge consecutive segments that are close together"""
    if not segments:
        return []
    
    merged = [segments[0]]
    
    for segment in segments[1:]:
        last = merged[-1]
        
        # If segments are close and text is similar or continuation
        if segment.start - last.end < gap_threshold:
            # Merge by extending the end time and combining text
            if segment.text.lower() != last.text.lower():
                merged[-1] = TranscriptSegment(
                    text=f"{last.text} {segment.text}",
                    start=last.start,
                    end=segment.end
                )
            else:
                merged[-1] = TranscriptSegment(
                    text=last.text,
                    start=last.start,
                    end=segment.end
                )
        else:
            merged.append(segment)
    
    return merged


def transcribe_with_whisper(video_path: Path, model_name: str = "base") -> List[TranscriptSegment]:
    """
    Transcribe video using Whisper (fallback method).
    
    Args:
        video_path: Path to video file
        model_name: Whisper model to use
        
    Returns:
        List of TranscriptSegment objects
    """
    print(f"⏳ Transcribing with Whisper ({model_name} model)...")
    
    import whisper
    
    model = whisper.load_model(model_name)
    result = model.transcribe(str(video_path))
    
    segments = []
    for seg in result['segments']:
        segments.append(TranscriptSegment(
            text=seg['text'].strip(),
            start=seg['start'],
            end=seg['end']
        ))
    
    print(f"✓ Transcribed {len(segments)} segments with Whisper")
    return segments


def extract_transcript(
    video_path: Path,
    subtitle_path: Optional[Path] = None,
    whisper_model: str = "base"
) -> List[TranscriptSegment]:
    """
    Extract transcript from video.
    Uses subtitle file if available, otherwise falls back to Whisper.
    
    Args:
        video_path: Path to video file
        subtitle_path: Optional path to VTT subtitle file
        whisper_model: Whisper model to use for fallback
        
    Returns:
        List of TranscriptSegment objects
    """
    # Try VTT subtitles first
    if subtitle_path and subtitle_path.exists():
        segments = parse_vtt_file(subtitle_path)
        
        # QUALITY CHECK:
        # YouTube Shorts often return 1 giant segment (e.g., 00:00 to 00:59)
        # This ruins our ability to sync dubbing. 
        # If any segment is longer than 15 seconds, or we have very few segments for a moderate duration,
        # we consider the VTT "low granularity" and force Whisper.
        
        needs_whisper = False
        
        if not segments:
            needs_whisper = True
        else:
            # Check for super-long segments
            for seg in segments:
                duration = seg.end - seg.start
                if duration > 15.0:
                    print(f"⚠ VTT segment too long ({duration:.1f}s) - insufficient granularity for dubbing.")
                    needs_whisper = True
                    break
        
        if not needs_whisper:
            return segments
        else:
            print("⚠ Falling back to Whisper for granular timestamps...")
    
    # Fallback to Whisper
    return transcribe_with_whisper(video_path, whisper_model)
