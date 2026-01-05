#!/usr/bin/env python3
"""
FastAPI Backend for YouTube Dubber Web UI
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from pathlib import Path
import subprocess
import sys
import os

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import AUDIO_DIR, VIDEOS_DIR, OUTPUT_DIR

app = FastAPI(title="YouTube Dubber API")

# Serve static files
FRONTEND_DIR = Path(__file__).parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# Serve videos and audio
app.mount("/videos", StaticFiles(directory=str(VIDEOS_DIR)), name="videos")
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")


class DubRequest(BaseModel):
    url: str
    language: str = "tel"
    add_music: bool = False
    music_file: str | None = None
    music_volume: float = 0.3


class DownloadRequest(BaseModel):
    url: str


@app.get("/")
async def index():
    """Serve the main HTML page"""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/music-files")
async def get_music_files():
    """Get list of available music files"""
    files = list(AUDIO_DIR.glob("*.mp3"))
    return [f.name for f in files]


@app.get("/api/videos")
async def get_videos():
    """Get list of dubbed videos"""
    files = sorted(VIDEOS_DIR.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)
    return [{"name": f.name, "size": f.stat().st_size} for f in files]


@app.post("/api/dub")
async def dub_video(request: DubRequest):
    """Run the dubbing pipeline with streaming output"""
    
    cmd = [
        sys.executable, "main.py",
        "--url", request.url,
        "--language", request.language
    ]
    
    if request.add_music and request.music_file:
        cmd.extend([
            "--add-music",
            "--music-file", request.music_file,
            "--music-volume", str(request.music_volume)
        ])
    
    async def generate():
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(Path(__file__).parent)
        )
        
        for line in iter(process.stdout.readline, ''):
            yield line
        
        process.wait()
    
    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/api/download-audio")
async def download_audio(request: DownloadRequest):
    """Download audio from YouTube"""
    
    cmd = [
        sys.executable, "main.py",
        "--url", request.url,
        "--download-audio"
    ]
    
    async def generate():
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(Path(__file__).parent)
        )
        
        for line in iter(process.stdout.readline, ''):
            yield line
        
        process.wait()
    
    return StreamingResponse(generate(), media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    print("\n🎬 YouTube Dubber Web UI")
    print("=" * 40)
    print("Open in browser: http://localhost:8000")
    print("=" * 40 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
