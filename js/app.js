/**
 * app.js — Main coordinator for Aeterna
 * 
 * Wires together: UI ↔ AudioEngine ↔ IndexedDB ↔ ZipLoader
 */

import { AudioEngine } from './audio-engine.js';
import { saveSong, getSongStems, listSongs, deleteSong } from './db.js';
import { extractStemsFromZip, extractStemsFromFiles } from './zip-loader.js';

// ============================================================
// State
// ============================================================

const engine = new AudioEngine();
let currentSongId = null;
let animFrameId = null;

// ============================================================
// DOM References
// ============================================================

const $ = (id) => document.getElementById(id);

const dom = {
  statusDot:        $('status-dot'),
  statusText:       $('status-text'),
  uploadZone:       $('upload-zone'),
  fileInput:        $('file-input'),
  songListContent:  $('song-list-content'),
  transportName:    $('transport-song-name'),
  timeCurrent:      $('time-current'),
  timeTotal:        $('time-total'),
  seekBar:          $('seek-bar'),
  seekBarFill:      $('seek-bar-fill'),
  btnRewind:        $('btn-rewind'),
  btnPlay:          $('btn-play'),
  btnStop:          $('btn-stop'),
  stemsList:        $('stems-list'),
  stemsListContent: $('stems-list-content'),
  progressOverlay:  $('progress-overlay'),
  progressLabel:    $('progress-label'),
  progressDetail:   $('progress-detail'),
};

// ============================================================
// Utility
// ============================================================

