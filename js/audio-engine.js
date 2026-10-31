/**
 * audio-engine.js — Core multitrack audio engine for Aeterna
 * 
 * Design principles:
 * - Single shared AudioContext matching hardware native sample rate (no forced resampling)
 * - Sequential decoding with garbage collection pauses to prevent mobile CPU/RAM spikes
 * - Smart mono optimization: stems with identical stereo channels are kept as 1-channel, saving 50% RAM
 * - Sample-accurate sync via audioCtx.currentTime
 * - Minimal node graph: Source → Gain → Master → Destination
 */

import { parseWavToAudioBuffer } from './fast-wav-parser.js';

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

    // Use native hardware sample rate to avoid audio glitches and heavy resampling overhead
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    this.ctx = new AudioContextClass();

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
   * If a stem has 2 channels (stereo) but both channels are identical
   * (e.g. click, cue, bass, lead vocals bounced as stereo in DAWs),
   * downmix it to a 1-channel buffer. Web Audio will center-pan it to stereo automatically,
   * saving 50% of the RAM for that track!
   * 
   * @param {AudioBuffer} audioBuffer
   * @returns {AudioBuffer}
   */
  _optimizeBuffer(audioBuffer) {
    if (audioBuffer.numberOfChannels !== 2) return audioBuffer;

    const ch0 = audioBuffer.getChannelData(0);
    const ch1 = audioBuffer.getChannelData(1);
    const len = ch0.length;

    // Fast check: sample 1000 points across the track
    let isIdentical = true;
    const step = Math.max(1, Math.floor(len / 1000));
    for (let i = 0; i < len; i += step) {
      if (Math.abs(ch0[i] - ch1[i]) > 0.0001) {
        isIdentical = false;
        break;
      }
    }

    if (!isIdentical) {
      return audioBuffer;
    }

    // It's a mono track exported as stereo! Downmix to 1 channel
    const monoBuffer = this.ctx.createBuffer(1, len, audioBuffer.sampleRate);
    monoBuffer.copyToChannel(ch0, 0);
    return monoBuffer;
  }

  /**
   * Load and decode audio blobs into AudioBuffers — SEQUENTIALLY
   * Decoding one at a time with GC breathing room prevents mobile crashes.
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
        let arrayBuffer = await stem.blob.arrayBuffer();

        // ⚡ FAST PATH: Direct WAV PCM parser (< 50ms per track, no media pipeline delay)
        let audioBuffer = parseWavToAudioBuffer(arrayBuffer, this.ctx);

        // SLOW PATH FALLBACK: If not standard WAV (e.g. MP3, AAC, OGG), use standard decodeAudioData
        if (!audioBuffer) {
          audioBuffer = await this.ctx.decodeAudioData(arrayBuffer);
          audioBuffer = this._optimizeBuffer(audioBuffer);
        }

        arrayBuffer = null; // Free raw buffer immediately

        this.tracks.push({
          name: stem.name,
          buffer: audioBuffer
        });
      } catch (err) {
        console.warn(`Failed to decode "${stem.name}":`, err);
      }

      // Small pause to allow GC to run and keep the UI responsive between stems
      await new Promise(r => setTimeout(r, 40));
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
    // 0.05s buffer gives the audio thread time to prepare
    const startTime = this.ctx.currentTime + 0.05;
    this._playStartTime = startTime;

    for (const track of this.tracks) {
      const source = this.ctx.createBufferSource();
      source.buffer = track.buffer;

      const gain = this.ctx.createGain();
      source.connect(gain);
      gain.connect(this.masterGain);

      const offset = Math.min(this._playOffset, track.buffer.duration);
      const remaining = track.buffer.duration - offset;

      if (remaining > 0) {
        source.start(startTime, offset);
      }

      source.onended = () => {
        try {
          source.disconnect();
          gain.disconnect();
        } catch (e) {}
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
   * Stop playback and save current position
   */
  stop() {
    if (this.state !== 'playing') return;

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
      } catch (e) {}
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
