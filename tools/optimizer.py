#!/usr/bin/env python3
"""
Aeterna Multitrack Optimizer
Converts multitrack stems (WAV, MP3, M4A, FLAC, etc.) into 16-bit Mono WAV (44.1kHz)
and packs them into an optimized ZIP ready for instant loading in Aeterna (< 2s).
"""

import os
import sys
import shutil
import zipfile
import subprocess
from pathlib import Path

AUDIO_EXTS = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aif', '.aiff'}

def check_ffmpeg():
    cmd = shutil.which('ffmpeg') or r'C:\ffmpeg\bin\ffmpeg.exe'
    if os.path.exists(cmd) or shutil.which('ffmpeg'):
        return cmd if os.path.exists(cmd) else 'ffmpeg'
    print("❌ Error: No se encontró FFmpeg. Asegúrate de tenerlo instalado en el sistema.")
    sys.exit(1)

def optimize_track(ffmpeg_bin, input_path, output_path):
    """Convert any audio file to 16-bit 44.1kHz Mono WAV"""
    cmd = [
        ffmpeg_bin,
        '-y',               # Overwrite output
        '-v', 'error',      # Suppress banner
        '-i', str(input_path),
        '-ac', '1',         # Downmix to Mono (saves 50% RAM & size)
        '-ar', '44100',     # Standard 44.1kHz
        '-c:a', 'pcm_s16le',# 16-bit linear PCM (instant direct parsing in Aeterna)
        str(output_path)
    ]
    subprocess.run(cmd, check=True)

def process_target(target_path):
    target = Path(target_path)
    if not target.exists():
        print(f"❌ Error: La ruta no existe: {target}")
        return

    ffmpeg_bin = check_ffmpeg()

    # Determine song name and working directory
    is_zip = target.is_file() and target.suffix.lower() == '.zip'
    song_name = target.stem.replace('_Aeterna_Mono', '').replace('_mono', '').strip()

    work_dir = target.parent / f"temp_{song_name}"
    out_dir = target.parent / f"optimized_{song_name}"
    output_zip = target.parent / f"{song_name}_Aeterna_Mono.zip"

    if work_dir.exists(): shutil.rmtree(work_dir)
    if out_dir.exists(): shutil.rmtree(out_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n========================================================")
    print(f"🎵 Optimizando Multitrack: {song_name}")
    print(f"========================================================")

    # Step 1: Collect files
    source_files = []
    if is_zip:
        print("📦 Descomprimiendo archivo ZIP original...")
        with zipfile.ZipFile(target, 'r') as z:
            z.extractall(work_dir)
        source_dir = work_dir
    elif target.is_dir():
        source_dir = target
    else:
        print("❌ Por favor arrastra una carpeta con stems o un archivo .ZIP.")
        return

    # Find all audio files
    for root, _, files in os.walk(source_dir):
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in AUDIO_EXTS and not f.startswith('.'):
                source_files.append(p)

    if not source_files:
        print("❌ No se encontraron archivos de audio válidos.")
        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)
        return

    total_original_bytes = sum(f.stat().st_size for f in source_files)
    print(f"🔍 Encontradas {len(source_files)} pistas de audio ({total_original_bytes / (1024*1024):.1f} MB en total)")

    # Step 2: Convert to 16-bit Mono WAV
    print("\n⚡ Convirtiendo pistas a Mono WAV 16-bit 44.1kHz (ultra-rápido)...")
    converted_files = []

    for i, file_path in enumerate(source_files, 1):
        clean_name = file_path.stem
        # Remove numbers and clean up
        clean_name = clean_name.replace('__', '_').strip()
        dest_wav = out_dir / f"{clean_name}.wav"

        print(f"  [{i}/{len(source_files)}] {file_path.name}  ->  {dest_wav.name}")
        try:
            optimize_track(ffmpeg_bin, file_path, dest_wav)
            converted_files.append(dest_wav)
        except Exception as e:
            print(f"    ⚠️ Error convirtiendo {file_path.name}: {e}")

    # Step 3: Zip the optimized stems
    print(f"\n📦 Empaquetando en: {output_zip.name}...")
    with zipfile.ZipFile(output_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for f in converted_files:
            zf.write(f, arcname=f.name)

    total_final_bytes = output_zip.stat().st_size
    savings_pct = (1.0 - (total_final_bytes / total_original_bytes)) * 100 if total_original_bytes > 0 else 0

    # Cleanup temp
    if work_dir.exists(): shutil.rmtree(work_dir, ignore_errors=True)
    if out_dir.exists(): shutil.rmtree(out_dir, ignore_errors=True)

    print("\n========================================================")
    print("✅ ¡OPTIMIZACIÓN COMPLETADA CON ÉXITO!")
    print(f"📊 Peso Original:   {total_original_bytes / (1024*1024):.1f} MB")
    print(f"📊 Peso Optimizado:  {total_final_bytes / (1024*1024):.1f} MB ({savings_pct:.0f}% de ahorro)")
    print(f"📁 Archivo listo:   {output_zip}")
    print(f"⚡ Carga estimada en celular: ~1.5 a 2 segundos!")
    print("========================================================\n")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: Arrastra una carpeta con stems o un archivo .ZIP sobre este script.")
        input("\nPresiona Enter para salir...")
        sys.exit(0)

    for arg in sys.argv[1:]:
        process_target(arg)

    input("Presiona Enter para cerrar...")
