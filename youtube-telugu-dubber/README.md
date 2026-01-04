# YouTube Telugu Dubber

A CLI tool that automatically dubs YouTube videos into Telugu.

## Features

- Downloads YouTube videos (works great with Shorts)
- Extracts transcripts (YouTube captions or Whisper fallback)
- Translates to Telugu using Google Gemini
- Generates Telugu voiceover using Eleven Labs
- Produces final dubbed video with FFmpeg

## Installation

### Prerequisites

1. **Python 3.9+**
2. **FFmpeg** - Install via Homebrew:
   ```bash
   brew install ffmpeg
   ```

### Setup

```bash
cd youtube-telugu-dubber
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
```

## Configuration

Edit `.env` file with your API keys:

```
GEMINI_API_KEY=your_gemini_api_key
ELEVENLABS_API_KEY=your_elevenlabs_api_key
```

## Usage

```bash
# Basic usage
python main.py --url "https://www.youtube.com/shorts/VIDEO_ID"

# With custom output path
python main.py --url "https://www.youtube.com/shorts/VIDEO_ID" --output "my_video.mp4"

# With specific Eleven Labs voice
python main.py --url "https://www.youtube.com/shorts/VIDEO_ID" --voice "voice_id_here"
```

## API Keys

- **Gemini API**: https://aistudio.google.com/app/apikey
- **Eleven Labs API**: https://elevenlabs.io/
