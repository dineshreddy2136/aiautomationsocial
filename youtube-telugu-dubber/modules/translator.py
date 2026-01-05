"""
Translation module using Google Gemini (new google-genai SDK)
"""

from google import genai
from google.genai import types
from typing import List
from pathlib import Path
from datetime import datetime
from modules.transcript import TranscriptSegment
from config import GEMINI_MODEL, OUTPUT_DIR, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE
import json
import re


def translate_text(
    segments: List[TranscriptSegment],
    api_key: str,
    target_language: str = DEFAULT_LANGUAGE
) -> List[TranscriptSegment]:
    """
    Translate transcript segments to the target language using Gemini.
    
    Args:
        segments: List of TranscriptSegment with English text
        api_key: Gemini API key
        target_language: Language code (e.g., 'tel', 'hin', 'tam')
        
    Returns:
        List of TranscriptSegment with translated text
    """
    # Get language name from code
    language_name = SUPPORTED_LANGUAGES.get(target_language, "Telugu")
    
    # Initialize client
    client = genai.Client(api_key=api_key)
    
    # Prepare text for translation with duration calculation
    texts_to_translate = [
        {
            "index": i, 
            "text": seg.text, 
            "start": seg.start, 
            "end": seg.end,
            "duration": round(seg.end - seg.start, 1)
        }
        for i, seg in enumerate(segments)
    ]
    
    prompt = f"""You are a professional dubbing script writer and translator. 
Your task is to adapt the following English transcript segments into {language_name} for a YouTube video voiceover.

IMPORTANT CONSTRAINTS:
1. **DURATION MATCHING**: Each segment has a "duration" in seconds. The {language_name} translation MUST be able to be spoken naturally within that time. 
   - If the direct translation is too long, YOU MUST SUMMARIZE OR REPHRASE it to be shorter.
   - Do NOT rush the speaker. It is better to have a shorter, concise sentence than a fast, rushed one.
   
2. **Conversation Style**: Use natural, colloquial (spoken) {language_name}. 
   - You can use common English words (like "Time", "Mobile", "School", "Bus", "Train") if they are commonly used in daily {language_name} conversation.
   - Avoid formal/bookish {language_name}. Write how a friend talks to another friend.

3. **Context**: This is likely a movie recap or storytelling video. Keep the tone engaging and synchronized with the flow.

Input segments:
{json.dumps(texts_to_translate, indent=2)}

Return format (JSON array only, no markdown):
[
  {{"index": 0, "translation": "Condensed {language_name} translation that fits duration"}},
  {{"index": 1, "translation": "Short and natural {language_name}"}},
  ...
]

Translate now:"""


    print(f"⏳ Translating to {language_name} with Gemini ({GEMINI_MODEL})...")
    
    # Configure safety settings to be permissive for translation
    # This is needed because movie recap content may trigger safety filters
    safety_settings = [
        types.SafetySetting(
            category="HARM_CATEGORY_HARASSMENT",
            threshold="BLOCK_NONE"
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_HATE_SPEECH",
            threshold="BLOCK_NONE"
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
            threshold="BLOCK_NONE"
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="BLOCK_NONE"
        ),
    ]
    
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            safety_settings=safety_settings
        )
    )
    
    # Save Gemini input/output for debugging
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_dir = OUTPUT_DIR / "gemini_logs"
    logs_dir.mkdir(exist_ok=True)
    
    # Save input (prompt)
    input_file = logs_dir / f"{timestamp}_input.txt"
    with open(input_file, 'w', encoding='utf-8') as f:
        f.write("=== GEMINI INPUT ===\n")
        f.write(f"Model: {GEMINI_MODEL}\n")
        f.write(f"Timestamp: {timestamp}\n\n")
        f.write("=== PROMPT ===\n")
        f.write(prompt)
    
    # Handle empty or None response
    if response is None:
        raise ValueError("Gemini returned no response")
    
    # Debug: print response object info
    print(f"  Response received, extracting text...")
    
    # Access response text properly - try multiple methods
    response_text = None
    
    # Method 1: Direct .text attribute (most common)
    try:
        if hasattr(response, 'text') and response.text:
            response_text = response.text.strip()
    except Exception as e:
        print(f"  Method 1 failed: {e}")
    
    # Method 2: Through candidates
    if not response_text:
        try:
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and candidate.content:
                    if hasattr(candidate.content, 'parts') and candidate.content.parts:
                        response_text = candidate.content.parts[0].text.strip()
        except Exception as e:
            print(f"  Method 2 failed: {e}")
    
    if not response_text:
        # Print full response for debugging
        print(f"  Full response object: {response}")
        if hasattr(response, 'candidates'):
            print(f"  Candidates: {response.candidates}")
        raise ValueError("Could not extract text from Gemini response - may be a content policy block")
    
    # Save output (response)
    output_file = logs_dir / f"{timestamp}_output.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=== GEMINI OUTPUT ===\n")
        f.write(f"Model: {GEMINI_MODEL}\n")
        f.write(f"Timestamp: {timestamp}\n\n")
        f.write("=== RAW RESPONSE ===\n")
        f.write(response_text)
    
    print(f"  Logs saved to: {logs_dir}")
    
    # Clean up response - remove markdown code blocks if present
    if response_text.startswith('```'):
        response_text = re.sub(r'^```json?\n?', '', response_text)
        response_text = re.sub(r'\n?```$', '', response_text)
    
    try:
        translations = json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"⚠ Error parsing Gemini response: {e}")
        print(f"Response was: {response_text[:500]}...")
        raise ValueError("Failed to parse translation response from Gemini")
    
    # Create translated segments
    translated_segments = []
    translation_map = {t['index']: t.get('translation', t.get('telugu', '')) for t in translations}
    
    for i, seg in enumerate(segments):
        translated_text = translation_map.get(i, seg.text)
        translated_segments.append(TranscriptSegment(
            text=translated_text,
            start=seg.start,
            end=seg.end
        ))
    
    print(f"✓ Translated {len(translated_segments)} segments to {language_name}")
    return translated_segments
