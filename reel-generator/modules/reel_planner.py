"""
Reel Planner Module - Two-Phase Gemini System
Phase 1: Generate 8-10 reel ideas
Phase 2: Rate and rank ideas, select top 4
"""

import json
import re
from typing import List, Tuple
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

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
    virality_score: int = 0
    reasoning: str = ""
    rank: int = 0
    total_duration: float = 0.0
    
    def __post_init__(self):
        self.total_duration = sum(c.end - c.start for c in self.clips)
    
    def to_dict(self) -> dict:
        return {
            "reel_number": self.reel_number,
            "title": self.title,
            "virality_score": self.virality_score,
            "reasoning": self.reasoning,
            "rank": self.rank,
            "clips": [{"start": c.start, "end": c.end, "description": c.description} for c in self.clips],
            "narration_script": self.narration_script,
            "total_duration": round(self.total_duration, 2)
        }


def _get_safety_settings():
    """Safety settings for movie content"""
    return [
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    ]


def _extract_response_text(response) -> str:
    """Extract text from Gemini response"""
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
    
    return response_text


def _clean_json_response(response_text: str) -> str:
    """Clean markdown code blocks from JSON response"""
    if response_text.startswith('```'):
        response_text = re.sub(r'^```json?\n?', '', response_text)
        response_text = re.sub(r'\n?```$', '', response_text)
    return response_text


def phase1_generate_ideas(
    client: genai.Client,
    transcript_data: list,
    video_duration: float,
    target_reel_duration: int,
    logs_dir: Path,
    timestamp: str
) -> list:
    """
    Phase 1: Generate 8-10 viral reel ideas.
    Returns raw JSON data from Gemini.
    """
    prompt = f"""You are an expert story editor. Split this movie recap into 4-6 SEQUENTIAL PARTS that tell the complete story.

## INPUT
- Video Duration: {video_duration:.1f} seconds
- Target Reel Duration: Each part should be {target_reel_duration}-80 seconds
- Transcript with WORD-LEVEL TIMESTAMPS (use these for precise clip boundaries):
{json.dumps(transcript_data, indent=2)}

## YOUR MISSION
Create 4-6 SEQUENTIAL story parts (Part 1, Part 2, etc.) that:
1. Tell the COMPLETE story from beginning to end
2. Follow CHRONOLOGICAL order (no jumping around)
3. Each part is a natural story segment (not random viral clips)
4. All parts together cover the ENTIRE video
5. Each part ends at a natural pause/cliffhanger to encourage watching the next part
6. Use PRECISE timestamps from the transcript word boundaries

## STRUCTURE FOR EACH PART

### Part 1: Introduction & Setup
- Introduce the main character/situation
- Set up the world and stakes
- End with the first major conflict or hook

### Parts 2-4: Rising Action
- Continue the story chronologically
- Build tension and stakes
- Each part should have its own mini-climax
- End on cliffhangers ("But little did he know...")

### Final Part: Climax & Resolution
- The main confrontation/payoff
- Story resolution
- Satisfying ending

## CLIP RULES
- Clips MUST be in chronological order within each part
- Each clip: 5-15 seconds
- Use EXACT timestamps from the transcript (word-level precision available)
- Parts should NOT overlap in timeline
- Include the transcript_text for each clip (exact words spoken)

## SHOT TYPE GUIDELINES
For each clip, suggest the best shot_type for vertical reframing:
- "closeup": Emotional moments, single speaker, dramatic reveals, tension
- "wide": Establishing shots, landscapes, no humans, scene transitions, reveals
- "group": Multiple people (3+), reactions, conversations, crowd scenes
- "focus": Default tracking of 1-2 people, action sequences

## OUTPUT FORMAT (JSON only)
{{
  "total_parts": <4-6>,
  "reels": [
    {{
      "reel_number": 1,
      "title": "Part 1: [Story Phase Title]",
      "story_summary": "What happens in this part",
      "clips": [
        {{"start": <seconds>, "end": <seconds>, "transcript_text": "exact words spoken", "description": "...", "shot_type": "focus"}},
        ...
      ],
      "narration_script": "60-80 second narration for this part...",
      "cliffhanger": "How this part ends to hook viewers for Part 2"
    }}
  ]
}}

Generate 4-6 sequential story parts NOW:"""

    print(f"⏳ Phase 1: Generating 4-6 story parts with Gemini ({GEMINI_MODEL})...")
    
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(safety_settings=_get_safety_settings())
    )
    
    # Save Phase 1 logs
    with open(logs_dir / f"{timestamp}_phase1_input.txt", 'w', encoding='utf-8') as f:
        f.write(prompt)
    
    response_text = _extract_response_text(response)
    
    with open(logs_dir / f"{timestamp}_phase1_output.txt", 'w', encoding='utf-8') as f:
        f.write(response_text)
    
    response_text = _clean_json_response(response_text)
    
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"⚠ Error parsing Phase 1 response: {e}")
        raise ValueError("Failed to parse Phase 1 from Gemini")
    
    print(f"✓ Phase 1: Generated {len(data.get('reels', []))} story parts")
    return data


