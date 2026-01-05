"""
Reel Planner Module
Uses Gemini LLM to analyze transcript and create reel plans with:
- Scene timestamps to cut
- Narration scripts for each reel
"""

import json
import re
from typing import List
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict

from google import genai
from google.genai import types

from modules.transcript import TranscriptSegment
from config import GEMINI_MODEL, OUTPUT_DIR


@dataclass
class Clip:
    """A single clip to cut from the video"""
    start: float
    end: float
    description: str = ""


@dataclass
class ReelPlan:
    """Plan for a single reel"""
    reel_number: int
    title: str
    clips: List[Clip]
    narration_script: str
    total_duration: float = 0.0
    
    def __post_init__(self):
        self.total_duration = sum(c.end - c.start for c in self.clips)
    
    def to_dict(self) -> dict:
        return {
            "reel_number": self.reel_number,
            "title": self.title,
            "clips": [{"start": c.start, "end": c.end, "description": c.description} for c in self.clips],
            "narration_script": self.narration_script,
            "total_duration": round(self.total_duration, 2)
        }


def plan_reels(
    segments: List[TranscriptSegment],
    api_key: str,
    video_duration: float,
    target_reel_duration: int = 60
) -> List[ReelPlan]:
    """
    Use Gemini to analyze transcript and create reel plans.
    
    Args:
        segments: List of TranscriptSegment with timestamps
        api_key: Gemini API key
        video_duration: Total video duration in seconds
        target_reel_duration: Target duration for each reel (default 60s)
        
    Returns:
        List of ReelPlan objects
    """
    client = genai.Client(api_key=api_key)
    
    # Prepare transcript for LLM
    transcript_data = [seg.to_dict() for seg in segments]
    
    prompt = f"""You are an expert video editor and storyteller. Your task is to analyze a movie recap video transcript and create a plan for breaking it into short-form vertical reels (like Instagram Reels or TikTok).

## INPUT
- Video Duration: {video_duration:.1f} seconds ({video_duration/60:.1f} minutes)
- Target Reel Duration: ~{target_reel_duration} seconds each
- Transcript with timestamps:

{json.dumps(transcript_data, indent=2)}

## YOUR TASK
1. Analyze the story/content in the transcript
2. Determine how many reels are needed to tell the complete story (typically 3-5 reels for a 10-15 min video)
3. For each reel, select the most engaging and visually interesting scenes by their timestamps
4. Write a NEW narration script for each reel that:
   - Is engaging and hook-driven
   - Fits within ~{target_reel_duration} seconds when spoken
   - Tells the story in a compelling way
   - Uses cliffhangers between parts to encourage viewers to watch the next reel

## RULES
- Each reel should be approximately {target_reel_duration} seconds of video clips
- Select 4-8 clips per reel, each clip 5-15 seconds long
- Clips should be in chronological order within each reel
- The narration should be a FRESH script, not just copying the original transcript
- Make the narration punchy, engaging, and suitable for short-form content
- End each reel (except the last) with a hook/cliffhanger

## OUTPUT FORMAT (JSON only, no markdown)
{{
  "total_reels": <number>,
  "reels": [
    {{
      "reel_number": 1,
      "title": "Part 1 - [Catchy Title]",
      "clips": [
        {{"start": <seconds>, "end": <seconds>, "description": "Brief scene description"}},
        ...
      ],
      "narration_script": "Your engaging narration script for this reel..."
    }},
    ...
  ]
}}

Analyze the transcript and create the reel plan now:"""

    print(f"⏳ Analyzing transcript with Gemini ({GEMINI_MODEL})...")
    
    # Safety settings for movie content
    safety_settings = [
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    ]
    
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(safety_settings=safety_settings)
    )
    
    # Save logs for debugging
    logs_dir = OUTPUT_DIR / "gemini_logs"
    logs_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    with open(logs_dir / f"{timestamp}_reel_planner_input.txt", 'w', encoding='utf-8') as f:
        f.write(prompt)
    
    # Extract response text
    response_text = None
    try:
        if hasattr(response, 'text') and response.text:
            response_text = response.text.strip()
    except Exception:
        pass
    
    if not response_text:
        try:
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and candidate.content:
                    if hasattr(candidate.content, 'parts') and candidate.content.parts:
                        response_text = candidate.content.parts[0].text.strip()
        except Exception:
            pass
    
    if not response_text:
        raise ValueError("Could not extract text from Gemini response")
    
    with open(logs_dir / f"{timestamp}_reel_planner_output.txt", 'w', encoding='utf-8') as f:
        f.write(response_text)
    
    # Clean up response
    if response_text.startswith('```'):
        response_text = re.sub(r'^```json?\n?', '', response_text)
        response_text = re.sub(r'\n?```$', '', response_text)
    
    # Parse JSON
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"⚠ Error parsing Gemini response: {e}")
        print(f"Response was: {response_text[:500]}...")
        raise ValueError("Failed to parse reel plan from Gemini")
    
    # Convert to ReelPlan objects
    reel_plans = []
    for reel_data in data.get('reels', []):
        clips = [
            Clip(
                start=clip['start'],
                end=clip['end'],
                description=clip.get('description', '')
            )
            for clip in reel_data.get('clips', [])
        ]
        
        reel_plan = ReelPlan(
            reel_number=reel_data['reel_number'],
            title=reel_data.get('title', f"Part {reel_data['reel_number']}"),
            clips=clips,
            narration_script=reel_data.get('narration_script', '')
        )
        reel_plans.append(reel_plan)
    
    print(f"✓ Created {len(reel_plans)} reel plans")
    return reel_plans


def save_reel_plans(reel_plans: List[ReelPlan], output_path: Path) -> Path:
    """Save reel plans to JSON file"""
    data = {
        "total_reels": len(reel_plans),
        "reels": [reel.to_dict() for reel in reel_plans]
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Saved reel plans to: {output_path}")
    return output_path
