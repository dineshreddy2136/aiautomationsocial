// YouTube Dubber - Frontend Logic

const API_BASE = '';

// Tab Navigation
document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
        // Update nav
        document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');

        // Update tabs
        const tabId = item.dataset.tab + '-tab';
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        document.getElementById(tabId).classList.add('active');

        // Load gallery if switching to it
        if (item.dataset.tab === 'gallery') {
            loadVideos();
        }
        if (item.dataset.tab === 'audio') {
            loadMusicFiles();
        }
    });
});

// Music checkbox toggle
document.getElementById('add-music').addEventListener('change', (e) => {
    const musicOptions = document.getElementById('music-options');
    if (e.target.checked) {
        musicOptions.classList.remove('hidden');
        loadMusicDropdown();
    } else {
        musicOptions.classList.add('hidden');
    }
});

// Volume slider
document.getElementById('music-volume').addEventListener('input', (e) => {
    document.getElementById('volume-value').textContent = e.target.value;
});

// Load music files for dropdown
async function loadMusicDropdown() {
    try {
        const res = await fetch(API_BASE + '/api/music-files');
        const files = await res.json();
        const select = document.getElementById('music-select');
        select.innerHTML = files.map(f => `<option value="${f}">${f}</option>`).join('');
    } catch (err) {
        console.error('Failed to load music files:', err);
    }
}

// Dub Video
document.getElementById('dub-btn').addEventListener('click', async () => {
    const url = document.getElementById('url-input').value.trim();
    const language = document.getElementById('language-select').value;
    const addMusic = document.getElementById('add-music').checked;
    const musicFile = document.getElementById('music-select').value;
    const musicVolume = parseInt(document.getElementById('music-volume').value);

    if (!url) {
        alert('Please enter a YouTube URL');
        return;
    }

    // Show progress, hide result
    document.getElementById('progress-section').classList.remove('hidden');
    document.getElementById('result-section').classList.add('hidden');
    document.getElementById('log-output').textContent = '🚀 Starting dubbing process...\n';
    document.getElementById('progress-fill').style.width = '5%';
    document.getElementById('dub-btn').disabled = true;

    try {
        const response = await fetch(API_BASE + '/api/dub', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url,
                language,
                add_music: addMusic,
                music_file: addMusic ? musicFile : null,
                music_volume: addMusic ? musicVolume / 100 : 0.3
            })
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let fullOutput = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const text = decoder.decode(value);
            fullOutput += text;
            document.getElementById('log-output').textContent = fullOutput;
            document.getElementById('log-output').scrollTop = document.getElementById('log-output').scrollHeight;

            // Update progress based on content
            if (fullOutput.includes('Step 1')) document.getElementById('progress-fill').style.width = '20%';
            if (fullOutput.includes('Step 2')) document.getElementById('progress-fill').style.width = '35%';
            if (fullOutput.includes('Step 3')) document.getElementById('progress-fill').style.width = '50%';
            if (fullOutput.includes('Step 4')) document.getElementById('progress-fill').style.width = '70%';
            if (fullOutput.includes('Step 5')) document.getElementById('progress-fill').style.width = '85%';
            if (fullOutput.includes('Success')) document.getElementById('progress-fill').style.width = '100%';
        }

        if (fullOutput.includes('Success')) {
            // Extract video/audio paths from output
            const videoMatch = fullOutput.match(/Video: (.+\.mp4)/);
            const audioMatch = fullOutput.match(/Audio: (.+\.mp3)/);

            if (videoMatch) {
                const videoPath = videoMatch[1];
                const videoName = videoPath.split('/').pop();
                document.getElementById('result-video').src = API_BASE + '/videos/' + videoName;
                document.getElementById('download-video-btn').href = API_BASE + '/videos/' + videoName;
            }

            if (audioMatch) {
                const audioPath = audioMatch[1];
                const audioName = audioPath.split('/').pop();
                document.getElementById('download-audio-btn').href = API_BASE + '/output/' + audioName;
            }

            document.getElementById('result-section').classList.remove('hidden');
        }

    } catch (err) {
        document.getElementById('log-output').textContent += '\n❌ Error: ' + err.message;
    } finally {
        document.getElementById('dub-btn').disabled = false;
    }
});

// Load videos gallery
async function loadVideos() {
    try {
        const res = await fetch(API_BASE + '/api/videos');
        const videos = await res.json();
        const grid = document.getElementById('video-grid');

        if (videos.length === 0) {
            grid.innerHTML = '<p style="color: var(--text-secondary);">No videos yet. Dub your first video!</p>';
            return;
        }

        grid.innerHTML = videos.map(v => `
            <div class="video-card" data-video="${v.name}">
                <video src="${API_BASE}/videos/${v.name}" preload="metadata"></video>
                <div class="video-card-info">
                    <p class="video-card-title">${v.name}</p>
                </div>
            </div>
        `).join('');

        // Add click handlers
        document.querySelectorAll('.video-card').forEach(card => {
            card.addEventListener('click', () => {
                const videoName = card.dataset.video;
                showVideoModal(videoName);
            });
        });
    } catch (err) {
        console.error('Failed to load videos:', err);
    }
}

// Video Modal with Plyr
let modalPlayer = null;

function showVideoModal(videoName) {
    const modal = document.getElementById('video-modal');
    const video = document.getElementById('modal-video');
    const title = document.getElementById('modal-title');

    video.src = API_BASE + '/videos/' + videoName;
    title.textContent = videoName;
    modal.classList.remove('hidden');

    // Initialize Plyr with custom options
    if (modalPlayer) {
        modalPlayer.destroy();
    }
    modalPlayer = new Plyr('#modal-video', {
        controls: ['play-large', 'play', 'progress', 'current-time', 'mute', 'volume', 'fullscreen'],
        autoplay: true
    });
}

function closeVideoModal() {
    document.getElementById('video-modal').classList.add('hidden');
    if (modalPlayer) {
        modalPlayer.pause();
        modalPlayer.destroy();
        modalPlayer = null;
    }
}

document.querySelector('.modal-close').addEventListener('click', closeVideoModal);

document.getElementById('video-modal').addEventListener('click', (e) => {
    if (e.target.id === 'video-modal') {
        closeVideoModal();
    }
});

document.getElementById('refresh-gallery-btn').addEventListener('click', loadVideos);

// Download Audio
document.getElementById('download-audio-btn-main').addEventListener('click', async () => {
    const url = document.getElementById('audio-url-input').value.trim();
    if (!url) {
        alert('Please enter a YouTube URL');
        return;
    }

    document.getElementById('audio-log-output').textContent = '📥 Downloading audio...\n';
    document.getElementById('download-audio-btn-main').disabled = true;

    try {
        const response = await fetch(API_BASE + '/api/download-audio', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let fullOutput = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            fullOutput += decoder.decode(value);
            document.getElementById('audio-log-output').textContent = fullOutput;
        }

        loadMusicFiles();
    } catch (err) {
        document.getElementById('audio-log-output').textContent += '\n❌ Error: ' + err.message;
    } finally {
        document.getElementById('download-audio-btn-main').disabled = false;
    }
});

// Load music files list
async function loadMusicFiles() {
    try {
        const res = await fetch(API_BASE + '/api/music-files');
        const files = await res.json();
        const list = document.getElementById('music-list');
        list.innerHTML = files.map(f => `<li>${f}</li>`).join('');
    } catch (err) {
        console.error('Failed to load music files:', err);
    }
}

// Initial load
loadMusicFiles();
