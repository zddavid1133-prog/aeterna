const fs = require('fs');
const path = require('path');

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

// Clean and recreate www/
fs.rmSync('www', { recursive: true, force: true });
fs.mkdirSync('www', { recursive: true });

fs.copyFileSync('index.html', path.join('www', 'index.html'));
fs.copyFileSync('manifest.json', path.join('www', 'manifest.json'));
if (fs.existsSync('sw.js')) fs.copyFileSync('sw.js', path.join('www', 'sw.js'));
copyDir('css', path.join('www', 'css'));
copyDir('js', path.join('www', 'js'));

console.log('✓ Web assets copied to www/');
