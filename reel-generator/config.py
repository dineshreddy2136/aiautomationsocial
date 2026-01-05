"""
Configuration for Reel Generator
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Directories
BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"

# Create directories
TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Whisper settings
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "") or "base"

# Gemini settings
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")

# Reel settings
DEFAULT_REEL_DURATION = 60  # seconds
MIN_CLIP_DURATION = 3       # minimum clip length in seconds
MAX_CLIP_DURATION = 15      # maximum clip length in seconds


def validate_config():
    """Validate that required configuration is present."""
    errors = []
    
    if not GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY is not set")
    
    if errors:
        raise ValueError("\\n".join(errors))
