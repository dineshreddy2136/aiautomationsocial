"""
Configuration management for YouTube Telugu Dubber
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

# Model configuration
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_v3")

# Eleven Labs default voice (multilingual voice that supports Telugu)
DEFAULT_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pFZP5JQG7iQjIQuC4Bku")  # Lily - multilingual

# Audio settings
AUDIO_SPEED = float(os.getenv("AUDIO_SPEED", "1.6"))  # 1.0 = normal, 1.6 = faster (default)

# Paths
PROJECT_ROOT = Path(__file__).parent
TEMP_DIR = PROJECT_ROOT / "temp"
OUTPUT_DIR = PROJECT_ROOT / "output"
AUDIO_DIR = PROJECT_ROOT / "audio"

# Ensure directories exist
TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)

# Whisper model (used as fallback for transcription)
WHISPER_MODEL = "base"  # Options: tiny, base, small, medium, large

def validate_config():
    """Validate that required API keys are set"""
    errors = []
    
    if not GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY not set in .env file")
    
    if not ELEVENLABS_API_KEY:
        errors.append("ELEVENLABS_API_KEY not set in .env file")
    
    if errors:
        raise ValueError("Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))