def phase2_rank_ideas(
    client: genai.Client,
    phase1_data: dict,
    logs_dir: Path,
    timestamp: str,
    top_n: int = 4
) -> list:
    """
    Phase 2: Rate and rank the reel ideas, return top N.
    Returns ranked list with virality scores.
    """
    prompt = f"""You are a story quality reviewer. Review and enhance these sequential story parts.

## INPUT: {len(phase1_data.get('reels', []))} Story Parts
{json.dumps(phase1_data['reels'], indent=2)}

## YOUR TASK
1. Verify each part follows chronological order
2. Score each part's storytelling quality (0-100)
3. Ensure smooth transitions between parts
4. Select the best {top_n} parts if there are more than {top_n}

## SCORING CRITERIA

### STORY CLARITY (40 points)
- Does this part clearly advance the narrative?
- Is it easy to follow without context?

### PACING (30 points)
- Does it have good rhythm (not too slow/fast)?
- Does it end at a natural break point?

### ENGAGEMENT (30 points)
- Does it hook viewers to watch the next part?
- Are there "can't look away" moments?

## OUTPUT FORMAT (JSON only)
{{
  "rankings": [
    {{
      "original_reel_number": <from input>,
      "rank": <chronological order: 1, 2, 3...>,
      "virality_score": <0-100>,
      "reasoning": "How well this part tells its segment of the story",
      "improvements": "Suggestions for better pacing or transitions"
    }},
    ...
  ],
  "top_{top_n}_reel_numbers": [<list of part numbers to keep, up to {top_n}>]
}}

Review all story parts:"""

    print(f"⏳ Phase 2: Reviewing story quality with Gemini...")
    
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(safety_settings=_get_safety_settings())
    )
    
    # Save Phase 2 logs
    with open(logs_dir / f"{timestamp}_phase2_input.txt", 'w', encoding='utf-8') as f:
        f.write(prompt)
    
    response_text = _extract_response_text(response)
    
    with open(logs_dir / f"{timestamp}_phase2_output.txt", 'w', encoding='utf-8') as f:
        f.write(response_text)
    
    response_text = _clean_json_response(response_text)
    
    try:
        ranking_data = json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"⚠ Error parsing Phase 2 response: {e}")
        raise ValueError("Failed to parse Phase 2 from Gemini")
    
    print(f"✓ Phase 2: Ranked {len(ranking_data.get('rankings', []))} ideas")
    return ranking_data


def plan_reels(
    segments: List[TranscriptSegment],
    api_key: str,
    video_duration: float,
    target_reel_duration: int = 60,
    top_n: int = 4
) -> List[ReelPlan]:
    """
    Single-phase reel planning for sequential story mode.
    Generates 4-6 story parts covering the entire video chronologically.
    """
    client = genai.Client(api_key=api_key)
    transcript_data = [seg.to_dict() for seg in segments]
    
    # Setup logging
    logs_dir = OUTPUT_DIR / "gemini_logs"
    logs_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Generate story parts (no Phase 2 ranking for sequential mode)
    phase1_data = phase1_generate_ideas(
        client, transcript_data, video_duration, 
        target_reel_duration, logs_dir, timestamp
    )
    
    # Convert all story parts to ReelPlan objects
    reel_plans = []
    
    for reel_data in phase1_data.get('reels', []):
        clips = [
            Clip(
                start=clip['start'],
                end=clip['end'],
                description=clip.get('description', '')
            )
            for clip in reel_data.get('clips', [])
        ]
        
        reel_plan = ReelPlan(
            reel_number=reel_data.get('reel_number', len(reel_plans) + 1),
            title=reel_data.get('title', f"Part {len(reel_plans) + 1}"),
            virality_score=85,  # Default score for story parts
            reasoning=reel_data.get('story_summary', ''),
            rank=reel_data.get('reel_number', len(reel_plans) + 1),
            clips=clips,
            narration_script=reel_data.get('narration_script', '')
        )
        reel_plans.append(reel_plan)
    
    # Limit to top_n if more were generated
    if len(reel_plans) > top_n:
        reel_plans = reel_plans[:top_n]
    
    # Renumber sequentially
    for i, reel in enumerate(reel_plans):
        reel.reel_number = i + 1
    
    print(f"✓ Final: {len(reel_plans)} story parts ready for cutting")
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