function formatTime(seconds) {
  if (!seconds || !isFinite(seconds)) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

function showProgress(label, detail) {
  dom.progressLabel.textContent = label;
  dom.progressDetail.textContent = detail || '';
  dom.progressOverlay.classList.add('visible');
}

function updateProgress(label, detail) {
  dom.progressLabel.textContent = label;
  dom.progressDetail.textContent = detail || '';
}

function hideProgress() {
  dom.progressOverlay.classList.remove('visible');
}

function setStatus(state, text) {
  dom.statusDot.className = 'status-dot ' + state;
  dom.statusText.textContent = text;
}

// ============================================================
// Song List UI
// ============================================================

async function refreshSongList() {
  const songs = await listSongs();

  if (songs.length === 0) {
    dom.songListContent.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🎵</div>
        <div>Sube un multitrack para empezar</div>
      </div>
    `;
    return;
  }

  // Sort by newest first
  songs.sort((a, b) => b.createdAt - a.createdAt);

  dom.songListContent.innerHTML = songs.map(song => `
    <div class="song-card ${song.id === currentSongId ? 'active' : ''}" data-id="${song.id}">
      <div class="song-card-icon">🎶</div>
      <div class="song-card-info">
        <div class="song-card-name">${escapeHtml(song.name)}</div>
        <div class="song-card-meta">${song.stemCount} pistas</div>
      </div>
      <button class="song-card-delete" data-delete-id="${song.id}" title="Eliminar">🗑</button>
    </div>
  `).join('');

  // Attach click listeners
  dom.songListContent.querySelectorAll('.song-card').forEach(card => {
    card.addEventListener('click', (e) => {
      // Don't trigger load when clicking delete
      if (e.target.closest('.song-card-delete')) return;
      loadSong(card.dataset.id);
    });
  });

  dom.songListContent.querySelectorAll('.song-card-delete').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = btn.dataset.deleteId;
      if (currentSongId === id) {
        engine.stop();
        engine.tracks = [];
        engine._setState('idle');
        currentSongId = null;
        updateTransportUI();
      }
      await deleteSong(id);
      refreshSongList();
      setStatus('', 'Canción eliminada');
    });
  });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ============================================================
// File Upload
// ============================================================

async function handleFiles(files) {
  if (!files || files.length === 0) return;

  try {
    let stems;
    const firstFile = files[0];

    if (firstFile.name.toLowerCase().endsWith('.zip')) {
      // ZIP file
      showProgress('Extrayendo ZIP...', firstFile.name);
      stems = await extractStemsFromZip(firstFile, (current, total, name) => {
        updateProgress('Extrayendo ZIP...', `${current}/${total}: ${name}`);
      });
    } else {
      // Individual audio files
      stems = extractStemsFromFiles(files);
      if (stems.length === 0) {
        setStatus('error', 'No se encontraron archivos de audio válidos');
        return;
      }
    }

    // Generate a song name from the ZIP filename or first stem
    const songName = firstFile.name.toLowerCase().endsWith('.zip')
      ? firstFile.name.replace(/\.zip$/i, '').replace(/[_-]+/g, ' ').trim()
      : 'Multitrack ' + new Date().toLocaleDateString();

    const songId = generateId();

    // Save to IndexedDB
    updateProgress('Guardando en dispositivo...', `${stems.length} pistas`);
    await saveSong(songId, songName, stems);

    hideProgress();
    setStatus('ready', 'Multitrack guardado');

    // Refresh list and auto-load the new song
    await refreshSongList();
    await loadSong(songId);

  } catch (err) {
    hideProgress();
    setStatus('error', err.message);
    console.error('Upload error:', err);
  }
}

// ============================================================
// Song Loading
// ============================================================

async function loadSong(songId) {
  try {
    // Stop current playback
    if (engine.state === 'playing') {
      engine.stop();
    }
    stopTimeUpdate();

    currentSongId = songId;
    refreshSongList();

    // Get stems from IndexedDB
    showProgress('Cargando pistas...', 'Leyendo desde almacenamiento');
    const stems = await getSongStems(songId);

    if (!stems || stems.length === 0) {
      hideProgress();
      setStatus('error', 'No se encontraron pistas');
      return;
    }

    // Decode sequentially (the key optimization)
    engine.onDecodeProgress = (current, total, name) => {
      updateProgress('Decodificando audio...', `${current}/${total}: ${name}`);
    };

    await engine.loadStems(stems);

    hideProgress();

    // Update UI with loaded song info
    const songs = await listSongs();
    const songMeta = songs.find(s => s.id === songId);
    dom.transportName.textContent = songMeta ? songMeta.name : 'Multitrack';
    dom.transportName.classList.remove('empty');

    // Show stems list
    renderStemsList();

    // Update transport
    updateTransportUI();

    setStatus('ready', `${engine.tracks.length} pistas listas`);

  } catch (err) {
    hideProgress();
    setStatus('error', err.message);
    console.error('Load error:', err);
  }
}

function renderStemsList() {
  if (engine.tracks.length === 0) {
    dom.stemsList.classList.add('hidden');
    return;
  }

  dom.stemsList.classList.remove('hidden');
  dom.stemsListContent.innerHTML = engine.tracks.map(track => `
    <div class="stem-item">
      <div class="stem-indicator"></div>
      <span class="stem-name">${escapeHtml(track.name)}</span>
    </div>
  `).join('');
}

// ============================================================
// Transport / Playback Controls
// ============================================================

function updateTransportUI() {
  const hasTrack = engine.tracks.length > 0;
  const isPlaying = engine.state === 'playing';

  dom.btnPlay.disabled = !hasTrack;
  dom.btnStop.disabled = !hasTrack;
  dom.btnRewind.disabled = !hasTrack;

  dom.btnPlay.textContent = isPlaying ? '⏸' : '▶';
  dom.btnPlay.title = isPlaying ? 'Pausar' : 'Reproducir';

  dom.timeTotal.textContent = formatTime(engine.getDuration());

  if (!hasTrack) {
    dom.transportName.textContent = 'Ninguna canción seleccionada';
    dom.transportName.classList.add('empty');
    dom.timeCurrent.textContent = '0:00';
    dom.timeTotal.textContent = '0:00';
    dom.seekBarFill.style.width = '0%';
    dom.stemsList.classList.add('hidden');
  }
}

function startTimeUpdate() {
  stopTimeUpdate();

  function update() {
    const current = engine.getCurrentTime();
    const duration = engine.getDuration();

    dom.timeCurrent.textContent = formatTime(current);
    
    if (duration > 0) {
      const pct = (current / duration) * 100;
      dom.seekBarFill.style.width = pct + '%';
    }

    animFrameId = requestAnimationFrame(update);
  }

  animFrameId = requestAnimationFrame(update);
}

function stopTimeUpdate() {
  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }
}

// ============================================================
// Engine State Listener
// ============================================================

engine.onStateChange = (state) => {
  updateTransportUI();

  switch (state) {
    case 'playing':
      setStatus('playing', 'Reproduciendo');
      startTimeUpdate();
      break;
    case 'ready':
      setStatus('ready', `${engine.tracks.length} pistas listas`);
      stopTimeUpdate();
      // Update time display one last time
      dom.timeCurrent.textContent = formatTime(engine.getCurrentTime());
      break;
    case 'loading':
      setStatus('loading', 'Decodificando...');
      break;
    case 'idle':
      setStatus('', 'Listo para cargar');
      stopTimeUpdate();
      break;
  }
};

// ============================================================
// Event Listeners
// ============================================================

// File input
dom.fileInput.addEventListener('change', (e) => {
  handleFiles(e.target.files);
  // Reset so same file can be re-selected
  e.target.value = '';
});

// Drag & Drop
dom.uploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dom.uploadZone.classList.add('drag-over');
});

dom.uploadZone.addEventListener('dragleave', () => {
  dom.uploadZone.classList.remove('drag-over');
});

dom.uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dom.uploadZone.classList.remove('drag-over');
  handleFiles(e.dataTransfer.files);
});

// Play / Pause
dom.btnPlay.addEventListener('click', () => {
  if (engine.state === 'playing') {
    engine.stop();
  } else if (engine.state === 'ready') {
    engine.play();
  }
});

// Stop
dom.btnStop.addEventListener('click', () => {
  engine.stop();
  engine._playOffset = 0;
  dom.timeCurrent.textContent = '0:00';
  dom.seekBarFill.style.width = '0%';
});

// Rewind
dom.btnRewind.addEventListener('click', () => {
  engine.rewind();
  dom.timeCurrent.textContent = '0:00';
  dom.seekBarFill.style.width = '0%';
});

// Seek bar interaction
let isSeeking = false;

function handleSeek(e) {
  const rect = dom.seekBar.getBoundingClientRect();
  const x = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
  const pct = Math.max(0, Math.min(1, x / rect.width));
  const time = pct * engine.getDuration();
  
  dom.seekBarFill.style.width = (pct * 100) + '%';
  dom.timeCurrent.textContent = formatTime(time);
  
  return time;
}

dom.seekBar.addEventListener('mousedown', (e) => {
  if (engine.tracks.length === 0) return;
  isSeeking = true;
  dom.seekBar.classList.add('seeking');
  const time = handleSeek(e);
  engine.seek(time);
});

dom.seekBar.addEventListener('touchstart', (e) => {
  if (engine.tracks.length === 0) return;
  isSeeking = true;
  dom.seekBar.classList.add('seeking');
  const time = handleSeek(e);
  engine.seek(time);
}, { passive: true });

document.addEventListener('mousemove', (e) => {
  if (!isSeeking) return;
  const time = handleSeek(e);
  engine.seek(time);
});

document.addEventListener('touchmove', (e) => {
  if (!isSeeking) return;
  const time = handleSeek(e);
  engine.seek(time);
}, { passive: true });

document.addEventListener('mouseup', () => {
  if (!isSeeking) return;
  isSeeking = false;
  dom.seekBar.classList.remove('seeking');
});

document.addEventListener('touchend', () => {
  if (!isSeeking) return;
  isSeeking = false;
  dom.seekBar.classList.remove('seeking');
});

// ============================================================
// Keyboard Shortcuts
// ============================================================

document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT') return;

  switch (e.code) {
    case 'Space':
      e.preventDefault();
      dom.btnPlay.click();
      break;
    case 'Escape':
      dom.btnStop.click();
      break;
  }
});

// ============================================================
// PWA Service Worker Registration
// ============================================================

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(err => {
    console.warn('SW registration failed:', err);
  });
}

// Request persistent storage so the browser doesn't evict our audio cache
if (navigator.storage && navigator.storage.persist) {
  navigator.storage.persist();
}

// ============================================================
// Init
// ============================================================

refreshSongList();
