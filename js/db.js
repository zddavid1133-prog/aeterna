/**
 * db.js — IndexedDB persistence layer for Aeterna
 * 
 * Stores compressed audio blobs AND decoded PCM data in IndexedDB.
 * 
 * Schema:
 *   songs store:     { id, name, stemCount, createdAt }
 *   stems store:     { id, songId, name, blob, mimeType }          ← compressed originals
 *   pcm_cache store: { id, songId, name, sampleRate,               ← decoded PCM (instant load)
 *                      numberOfChannels, length, channels: [ArrayBuffer...] }
 */

const DB_NAME = 'AeternaDB';
const DB_VERSION = 2;

let _db = null;

function openDB() {
  if (_db) return Promise.resolve(_db);

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onerror = () => reject(request.error);
    
    request.onupgradeneeded = (event) => {
      const db = event.target.result;

      // Songs store — metadata only
      if (!db.objectStoreNames.contains('songs')) {
        db.createObjectStore('songs', { keyPath: 'id' });
      }

      // Stems store — compressed audio blobs
      if (!db.objectStoreNames.contains('stems')) {
        const stemStore = db.createObjectStore('stems', { keyPath: 'id', autoIncrement: true });
        stemStore.createIndex('bySongId', 'songId', { unique: false });
      }

      // PCM cache store — decoded raw audio data (NEW in v2)
      if (!db.objectStoreNames.contains('pcm_cache')) {
        const pcmStore = db.createObjectStore('pcm_cache', { keyPath: 'id', autoIncrement: true });
        pcmStore.createIndex('bySongId', 'songId', { unique: false });
      }
    };

    request.onsuccess = () => {
      _db = request.result;
      resolve(_db);
    };
  });
}

/**
 * Save a song with its stems to IndexedDB
 * @param {string} songId - Unique ID for the song
 * @param {string} songName - Display name
 * @param {Array<{name: string, blob: Blob, mimeType: string}>} stems - Audio stem blobs
 */
export async function saveSong(songId, songName, stems) {
  const db = await openDB();

  // Save song metadata
  const txSong = db.transaction('songs', 'readwrite');
  txSong.objectStore('songs').put({
    id: songId,
    name: songName,
    stemCount: stems.length,
    createdAt: Date.now()
  });
  await new Promise((resolve, reject) => {
    txSong.oncomplete = resolve;
    txSong.onerror = () => reject(txSong.error);
  });

  // Save each stem as a separate record (keeps transactions small)
  for (const stem of stems) {
    const txStem = db.transaction('stems', 'readwrite');
    txStem.objectStore('stems').put({
      songId: songId,
      name: stem.name,
      blob: stem.blob,
      mimeType: stem.mimeType
    });
    await new Promise((resolve, reject) => {
      txStem.oncomplete = resolve;
      txStem.onerror = () => reject(txStem.error);
    });
  }
}

/**
 * Get all stems for a song (compressed blobs)
 * @param {string} songId
 * @returns {Promise<Array<{name: string, blob: Blob, mimeType: string}>>}
 */
export async function getSongStems(songId) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('stems', 'readonly');
    const index = tx.objectStore('stems').index('bySongId');
    const request = index.getAll(songId);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/**
 * Save decoded PCM data for a song's stems.
 * Each stem's AudioBuffer channels are extracted as Float32Array → ArrayBuffer
 * so they can be stored in IndexedDB and reconstructed instantly.
 * 
 * @param {string} songId
 * @param {Array<{name: string, sampleRate: number, numberOfChannels: number, length: number, channels: ArrayBuffer[]}>} pcmStems
 */
export async function savePCMCache(songId, pcmStems) {
  const db = await openDB();

  for (const stem of pcmStems) {
    const tx = db.transaction('pcm_cache', 'readwrite');
    tx.objectStore('pcm_cache').put({
      songId: songId,
      name: stem.name,
      sampleRate: stem.sampleRate,
      numberOfChannels: stem.numberOfChannels,
      length: stem.length,
      channels: stem.channels  // Array of ArrayBuffer, one per channel
    });
    await new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }
}

/**
 * Get cached PCM data for a song.
 * Returns null if no cache exists (first-time load).
 * 
 * @param {string} songId
 * @returns {Promise<Array<{name, sampleRate, numberOfChannels, length, channels: ArrayBuffer[]}> | null>}
 */
export async function getPCMCache(songId) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('pcm_cache', 'readonly');
    const index = tx.objectStore('pcm_cache').index('bySongId');
    const request = index.getAll(songId);
    request.onsuccess = () => {
      const results = request.result;
      resolve(results && results.length > 0 ? results : null);
    };
    request.onerror = () => reject(request.error);
  });
}

/**
 * List all saved songs (metadata only, no blobs)
 * @returns {Promise<Array<{id: string, name: string, stemCount: number, createdAt: number}>>}
 */
export async function listSongs() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('songs', 'readonly');
    const request = tx.objectStore('songs').getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/**
 * Delete a song, all its stems, AND its PCM cache
 * @param {string} songId
 */
export async function deleteSong(songId) {
  const db = await openDB();

  // Delete compressed stems
  const txStems = db.transaction('stems', 'readwrite');
  const stemIndex = txStems.objectStore('stems').index('bySongId');
  const stemsRequest = stemIndex.getAllKeys(songId);
  
  await new Promise((resolve, reject) => {
    stemsRequest.onsuccess = () => {
      const keys = stemsRequest.result;
      keys.forEach((key) => {
        txStems.objectStore('stems').delete(key);
      });
      txStems.oncomplete = resolve;
      txStems.onerror = () => reject(txStems.error);
    };
    stemsRequest.onerror = () => reject(stemsRequest.error);
  });

  // Delete PCM cache
  const txPcm = db.transaction('pcm_cache', 'readwrite');
  const pcmIndex = txPcm.objectStore('pcm_cache').index('bySongId');
  const pcmRequest = pcmIndex.getAllKeys(songId);
  
  await new Promise((resolve, reject) => {
    pcmRequest.onsuccess = () => {
      const keys = pcmRequest.result;
      keys.forEach((key) => {
        txPcm.objectStore('pcm_cache').delete(key);
      });
      txPcm.oncomplete = resolve;
      txPcm.onerror = () => reject(txPcm.error);
    };
    pcmRequest.onerror = () => reject(pcmRequest.error);
  });

  // Delete song metadata
  const txSong = db.transaction('songs', 'readwrite');
  txSong.objectStore('songs').delete(songId);
  await new Promise((resolve, reject) => {
    txSong.oncomplete = resolve;
    txSong.onerror = () => reject(txSong.error);
  });
}

/**
 * Get estimated storage usage
 * @returns {Promise<{used: number, quota: number}>}
 */
export async function getStorageEstimate() {
  if (navigator.storage && navigator.storage.estimate) {
    const estimate = await navigator.storage.estimate();
    return { used: estimate.usage || 0, quota: estimate.quota || 0 };
  }
  return { used: 0, quota: 0 };
}
