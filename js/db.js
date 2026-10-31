/**
 * db.js — IndexedDB persistence layer for Aeterna
 * 
 * Stores original compressed audio blobs (WAV/MP3) in IndexedDB.
 * Storing raw PCM in IndexedDB was causing memory blowup and crashes on mobile.
 * 
 * Schema:
 *   songs store: { id, name, stemCount, createdAt }
 *   stems store: { id, songId, name, blob, mimeType }
 */

const DB_NAME = 'AeternaDB';
const DB_VERSION = 3;

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

      // Stems store — audio blobs
      if (!db.objectStoreNames.contains('stems')) {
        const stemStore = db.createObjectStore('stems', { keyPath: 'id', autoIncrement: true });
        stemStore.createIndex('bySongId', 'songId', { unique: false });
      }

      // Purge old pcm_cache store if it exists from v2 (it crashed mobile memory)
      if (db.objectStoreNames.contains('pcm_cache')) {
        try {
          db.deleteObjectStore('pcm_cache');
        } catch (e) {
          console.warn('Could not delete pcm_cache store:', e);
        }
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
 * Get all stems for a song (audio blobs)
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
 * Delete a song and all its stems
 * @param {string} songId
 */
export async function deleteSong(songId) {
  const db = await openDB();

  // Delete stems
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
