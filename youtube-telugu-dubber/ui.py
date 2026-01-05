#!/usr/bin/env python3
"""
Gradio UI for YouTube Dubber
"""

import gradio as gr
from pathlib import Path
import subprocess
import sys
import threading
import queue

from config import (
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    OUTPUT_DIR,
    AUDIO_DIR,
    VIDEOS_DIR
)


def get_music_files():
    """Get list of available music files"""
    files = list(AUDIO_DIR.glob("*.mp3"))
    return [f.name for f in files] if files else ["No music files available"]


def get_video_files():
    """Get list of dubbed videos"""
    files = sorted(VIDEOS_DIR.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)
    return [(str(f), f.name) for f in files]


def run_process_with_output(cmd, cwd):
    """Run a process and yield output lines"""
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=cwd
    )
    
    output_lines = []
    for line in iter(process.stdout.readline, ''):
        output_lines.append(line)
        yield ''.join(output_lines)
    
    process.wait()
    return process.returncode


def dub_video(url, language, add_music, music_file, music_volume):
    """Run the dubbing pipeline with streaming output"""
    if not url:
        yield None, None, "❌ Please enter a YouTube URL"
        return
    
    # Build command
    cmd = [
        sys.executable, "main.py",
        "--url", url,
        "--language", language
    ]
    
    if add_music and music_file and music_file != "No music files available":
        cmd.extend(["--add-music", "--music-file", music_file, "--music-volume", str(music_volume / 100)])
    
    yield None, None, "🚀 Starting dubbing process...\n"
    
    # Run with streaming output
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(Path(__file__).parent)
    )
    
    output_lines = []
    for line in iter(process.stdout.readline, ''):
        output_lines.append(line)
        yield None, None, ''.join(output_lines)
    
    process.wait()
    
    full_output = ''.join(output_lines)
    
    if process.returncode != 0:
        yield None, None, f"❌ Error:\n{full_output}"
        return
    
    # Find the most recent output files
    video_files = sorted(VIDEOS_DIR.glob(f"*_{language}.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)
    audio_files = sorted(OUTPUT_DIR.glob(f"*_{language}.mp3"), key=lambda x: x.stat().st_mtime, reverse=True)
    
    video_path = str(video_files[0]) if video_files else None
    audio_path = str(audio_files[0]) if audio_files else None
    
    yield video_path, audio_path, f"✅ Done!\n\n{full_output}"


def refresh_gallery():
    """Refresh the video gallery"""
    videos = get_video_files()
    return [v[0] for v in videos]


# Language choices for dropdown
language_choices = [(name, code) for code, name in SUPPORTED_LANGUAGES.items()]

# Create the UI
with gr.Blocks(title="YouTube Dubber", theme=gr.themes.Soft()) as app:
    gr.Markdown("# 🎬 YouTube Indian Language Dubber")
    gr.Markdown("Dub YouTube videos into 12 Indian languages with AI voiceover")
    
    with gr.Tabs():
        # Tab 1: Dub Video
        with gr.Tab("🎙️ Dub Video"):
            with gr.Row():
                with gr.Column(scale=2):
                    url_input = gr.Textbox(
                        label="YouTube URL",
                        placeholder="https://youtube.com/shorts/...",
                        lines=1
                    )
                    
                    language_dropdown = gr.Dropdown(
                        choices=language_choices,
                        value=DEFAULT_LANGUAGE,
                        label="Target Language"
                    )
                    
                    with gr.Accordion("🎵 Background Music (Optional)", open=False):
                        add_music_checkbox = gr.Checkbox(label="Add Background Music", value=False)
                        music_dropdown = gr.Dropdown(
                            choices=get_music_files(),
                            label="Select Music File",
                            interactive=True
                        )
                        music_volume_slider = gr.Slider(
                            minimum=0, maximum=100, value=30,
                            label="Music Volume (%)"
                        )
                    
                    dub_button = gr.Button("🚀 Dub Video", variant="primary", size="lg")
                
                with gr.Column(scale=3):
                    output_log = gr.Textbox(label="Live Progress", lines=20, interactive=False, autoscroll=True)
            
            with gr.Row():
                video_output = gr.Video(label="Dubbed Video", format="mp4")
                audio_output = gr.Audio(label="Dubbed Audio", format="mp3")
            
            # Connect the button
            dub_button.click(
                fn=dub_video,
                inputs=[url_input, language_dropdown, add_music_checkbox, music_dropdown, music_volume_slider],
                outputs=[video_output, audio_output, output_log]
            )
        
        # Tab 2: Video Gallery
        with gr.Tab("📁 My Videos"):
            gr.Markdown("### Your Dubbed Videos")
            gr.Markdown(f"Videos are saved to: `{VIDEOS_DIR}`")
            
            refresh_btn = gr.Button("🔄 Refresh", size="sm")
            
            video_gallery = gr.Gallery(
                label="Dubbed Videos",
                show_label=False,
                columns=3,
                object_fit="contain",
                height="auto",
                type="filepath"
            )
            
            selected_video = gr.Video(label="Selected Video", format="mp4")
            
            def load_videos():
                videos = get_video_files()
                return [v[0] for v in videos]
            
            def play_video(evt: gr.SelectData, gallery_data):
                if gallery_data and evt.index < len(gallery_data):
                    return gallery_data[evt.index]
                return None
            
            refresh_btn.click(fn=load_videos, outputs=video_gallery)
            video_gallery.select(fn=play_video, inputs=[video_gallery], outputs=selected_video)
            
            # Load on start
            app.load(fn=load_videos, outputs=video_gallery)
        
        # Tab 3: Download Audio
        with gr.Tab("🎵 Download Audio"):
            gr.Markdown("### Download Background Music from YouTube")
            
            audio_url_input = gr.Textbox(
                label="YouTube URL",
                placeholder="https://youtube.com/watch?v=...",
                lines=1
            )
            
            download_btn = gr.Button("📥 Download Audio", variant="secondary")
            download_status = gr.Textbox(label="Status", lines=5, interactive=False)
            
            def download_audio(url):
                if not url:
                    return "❌ Please enter a YouTube URL"
                
                cmd = [sys.executable, "main.py", "--url", url, "--download-audio"]
                result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).parent))
                return result.stdout + result.stderr
            
            download_btn.click(fn=download_audio, inputs=[audio_url_input], outputs=[download_status])
    
    gr.Markdown("---")
    gr.Markdown("💡 **CLI Usage:** `python main.py --url 'URL' --language hin`")


if __name__ == "__main__":
    app.launch(share=False)
