/**
 * audio-engine.js — Core multitrack audio engine for Aeterna
 * 
 * Design principles:
 * - Single shared AudioContext for all tracks
 * - Sequential decoding to avoid CPU spikes on mobile
 * - Sample-accurate sync via audioCtx.currentTime
 * - Minimal node graph: Source → Gain → Master → Destination
 */

export class AudioEngine {
  constructor() {
    /** @type {AudioContext|null} */
    this.ctx = null;
    
    /** @type {GainNode|null} */
    this.masterGain = null;
    
    /** @type {Array<{name: string, buffer: AudioBuffer}>} */
    this.tracks = [];
    
    /** @type {Array<{source: AudioBufferSourceNode, gain: GainNode}>} */
    this.activeSources = [];
    
    /** @type {'idle'|'loading'|'ready'|'playing'} */
    this.state = 'idle';
    
    /** @type {number} Scheduled start time in AudioContext clock */
    this._playStartTime = 0;
    
    /** @type {number} Offset when resuming after pause/seek */
    this._playOffset = 0;
    
    /** @type {function|null} State change callback */
    this.onStateChange = null;
    
    /** @type {function|null} Decode progress callback */
    this.onDecodeProgress = null;
  }

  /**
   * Initialize AudioContext. MUST be called from a user gesture (click/tap).
   */
  init() {
    if (this.ctx) return;

    this.ctx = new (window.AudioContext || window.webkitAudioContext)({
      // 44100 matches most stems, avoids forced resampling on mobile
      sampleRate: 44100
    });

    this.masterGain = this.ctx.createGain();
    this.masterGain.connect(this.ctx.destination);
  }

  /**
   * Ensure AudioContext is running (mobile browsers suspend it)
   */
  async _ensureResumed() {
    if (this.ctx && this.ctx.state === 'suspended') {
      await this.ctx.resume();
    }
  }

  /**
   * Load and decode audio blobs into AudioBuffers — SEQUENTIALLY
   * This is the key optimization: decoding one at a time prevents
   * CPU spikes that crash mobile browsers.
   * 
   * @param {Array<{name: string, blob: Blob}>} stems
   */
  async loadStems(stems) {
    this.init();
    await this._ensureResumed();

    this._setState('loading');
    this.tracks = [];

    for (let i = 0; i < stems.length; i++) {
      const stem = stems[i];

      if (this.onDecodeProgress) {
        this.onDecodeProgress(i + 1, stems.length, stem.name);
      }

      try {
        const arrayBuffer = await stem.blob.arrayBuffer();
        const audioBuffer = await this.ctx.decodeAudioData(arrayBuffer);

        this.tracks.push({
          name: stem.name,
          buffer: audioBuffer
        });
      } catch (err) {
        console.warn(`Failed to decode "${stem.name}":`, err);
        // Skip undecodable stems instead of crashing
      }
    }

    if (this.tracks.length === 0) {
      this._setState('idle');
      throw new Error('No se pudo decodificar ninguna pista de audio.');
    }

    this._playOffset = 0;
    this._setState('ready');
  }

  /**
   * Get total duration (longest track determines the song length)
   * @returns {number} Duration in seconds
   */
  getDuration() {
    if (this.tracks.length === 0) return 0;
    return Math.max(...this.tracks.map(t => t.buffer.duration));
  }

  /**
   * Get current playback position
   * @returns {number} Current time in seconds
   */
  getCurrentTime() {
    if (this.state !== 'playing') return this._playOffset;
    
    const elapsed = this.ctx.currentTime - this._playStartTime;
    const current = this._playOffset + elapsed;
    const duration = this.getDuration();
    
    return Math.min(current, duration);
  }

  /**
   * Play all tracks synchronized from current offset
   */
  async play() {
    if (this.state === 'playing') return;
    if (this.tracks.length === 0) return;

    await this._ensureResumed();

    // Clean up any lingering sources
    this._stopSources();

    // Schedule all tracks to start at the exact same moment
    // The 0.05s buffer gives the browser time to set up all nodes
    const startTime = this.ctx.currentTime + 0.05;
    this._playStartTime = startTime;

    for (const track of this.tracks) {
      const source = this.ctx.createBufferSource();
      source.buffer = track.buffer;

      const gain = this.ctx.createGain();
      
      source.connect(gain);
      gain.connect(this.masterGain);

      // Start at the scheduled time, with offset for seeking
      const offset = Math.min(this._playOffset, track.buffer.duration);
      const remaining = track.buffer.duration - offset;

      if (remaining > 0) {
        source.start(startTime, offset);
      }

      source.onended = () => {
        source.disconnect();
        gain.disconnect();
      };

      this.activeSources.push({ source, gain });
    }

    this._setState('playing');

    // Auto-stop when the longest track ends
    const duration = this.getDuration();
    const remaining = duration - this._playOffset;
    if (remaining > 0) {
      this._endTimer = setTimeout(() => {
        if (this.state === 'playing') {
          this._playOffset = 0;
          this._stopSources();
          this._setState('ready');
        }
      }, (remaining + 0.1) * 1000);
    }
  }

  /**
   * Stop playback and reset to current position
   */
  stop() {
    if (this.state !== 'playing') return;

    // Save current position before stopping
    this._playOffset = this.getCurrentTime();
    this._stopSources();
    this._setState('ready');
  }

  /**
   * Seek to a specific time position
   * @param {number} time - Time in seconds
   */
  seek(time) {
    const duration = this.getDuration();
    this._playOffset = Math.max(0, Math.min(time, duration));

    if (this.state === 'playing') {
      // Stop and restart from new position
      this._stopSources();
      this._setState('ready');
      this.play();
    }
  }

  /**
   * Reset to beginning
   */
  rewind() {
    this.seek(0);
  }

  /**
   * Clean up all source nodes
   */
  _stopSources() {
    if (this._endTimer) {
      clearTimeout(this._endTimer);
      this._endTimer = null;
    }

    for (const { source, gain } of this.activeSources) {
      try {
        source.stop();
        source.disconnect();
        gain.disconnect();
      } catch (e) {
        // Already stopped
      }
    }
    this.activeSources = [];
  }

  /**
   * Update state and notify listener
   * @param {'idle'|'loading'|'ready'|'playing'} newState
   */
  _setState(newState) {
    this.state = newState;
    if (this.onStateChange) {
      this.onStateChange(newState);
    }
  }

  /**
   * Destroy engine and release resources
   */
  destroy() {
    this._stopSources();
    this.tracks = [];
    if (this.ctx) {
      this.ctx.close();
      this.ctx = null;
    }
    this._setState('idle');
  }
}
