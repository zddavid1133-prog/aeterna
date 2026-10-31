/**
 * zip-loader.js — Extract audio stems from a ZIP file in the browser
 * 
 * Uses JSZip (loaded from CDN in index.html).
 * Filters for audio files only, ignores macOS resource forks and hidden files.
 */

// Supported audio extensions
const AUDIO_EXTENSIONS = ['.ogg', '.opus', '.mp3', '.wav', '.m4a', '.aac', '.webm', '.flac'];

// MIME type mapping
const MIME_MAP = {
  '.ogg': 'audio/ogg',
  '.opus': 'audio/ogg',
  '.mp3': 'audio/mpeg',
  '.wav': 'audio/wav',
  '.m4a': 'audio/mp4',
  '.aac': 'audio/aac',
  '.webm': 'audio/webm',
  '.flac': 'audio/flac'
};

/**
 * Extract audio stems from a ZIP File object
 * @param {File} zipFile - The ZIP file from an <input type="file">
 * @param {function} onProgress - Progress callback: (current, total, fileName) => void
 * @returns {Promise<Array<{name: string, blob: Blob, mimeType: string}>>}
 */
export async function extractStemsFromZip(zipFile, onProgress) {
  // JSZip is loaded as a global from CDN
  if (typeof JSZip === 'undefined') {
    throw new Error('JSZip not loaded. Check the CDN script in index.html.');
  }

  const zip = await JSZip.loadAsync(zipFile);
  
  // Filter to audio files, skip macOS __MACOSX junk and hidden files
  const audioEntries = [];
  zip.forEach((relativePath, zipEntry) => {
    if (zipEntry.dir) return;
    if (relativePath.startsWith('__MACOSX')) return;
    if (relativePath.startsWith('.')) return;

    const fileName = relativePath.split('/').pop();
    if (fileName.startsWith('.')) return;

    const ext = '.' + fileName.split('.').pop().toLowerCase();
    if (AUDIO_EXTENSIONS.includes(ext)) {
      audioEntries.push({ relativePath, zipEntry, ext, fileName });
    }
  });

  if (audioEntries.length === 0) {
    throw new Error('No se encontraron archivos de audio en el ZIP. Formatos soportados: ' + AUDIO_EXTENSIONS.join(', '));
  }

  // Sort alphabetically for consistent ordering
  audioEntries.sort((a, b) => a.fileName.localeCompare(b.fileName));

  // Extract each stem as a Blob
  const stems = [];
  for (let i = 0; i < audioEntries.length; i++) {
    const entry = audioEntries[i];
    
    if (onProgress) {
      onProgress(i + 1, audioEntries.length, entry.fileName);
    }

    const blob = await entry.zipEntry.async('blob');
    const mimeType = MIME_MAP[entry.ext] || 'audio/mpeg';

    // Clean up the display name: remove extension, replace underscores/dashes
    const displayName = entry.fileName
      .replace(/\.[^.]+$/, '')  // remove extension
      .replace(/[_-]+/g, ' ')  // underscores/dashes to spaces
      .replace(/^\d+\s*/, '')  // remove leading track numbers
      .trim() || entry.fileName;

    stems.push({
      name: displayName,
      blob: new Blob([blob], { type: mimeType }),
      mimeType: mimeType
    });
  }

  return stems;
}

/**
 * Extract stems from individual audio files (not ZIP)
 * @param {FileList} files - Files from an <input type="file" multiple>
 * @returns {Array<{name: string, blob: Blob, mimeType: string}>}
 */
export function extractStemsFromFiles(files) {
  const stems = [];

  for (const file of files) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!AUDIO_EXTENSIONS.includes(ext)) continue;

    const displayName = file.name
      .replace(/\.[^.]+$/, '')
      .replace(/[_-]+/g, ' ')
      .replace(/^\d+\s*/, '')
      .trim() || file.name;

    stems.push({
      name: displayName,
      blob: file,
      mimeType: MIME_MAP[ext] || file.type || 'audio/mpeg'
    });
  }

  stems.sort((a, b) => a.name.localeCompare(b.name));
  return stems;
}
