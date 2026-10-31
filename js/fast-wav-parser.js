/**
 * fast-wav-parser.js — Instant WAV to AudioBuffer parser for Aeterna
 * 
 * Bypasses the slow AudioContext.decodeAudioData() pipeline for uncompressed WAV files.
 * Directly decodes 16-bit, 24-bit, and 32-bit float PCM into AudioBuffers in milliseconds.
 * Also automatically downmixes identical stereo channels to mono to save 50% RAM.
 */

export function parseWavToAudioBuffer(arrayBuffer, ctx) {
  if (!arrayBuffer || arrayBuffer.byteLength < 44) return null;

  const dataView = new DataView(arrayBuffer);

  // Check 'RIFF' and 'WAVE'
  if (dataView.getUint32(0, false) !== 0x52494646) return null; // 'RIFF'
  if (dataView.getUint32(8, false) !== 0x57415645) return null; // 'WAVE'

  let offset = 12;
  const len = arrayBuffer.byteLength;

  let audioFormat = 0;
  let numChannels = 0;
  let sampleRate = 0;
  let bitsPerSample = 0;
  let dataOffset = 0;
  let dataLength = 0;

  // Walk RIFF chunks to find 'fmt ' and 'data' (handles metadata chunks like 'bext', 'JUNK', etc.)
  while (offset < len - 8) {
    const chunkId = dataView.getUint32(offset, false);
    const chunkSize = dataView.getUint32(offset + 4, true);
    const chunkDataOffset = offset + 8;

    if (chunkId === 0x666d7420) { // 'fmt '
      audioFormat = dataView.getUint16(chunkDataOffset, true);
      numChannels = dataView.getUint16(chunkDataOffset + 2, true);
      sampleRate = dataView.getUint32(chunkDataOffset + 4, true);
      bitsPerSample = dataView.getUint16(chunkDataOffset + 14, true);
    } else if (chunkId === 0x64617461) { // 'data'
      dataOffset = chunkDataOffset;
      dataLength = Math.min(chunkSize, len - dataOffset);
      break;
    }

    // Chunks are 2-byte aligned in RIFF
    offset += 8 + chunkSize + (chunkSize % 2);
  }

  // Fallback to standard decoder if required chunks missing or format unsupported
  if (!dataOffset || !sampleRate || !numChannels) return null;
  // Supported: 1 (Linear PCM) or 3 (IEEE Float)
  if (audioFormat !== 1 && audioFormat !== 3) return null;
  // Only mono and stereo are supported by this fast path
  if (numChannels !== 1 && numChannels !== 2) return null;

  const bytesPerSample = bitsPerSample / 8;
  const blockAlign = numChannels * bytesPerSample;
  const numFrames = Math.floor(dataLength / blockAlign);

  if (numFrames <= 0) return null;

  // -------------------------------------------------------------
  // Decode Samples Directly into AudioBuffer
  // -------------------------------------------------------------

  if (numChannels === 1) {
    // MONO TRACK
    const audioBuffer = ctx.createBuffer(1, numFrames, sampleRate);
    const ch0 = audioBuffer.getChannelData(0);

    if (bitsPerSample === 16 && audioFormat === 1) {
      const src = new Int16Array(arrayBuffer, dataOffset, numFrames);
      const factor = 1.0 / 32768.0;
      for (let i = 0; i < numFrames; i++) {
        ch0[i] = src[i] * factor;
      }
    } else if (bitsPerSample === 24 && audioFormat === 1) {
      const raw = new Uint8Array(arrayBuffer, dataOffset, numFrames * 3);
      const factor = 1.0 / 8388608.0;
      let s = 0;
      for (let i = 0; i < numFrames; i++) {
        const val = raw[s] | (raw[s + 1] << 8) | (raw[s + 2] << 16);
        ch0[i] = (val > 0x7FFFFF ? val - 0x1000000 : val) * factor;
        s += 3;
      }
    } else if (bitsPerSample === 32 && audioFormat === 3) {
      // 32-bit IEEE Float
      const src = new Float32Array(arrayBuffer, dataOffset, numFrames);
      ch0.set(src);
    } else {
      return null; // Fallback to decodeAudioData
    }

    return audioBuffer;

  } else if (numChannels === 2) {
    // STEREO TRACK — Interleaved L, R
    let ch0Data, ch1Data;

    if (bitsPerSample === 16 && audioFormat === 1) {
      const src = new Int16Array(arrayBuffer, dataOffset, numFrames * 2);
      ch0Data = new Float32Array(numFrames);
      ch1Data = new Float32Array(numFrames);
      const factor = 1.0 / 32768.0;
      for (let i = 0, s = 0; i < numFrames; i++, s += 2) {
        ch0Data[i] = src[s] * factor;
        ch1Data[i] = src[s + 1] * factor;
      }
    } else if (bitsPerSample === 24 && audioFormat === 1) {
      const raw = new Uint8Array(arrayBuffer, dataOffset, numFrames * 6);
      ch0Data = new Float32Array(numFrames);
      ch1Data = new Float32Array(numFrames);
      const factor = 1.0 / 8388608.0;
      let s = 0;
      for (let i = 0; i < numFrames; i++) {
        const v0 = raw[s] | (raw[s + 1] << 8) | (raw[s + 2] << 16);
        const v1 = raw[s + 3] | (raw[s + 4] << 8) | (raw[s + 5] << 16);
        ch0Data[i] = (v0 > 0x7FFFFF ? v0 - 0x1000000 : v0) * factor;
        ch1Data[i] = (v1 > 0x7FFFFF ? v1 - 0x1000000 : v1) * factor;
        s += 6;
      }
    } else if (bitsPerSample === 32 && audioFormat === 3) {
      const src = new Float32Array(arrayBuffer, dataOffset, numFrames * 2);
      ch0Data = new Float32Array(numFrames);
      ch1Data = new Float32Array(numFrames);
      for (let i = 0, s = 0; i < numFrames; i++, s += 2) {
        ch0Data[i] = src[s];
        ch1Data[i] = src[s + 1];
      }
    } else {
      return null; // Fallback to decodeAudioData
    }

    // -----------------------------------------------------------
    // Optimization: Check if stereo is actually mono (L == R)
    // Saves 50% RAM if true
    // -----------------------------------------------------------
    let isIdentical = true;
    const step = Math.max(1, Math.floor(numFrames / 1000));
    for (let i = 0; i < numFrames; i += step) {
      if (Math.abs(ch0Data[i] - ch1Data[i]) > 0.0001) {
        isIdentical = false;
        break;
      }
    }

    if (isIdentical) {
      // Downmix to 1 channel mono!
      const audioBuffer = ctx.createBuffer(1, numFrames, sampleRate);
      audioBuffer.copyToChannel(ch0Data, 0);
      return audioBuffer;
    } else {
      // True stereo
      const audioBuffer = ctx.createBuffer(2, numFrames, sampleRate);
      audioBuffer.copyToChannel(ch0Data, 0);
      audioBuffer.copyToChannel(ch1Data, 1);
      return audioBuffer;
    }
  }

  return null;
}
