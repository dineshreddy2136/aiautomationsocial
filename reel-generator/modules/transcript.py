"""
Transcript extraction module using stable-ts for precise word-level timestamps.
Uses Whisper large model for best accuracy.
"""

from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class WordTimestamp:
    """A single word with precise timing"""
    word: str
    start: float  # seconds
    end: float    # seconds
    
    def to_dict(self) -> dict:
        return {
            "word": self.word,
            "start": round(self.start, 3),
            "end": round(self.end, 3)
        }


@dataclass
class TranscriptSegment:
    """A segment of transcript with timing and optional word-level timestamps"""
    text: str
    start: float  # seconds
    end: float    # seconds
    words: List[WordTimestamp] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        result = {
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.end - self.start, 3)
        }
        if self.words:
            result["words"] = [w.to_dict() for w in self.words]
        return result


def transcribe_with_stable_ts(
    video_path: Path,
    model_name: str = "large"
) -> List[TranscriptSegment]:
    """
    Transcribe video using stable-ts with Whisper model.
    Provides precise word-level timestamps.
    
    Args:
        video_path: Path to video file
        model_name: Whisper model to use (default: large)
        
    Returns:
        List of TranscriptSegment objects with word-level timestamps
    """
    import stable_whisper
    
    print(f"⏳ Transcribing with stable-ts (Whisper {model_name} model)...")
    print(f"   This may take a few minutes for the first run (downloading model)...")
    
    # Load model
    model = stable_whisper.load_model(model_name)
    
    # Transcribe with word-level timestamps
    result = model.transcribe(str(video_path))
    
    segments = []
    for seg in result.segments:
        # Extract word-level timestamps
        words = []
        for word in seg.words:
            words.append(WordTimestamp(
                word=word.word,
                start=word.start,
                end=word.end
            ))
        
        segments.append(TranscriptSegment(
            text=seg.text.strip(),
            start=seg.start,
            end=seg.end,
            words=words
        ))
    
    total_words = sum(len(seg.words) for seg in segments)
    print(f"✓ Transcribed {len(segments)} segments with {total_words} word timestamps")
    
    return segments


def extract_transcript(
    video_path: Path,
    model_name: str = "large"
) -> List[TranscriptSegment]:
    """
    Extract transcript from video using stable-ts.
    
    Args:
        video_path: Path to video file
        model_name: Whisper model to use (default: large)
        
    Returns:
        List of TranscriptSegment objects with word-level timestamps
    """
    return transcribe_with_stable_ts(video_path, model_name)


def format_transcript_for_llm(segments: List[TranscriptSegment], include_words: bool = True) -> str:
    """
    Format transcript segments for LLM consumption.
    
    Args:
        segments: List of TranscriptSegment objects
        include_words: Whether to include word-level timestamps
        
    Returns:
        Formatted string for LLM prompt
    """
    lines = []
    for seg in segments:
        lines.append(f"[{seg.start:.3f}s - {seg.end:.3f}s] {seg.text}")
        if include_words and seg.words:
            for word in seg.words:
                lines.append(f"  {word.start:.3f}s - {word.end:.3f}s: \"{word.word}\"")
            lines.append("")  # Empty line between segments
    
    return "\n".join(lines)
