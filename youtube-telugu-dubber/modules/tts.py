"""
Text-to-Speech module using Eleven Labs
Uses FFmpeg directly for audio manipulation (Python 3.14 compatible)
"""

import subprocess
import tempfile
import os
import json
from typing import List, Dict
from pathlib import Path

from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings, save

from modules.transcript import TranscriptSegment
from config import ELEVENLABS_MODEL, OUTPUT_DIR, AUDIO_SPEED


def generate_audio(
    segments: List[TranscriptSegment],
    api_key: str,
    voice_id: str,
    output_path: Path
) -> Path:
    """
    Generate Telugu audio from translated segments using Eleven Labs.
    Uses FFmpeg for audio manipulation (compatible with Python 3.14).
    
    Args:
        segments: List of TranscriptSegment with Telugu text
        api_key: Eleven Labs API key
        voice_id: Eleven Labs voice ID
        output_path: Path to save the audio file
        
    Returns:
        Path to generated audio file
    """
    client = ElevenLabs(api_key=api_key)
    
    print(f"⏳ Generating Telugu audio with Eleven Labs (model: {ELEVENLABS_MODEL}, speed: {AUDIO_SPEED}x)...")
    
    # Calculate total duration needed
    if not segments:
        raise ValueError("No segments to generate audio from")
    
    total_duration = segments[-1].end + 1.0  # Add 1 second buffer
    
    # Create temp directory for segment audio files
    temp_dir = Path(tempfile.mkdtemp())
    segment_files = []
    
    # Create logs directory for debugging
    debug_dir = OUTPUT_DIR / "audio_debug"
    debug_dir.mkdir(exist_ok=True)
    
    try:
        for i, segment in enumerate(segments):
            if not segment.text.strip():
                continue
            
            text_preview = segment.text[:30] + "..." if len(segment.text) > 30 else segment.text
            char_count = len(segment.text)
            print(f"  Generating segment {i+1}/{len(segments)} ({char_count} chars): {text_preview}")
            
            # Save text being sent to Eleven Labs for debugging
            text_debug_path = debug_dir / f"segment_{i:03d}_text.txt"
            with open(text_debug_path, 'w', encoding='utf-8') as f:
                f.write(f"=== TEXT SENT TO ELEVEN LABS ===\n")
                f.write(f"Segment: {i+1}/{len(segments)}\n")
                f.write(f"Chars: {char_count}\n")
                f.write(f"Start: {segment.start}s, End: {segment.end}s\n\n")
                f.write(segment.text)
            
            # Generate audio for this segment
            try:
                # Generate audio - match test.py parameters
                # Use output_format="mp3_44100_128"
                # Use speed in VoiceSettings only if speed != 1.0
                voice_settings = None
                if AUDIO_SPEED != 1.0:
                    voice_settings = VoiceSettings(
                        stability=0.5,
                        similarity_boost=0.75,
                        style=0.0,
                        use_speaker_boost=True,
                        speed=AUDIO_SPEED
                    )
                
                audio_generator = client.text_to_speech.convert(
                    voice_id=voice_id,
                    text=segment.text,
                    model_id=ELEVENLABS_MODEL,
                    output_format="mp3_44100_128",
                    voice_settings=voice_settings
                )
                
                # Save segment audio (raw from Eleven Labs)
                raw_segment_path = temp_dir / f"segment_{i:03d}_raw.mp3"
                save(audio_generator, str(raw_segment_path))
                
                # Get actual audio duration
                probe_result = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'default=noprint_wrappers=1:nokey=1', str(raw_segment_path)],
                    capture_output=True, text=True
                )
                actual_duration = float(probe_result.stdout.strip())
                
                # Calculate target duration from timestamps
                target_duration = segment.end - segment.start
                
                # Calculate required speed to fit the target duration
                if target_duration > 0 and actual_duration > 0:
                    required_speed = actual_duration / target_duration
                else:
                    required_speed = 1.0
                
                # Apply speed adjustment using FFmpeg atempo filter
                segment_path = temp_dir / f"segment_{i:03d}.mp3"
                
                if abs(required_speed - 1.0) > 0.05:  # Only adjust if > 5% difference
                    # atempo filter range is 0.5 to 2.0, chain if needed
                    filter_chain = []
                    remaining_speed = required_speed
                    
                    while remaining_speed > 2.0:
                        filter_chain.append('atempo=2.0')
                        remaining_speed /= 2.0
                    while remaining_speed < 0.5:
                        filter_chain.append('atempo=0.5')
                        remaining_speed *= 2.0
                    
                    filter_chain.append(f'atempo={remaining_speed:.4f}')
                    filter_str = ','.join(filter_chain)
                    
                    subprocess.run([
                        'ffmpeg', '-y', '-i', str(raw_segment_path),
                        '-filter:a', filter_str,
                        '-c:a', 'libmp3lame',
                        str(segment_path)
                    ], capture_output=True, check=True)
                    
                    print(f"    ✓ Generated ({actual_duration:.1f}s → {target_duration:.1f}s, speed: {required_speed:.2f}x)")
                else:
                    # No speed adjustment needed
                    import shutil
                    shutil.copy2(raw_segment_path, segment_path)
                    print(f"    ✓ Generated ({actual_duration:.1f}s, no adjustment needed)")
                
                # Save both raw and adjusted audio for debugging
                import shutil
                debug_raw_path = debug_dir / f"segment_{i:03d}_raw.mp3"
                shutil.copy2(raw_segment_path, debug_raw_path)  # Original from Eleven Labs
                
                debug_adjusted_path = debug_dir / f"segment_{i:03d}_adjusted.mp3"
                shutil.copy2(segment_path, debug_adjusted_path)  # After speed adjustment
                
                segment_files.append({
                    'path': segment_path,
                    'start': segment.start,
                    'end': segment.end
                })
                
            except Exception as e:
                print(f"  ⚠ Error generating segment {i+1}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        if not segment_files:
            raise ValueError("No audio segments were generated successfully")
        
        print(f"  Segment audio saved to: {debug_dir}")
        
        # Use FFmpeg to combine segments with proper timing
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # For single segment, just copy the file directly (no need for complex mixing)
        if len(segment_files) == 1:
            import shutil
            shutil.copy2(segment_files[0]['path'], output_path)
            print(f"✓ Generated audio: {output_path}")
            return output_path
        
        # For multiple segments, use FFmpeg to combine with proper timing
        # Calculate duration based on the longest audio, not video duration
        max_audio_duration = max(seg['end'] for seg in segment_files) + 5.0  # Add buffer
        
        # Create silent base audio
        silent_path = temp_dir / "silent.mp3"
        subprocess.run([
            'ffmpeg', '-y', '-f', 'lavfi',
            '-i', f'anullsrc=r=44100:cl=stereo',
            '-t', str(max_audio_duration),
            '-c:a', 'libmp3lame',
            str(silent_path)
        ], capture_output=True, check=True)
        
        # Build complex filter for overlaying audio
        inputs = ['-i', str(silent_path)]
        filter_parts = []
        
        for idx, seg in enumerate(segment_files):
            inputs.extend(['-i', str(seg['path'])])
            delay_ms = int(seg['start'] * 1000)
            filter_parts.append(f"[{idx+1}]adelay={delay_ms}|{delay_ms}[a{idx}]")
        
        # Mix all delayed audio streams - use 'longest' duration
        if filter_parts:
            mix_inputs = ''.join(f'[a{i}]' for i in range(len(segment_files)))
            filter_complex = ';'.join(filter_parts) + f';[0]{mix_inputs}amix=inputs={len(segment_files)+1}:duration=longest[out]'
            
            cmd = ['ffmpeg', '-y'] + inputs + [
                '-filter_complex', filter_complex,
                '-map', '[out]',
                '-c:a', 'libmp3lame',
                str(output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                # Fallback: just concatenate if complex filter fails
                print("  Using fallback audio merge method...")
                _fallback_merge(segment_files, output_path, max_audio_duration)
        else:
            # No segments, just use silence
            subprocess.run(['cp', str(silent_path), str(output_path)], check=True)
        
        print(f"✓ Generated audio: {output_path}")
        return output_path
        
    finally:
        # Cleanup temp files
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def _fallback_merge(segment_files: list, output_path: Path, total_duration: float):
    """Fallback method: use first segment or concatenate"""
    if segment_files:
        # Just use the segments concatenated
        temp_list = output_path.parent / "concat_list.txt"
        with open(temp_list, 'w') as f:
            for seg in segment_files:
                f.write(f"file '{seg['path']}'\n")
        
        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', str(temp_list),
            '-c:a', 'libmp3lame',
            str(output_path)
        ], capture_output=True, check=True)
        
        temp_list.unlink()
