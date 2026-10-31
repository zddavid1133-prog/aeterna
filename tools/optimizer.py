#!/usr/bin/env python3
"""
Aeterna Multitrack Optimizer + Gemini AI Renamer (Batch Mode)
Automatically scans 'multitracks_rar/' for RAR, ZIP, or stem folders,
renames stems to English uppercase conventions using Gemini AI,
converts audio to 16-bit 44.1kHz Mono WAV, and packs into 'multitracks_optimizados/'.
"""

import os
import sys
import shutil
import zipfile
import subprocess
import threading
import time
import json
import re
import urllib.request
import urllib.error
from pathlib import Path

# Configure utf-8 console output for Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAR_DIR = PROJECT_ROOT / 'multitracks_rar'
OUTPUT_DIR = PROJECT_ROOT / 'multitracks_optimizados'
KEY_FILE = Path(__file__).parent / 'gemini_key.txt'

AUDIO_EXTS = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aif', '.aiff'}
ARCHIVE_EXTS = {'.rar', '.cbr', '.zip'}

CANDIDATE_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.8-flash"
]

PROMPT_TEMPLATE = """You are an expert live worship and band audio engineer (Loop Community Prime / Multitracks.com standard).
Analyze the following multitrack stem audio filenames and map each one to standard English UPPERCASE names:
- DRUMS (Acoustic kit, drums live, kick, snare, cymbals, etc.)
- BASS (Electric bass, synth bass, sub bass)
- PIANO (Acoustic grand piano, upright)
- KEYS_1, KEYS_2, KEYS_3 (Keyboards, synths, rhodes, organ, strings)
- AG, AG_1, AG_2 (Acoustic guitar)
- EG_1, EG_2, EG_3 (Electric guitars, leads, rhythm, crunch)
- CONGA (Congas, tumbadoras)
- TIMBAL (Timbales)
- BGVS, BGVS_1, BGVS_2 (Backing vocals, coros, harmonies)
- LEAD_VOX (Lead vocal, main singer)
- CLICK (Metronome, click track)
- GUIDE (Vocal cues, director cues)
- PAD (Ambient pads, drones)
- LOOP (Rhythm loop, shaker, tambourine)

Rules:
1. All names MUST be in UPPERCASE English.
2. If multiple stems belong to the same category, number them (e.g. EG_1, EG_2).
3. Preserve the .wav extension.
4. Return ONLY a valid JSON object mapping original filename to standardized filename.

Stems:
{stem_list}
"""

def get_default_api_key():
    """Reads API key from local gemini_key.txt or GEMINI_API_KEY environment variable."""
    if KEY_FILE.exists():
        try:
            return KEY_FILE.read_text(encoding='utf-8').strip()
        except Exception:
            pass
    return os.environ.get('GEMINI_API_KEY', '').strip()

def save_api_key(key):
    """Saves API key to local gemini_key.txt so it persists across runs."""
    try:
        KEY_FILE.write_text(key.strip(), encoding='utf-8')
    except Exception:
        pass

def check_ffmpeg():
    cmd = shutil.which('ffmpeg') or r'C:\ffmpeg\bin\ffmpeg.exe'
    if os.path.exists(cmd) or shutil.which('ffmpeg'):
        return cmd if os.path.exists(cmd) else 'ffmpeg'
    return None

def find_unrar():
    candidates = [
        r'C:\Program Files\WinRAR\UnRAR.exe',
        r'C:\Program Files\WinRAR\WinRAR.exe',
        r'C:\Program Files (x86)\WinRAR\UnRAR.exe',
        shutil.which('unrar'),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None

def sanitize_filename(name):
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    return clean.strip()

def rule_based_rename(name):
    """Fallback rename using pattern matching if AI is unavailable"""
    base = name.lower()
    if re.search(r'click|metr[oó]nomo|claqueta', base): return "CLICK.wav"
    if re.search(r'gu[ií]a|cue|director|voice.*guide', base): return "GUIDE.wav"
    if re.search(r'bat[eé]r|drum|baca', base): return "DRUMS.wav"
    if re.search(r'bajo|bass', base): return "BASS.wav"
    if re.search(r'piano|grand.*piano', base): return "PIANO.wav"
    if re.search(r'ac[uú]st|acoustic', base): return "AG.wav"
    if re.search(r'el[eé]ctr|electric|gtr|guitar', base): return "EG.wav"
    if re.search(r'conga|tumbadora', base): return "CONGA.wav"
    if re.search(r'timbal', base): return "TIMBAL.wav"
    if re.search(r'coro|bgv|back.*vox', base): return "BGVS.wav"
    if re.search(r'lead|voz.*prin', base): return "LEAD_VOX.wav"
    if re.search(r'pad|atmo', base): return "PAD.wav"
    if re.search(r'loop|shaker|tambor', base): return "LOOP.wav"
    if re.search(r'tecl|key|synth|rhodes|organ|string', base): return "KEYS.wav"
    
    clean = Path(name).stem.upper()
    clean = re.sub(r'^\d+[\s_-]*', '', clean)
    return f"{clean or 'TRACK'}.wav"

def get_standardized_names_gemini(stem_names, api_key=None, log_cb=print):
    """Renames stems via Gemini API with multi-model fallback and local rule safety net."""
    if api_key is None:
        api_key = get_default_api_key()
    if not api_key:
        log_cb("⚠️ No se proporcionó API Key. Usando renombrado por reglas locales.")
        return {name: rule_based_rename(name) for name in stem_names}

    prompt = PROMPT_TEMPLATE.format(stem_list=json.dumps(stem_names, indent=2))
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
    data_bytes = json.dumps(payload).encode("utf-8")

    for model in CANDIDATE_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        log_cb(f"🤖 [Gemini AI] Consultando modelo '{model}'...")
        try:
            req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
                mapping = json.loads(text)
                log_cb(f"✅ [Gemini AI] Éxito con {model} ({len(mapping)} pistas estandarizadas).")
                
                clean_map = {}
                for k, v in mapping.items():
                    target = str(v).strip().upper()
                    if not target.endswith('.WAV'):
                        target += '.WAV'
                    clean_map[k] = sanitize_filename(target)
                return clean_map

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 503 or "high demand" in err_body:
                log_cb(f"  ⚠️ Modelo '{model}' con alta demanda (503). Probando fallback siguiente...")
            elif e.code == 429:
                log_cb(f"  ⚠️ Modelo '{model}' alcanzó límite de cuota (429). Probando fallback...")
            else:
                log_cb(f"  ⚠️ Error en '{model}' (HTTP {e.code}). Probando siguiente...")
        except Exception as e:
            log_cb(f"  ⚠️ Error de red con '{model}': {e}. Probando fallback...")

    log_cb("⚠️ Modelos de Gemini ocupados o sin conexión. Aplicando reglas de respaldo...")
    return {name: rule_based_rename(name) for name in stem_names}

def ensure_unique_names(mapping):
    """Ensures that no two original files share the exact same target filename."""
    used_names = {}
    final_mapping = {}
    for orig, target in mapping.items():
        base = Path(target).stem
        if base not in used_names:
            used_names[base] = 1
            final_mapping[orig] = f"{base}.wav"
        else:
            used_names[base] += 1
            final_mapping[orig] = f"{base}_{used_names[base]}.wav"
    return final_mapping

def optimize_track(ffmpeg_bin, input_path, output_path):
    """Convert any audio file to 16-bit 44.1kHz Mono WAV"""
    cmd = [
        ffmpeg_bin,
        '-y',
        '-v', 'error',
        '-i', str(input_path),
        '-ac', '1',          # Mono
        '-ar', '44100',      # 44.1kHz
        '-c:a', 'pcm_s16le', # 16-bit PCM
        str(output_path)
    ]
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    subprocess.run(cmd, check=True, startupinfo=startupinfo)

def scan_incoming_multitracks():
    """Scans the multitracks_rar folder for files/folders to optimize."""
    RAR_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    items = []
    for p in sorted(RAR_DIR.iterdir()):
        if p.name.startswith('.'):
            continue
        is_arc = p.is_file() and p.suffix.lower() in ARCHIVE_EXTS
        is_subfolder = p.is_dir()
        if is_arc or is_subfolder:
            song_name = p.stem.replace('_Aeterna_Mono', '').replace('_mono', '').strip()
            dest_zip = OUTPUT_DIR / f"{song_name}_Aeterna_Mono.zip"
            already_done = dest_zip.exists()
            size_mb = p.stat().st_size / (1024*1024) if p.is_file() else sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) / (1024*1024)
            items.append({
                'path': p,
                'name': p.name,
                'song_name': song_name,
                'dest_zip': dest_zip,
                'already_done': already_done,
                'size_mb': size_mb
            })
    return items

def process_single_song(target_path, ffmpeg_bin, use_gemini=True, api_key=None,
                        track_progress_cb=None, log_cb=print):
    """Extracts, standardizes names, converts to Mono WAV 16-bit, and packs a single song."""
    target = Path(target_path)
    is_zip = target.is_file() and target.suffix.lower() == '.zip'
    is_rar = target.is_file() and target.suffix.lower() in ('.rar', '.cbr')
    is_folder = target.is_dir()

    song_name = target.stem.replace('_Aeterna_Mono', '').replace('_mono', '').strip()
    work_dir = target.parent / f"temp_{song_name}"
    out_dir = target.parent / f"optimized_{song_name}"
    
    # Save into multitracks_optimizados/ if available, otherwise target's parent
    if OUTPUT_DIR.exists():
        final_zip = OUTPUT_DIR / f"{song_name}_Aeterna_Mono.zip"
    else:
        final_zip = target.parent / f"{song_name}_Aeterna_Mono.zip"

    if work_dir.exists(): shutil.rmtree(work_dir, ignore_errors=True)
    if out_dir.exists(): shutil.rmtree(out_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    log_cb("-" * 55)
    log_cb(f"🎵 Procesando: {song_name}")

    # 1. Extraction
    source_files = []
    if is_zip:
        log_cb("  📦 Descomprimiendo .ZIP...")
        with zipfile.ZipFile(target, 'r') as z:
            z.extractall(work_dir)
        source_dir = work_dir
    elif is_rar:
        log_cb("  📦 Descomprimiendo .RAR...")
        unrar_bin = find_unrar()
        if not unrar_bin:
            raise RuntimeError("Se requiere WinRAR o UnRAR instalado para descomprimir archivos .RAR.")
        dest_str = str(work_dir)
        if not dest_str.endswith(os.sep): dest_str += os.sep
        cmd = [unrar_bin, 'x', '-y', '-inul', str(target), dest_str]
        subprocess.run(cmd, check=True)
        source_dir = work_dir
    elif is_folder:
        source_dir = target
    else:
        raise ValueError(f"Formato no soportado: {target.name}")

    # 2. Find audio files
    for root, _, files in os.walk(source_dir):
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in AUDIO_EXTS and not f.startswith('.'):
                source_files.append(p)

    if not source_files:
        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)
        raise RuntimeError("No se encontraron pistas de audio válidas.")

    orig_bytes = sum(f.stat().st_size for f in source_files)
    log_cb(f"  🔍 Encontradas {len(source_files)} pistas ({orig_bytes / (1024*1024):.1f} MB)")

    # 3. AI Renaming
    raw_names = [f.name for f in source_files]
    if use_gemini:
        mapping = get_standardized_names_gemini(raw_names, api_key=api_key, log_cb=log_cb)
    else:
        mapping = {name: rule_based_rename(name) for name in raw_names}
    mapping = ensure_unique_names(mapping)

    # 4. Conversion to Mono 16-bit 44.1kHz
    converted_files = []
    for i, file_path in enumerate(source_files, 1):
        target_name = mapping.get(file_path.name, f"{file_path.stem.upper()}.wav")
        dest_wav = out_dir / target_name

        if track_progress_cb:
            track_progress_cb(i, len(source_files), file_path.name, dest_wav.name)

        try:
            optimize_track(ffmpeg_bin, file_path, dest_wav)
            converted_files.append(dest_wav)
        except Exception as e:
            log_cb(f"    ⚠️ Error en {file_path.name}: {e}")

    # 5. Pack ZIP
    log_cb(f"  📦 Empaquetando en {final_zip.name}...")
    with zipfile.ZipFile(final_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for f in converted_files:
            zf.write(f, arcname=f.name)

    final_bytes = final_zip.stat().st_size
    savings = (1.0 - (final_bytes / orig_bytes)) * 100 if orig_bytes > 0 else 0

    shutil.rmtree(work_dir, ignore_errors=True)
    shutil.rmtree(out_dir, ignore_errors=True)

    log_cb(f"  ✅ {song_name} listo: {orig_bytes/(1024*1024):.1f}MB -> {final_bytes/(1024*1024):.1f}MB ({savings:.0f}% ahorro)")
    return final_zip, savings

# ==============================================================================
# GUI IMPLEMENTATION
# ==============================================================================

def launch_gui(single_target=None):
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print("Tkinter no está disponible. Ejecutando en modo CLI.")
        return False

    root = tk.Tk()
    root.title("Aeterna Multitrack Optimizer ⚡")
    root.geometry("860x700")
    root.minsize(780, 600)
    root.configure(bg="#0f172a")

    # Colors
    BG = "#0f172a"
    CARD_BG = "#1e293b"
    TEXT_MAIN = "#f8fafc"
    TEXT_MUTED = "#94a3b8"
    ACCENT = "#38bdf8"
    GREEN = "#22c55e"
    YELLOW = "#f59e0b"

    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure("TProgressbar", thickness=16, troughcolor="#334155", background=ACCENT)
    style.configure("Treeview", 
                    background=CARD_BG, 
                    foreground=TEXT_MAIN, 
                    fieldbackground=CARD_BG, 
                    rowheight=26,
                    font=("Segoe UI", 9))
    style.configure("Treeview.Heading", 
                    background="#334155", 
                    foreground=TEXT_MAIN, 
                    font=("Segoe UI", 9, "bold"))
    style.map("Treeview", background=[('selected', '#0369a1')])

    use_gemini_var = tk.BooleanVar(value=True)
    api_key_var = tk.StringVar(value=get_default_api_key())
    status_var = tk.StringVar(value="Listo")
    progress_val = tk.DoubleVar(value=0.0)
    is_processing = [False]

    # --- HEADER ---
    header = tk.Frame(root, bg=BG)
    header.pack(fill="x", padx=20, pady=(15, 8))

    tk.Label(header, text="⚡ AETERNA MULTITRACK OPTIMIZER", 
             font=("Segoe UI", 16, "bold"), fg=ACCENT, bg=BG).pack(anchor="w")
    tk.Label(header, 
             text=f"Carpeta de entrada: multitracks_rar/  ➜  Carpeta de salida: multitracks_optimizados/", 
             font=("Segoe UI", 9), fg=TEXT_MUTED, bg=BG).pack(anchor="w")

    # --- TOP CONTROL BAR ---
    top_bar = tk.Frame(root, bg=CARD_BG, padx=12, pady=10)
    top_bar.pack(fill="x", padx=20, pady=5)

    def open_rar_folder():
        RAR_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(f'explorer "{RAR_DIR}"', shell=True)

    def open_opt_folder():
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(f'explorer "{OUTPUT_DIR}"', shell=True)

    btn_open_rar = tk.Button(top_bar, text="📂 Abrir multitracks_rar", font=("Segoe UI", 9, "bold"), 
                             bg="#334155", fg=TEXT_MAIN, bd=0, padx=10, pady=5, cursor="hand2", command=open_rar_folder)
    btn_open_rar.pack(side="left", padx=(0, 6))

    btn_open_opt = tk.Button(top_bar, text="📁 Abrir multitracks_optimizados", font=("Segoe UI", 9, "bold"), 
                             bg="#334155", fg=TEXT_MAIN, bd=0, padx=10, pady=5, cursor="hand2", command=open_opt_folder)
    btn_open_opt.pack(side="left", padx=6)

    def reload_files():
        populate_queue()

    btn_refresh = tk.Button(top_bar, text="🔄 Recargar", font=("Segoe UI", 9), 
                            bg="#334155", fg=TEXT_MAIN, bd=0, padx=10, pady=5, cursor="hand2", command=reload_files)
    btn_refresh.pack(side="left", padx=6)

    ai_chk = tk.Checkbutton(top_bar, text="Renombrar stems con Gemini AI (Inglés Mayúsculas)",
                            variable=use_gemini_var, font=("Segoe UI", 9), 
                            fg=TEXT_MAIN, bg=CARD_BG, selectcolor="#0f172a", activebackground=CARD_BG, activeforeground=TEXT_MAIN)
    ai_chk.pack(side="right")

    # --- QUEUE CARD ---
    main_card = tk.Frame(root, bg=CARD_BG, padx=12, pady=10)
    main_card.pack(fill="both", expand=True, padx=20, pady=8)

    queue_title_frame = tk.Frame(main_card, bg=CARD_BG)
    queue_title_frame.pack(fill="x", pady=(0, 6))

    queue_count_lbl = tk.Label(queue_title_frame, text="Cola de Multitracks:", font=("Segoe UI", 10, "bold"), fg=TEXT_MAIN, bg=CARD_BG)
    queue_count_lbl.pack(side="left")

    status_lbl = tk.Label(queue_title_frame, textvariable=status_var, font=("Segoe UI", 9), fg=ACCENT, bg=CARD_BG)
    status_lbl.pack(side="right")

    pbar = ttk.Progressbar(main_card, variable=progress_val, maximum=100, style="TProgressbar")
    pbar.pack(fill="x", pady=(0, 8))

    # Split view: Song Queue & Live Log
    split_frame = tk.Frame(main_card, bg=CARD_BG)
    split_frame.pack(fill="both", expand=True)

    # Queue Treeview
    tree_frame = tk.Frame(split_frame, bg=CARD_BG)
    tree_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

    columns = ("name", "size", "status")
    tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=10)
    tree.heading("name", text="Archivo / Carpeta")
    tree.heading("size", text="Tamaño")
    tree.heading("status", text="Estado")
    tree.column("name", width=200, anchor="w")
    tree.column("size", width=70, anchor="center")
    tree.column("status", width=130, anchor="w")

    tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=tree_scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    tree_scroll.pack(side="right", fill="y")

    # Log text
    log_frame = tk.Frame(split_frame, bg=CARD_BG)
    log_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))

    tk.Label(log_frame, text="Consola de Eventos:", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg=CARD_BG).pack(anchor="w")

    log_text = tk.Text(log_frame, bg="#0b1120", fg="#cbd5e1", font=("Consolas", 8), bd=0, padx=6, pady=6, height=10, wrap="word")
    log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=log_text.yview)
    log_text.configure(yscrollcommand=log_scroll.set)
    log_text.pack(side="left", fill="both", expand=True)
    log_scroll.pack(side="right", fill="y")

    def gui_log(msg):
        def _append():
            log_text.insert("end", msg + "\n")
            log_text.see("end")
        root.after(0, _append)

    current_queue_items = []

    def populate_queue():
        tree.delete(*tree.get_children())
        current_queue_items.clear()

        # If a single target was provided via drag and drop
        if single_target and Path(single_target).exists():
            p = Path(single_target)
            size_mb = p.stat().st_size / (1024*1024) if p.is_file() else sum(f.stat().st_size for f in p.rglob('*')) / (1024*1024)
            current_queue_items.append({'path': p, 'name': p.name, 'size_mb': size_mb, 'already_done': False})
        else:
            current_queue_items.extend(scan_incoming_multitracks())

        pending_count = 0
        for item in current_queue_items:
            status_text = "✅ Ya optimizado" if item.get('already_done') else "⏳ Pendiente"
            if not item.get('already_done'): pending_count += 1
            tree.insert("", "end", iid=str(item['path']), values=(item['name'], f"{item['size_mb']:.1f} MB", status_text))

        queue_count_lbl.config(text=f"Cola de Multitracks ({len(current_queue_items)} encontrados, {pending_count} pendientes):")
        if len(current_queue_items) == 0:
            gui_log("💡 Carpeta 'multitracks_rar' vacía. Coloca tus archivos .rar o .zip allí para procesarlos.")

    populate_queue()

    # --- BOTTOM BAR ---
    bottom = tk.Frame(root, bg=BG)
    bottom.pack(fill="x", padx=20, pady=(0, 15))

    btn_start = tk.Button(bottom, text="⚡ OPTIMIZAR TODOS LOS RAR / ZIP", font=("Segoe UI", 11, "bold"), 
                          bg=GREEN, fg="#ffffff", activebackground="#16a34a", activeforeground="#ffffff", 
                          bd=0, padx=22, pady=9, cursor="hand2")
    btn_start.pack(side="left")

    def select_custom_file():
        f = filedialog.askopenfilename(title="Seleccionar RAR o ZIP suelto", 
                                      filetypes=[("Archivos comprimidos", "*.rar *.zip"), ("Todos", "*.*")])
        if f:
            p = Path(f)
            size_mb = p.stat().st_size / (1024*1024)
            current_queue_items.append({'path': p, 'name': p.name, 'size_mb': size_mb, 'already_done': False})
            tree.insert("", "end", iid=str(p), values=(p.name, f"{size_mb:.1f} MB", "⏳ Pendiente"))

    btn_custom = tk.Button(bottom, text="➕ Agregar archivo suelto", font=("Segoe UI", 9, "bold"), 
                           bg="#334155", fg=TEXT_MAIN, bd=0, padx=12, pady=9, cursor="hand2", command=select_custom_file)
    btn_custom.pack(side="left", padx=10)

    def run_batch():
        if is_processing[0]: return
        ffmpeg = check_ffmpeg()
        if not ffmpeg:
            messagebox.showerror("Error", "No se encontró FFmpeg en el sistema (C:\\ffmpeg\\bin\\ffmpeg.exe).")
            return

        to_process = [it for it in current_queue_items if not it.get('already_done')]
        if not to_process:
            if current_queue_items:
                if messagebox.askyesno("Ya optimizados", "Todos los archivos ya fueron optimizados previamente. ¿Deseas volver a procesarlos todos?"):
                    to_process = current_queue_items
                else:
                    return
            else:
                messagebox.showinfo("Aeterna Optimizer", "No hay archivos en la carpeta 'multitracks_rar'.\nColoca allí tus archivos .rar o .zip y vuelve a pulsar el botón.")
                return

        is_processing[0] = True
        btn_start.config(state="disabled", bg="#64748b", text="⏳ Procesando lote...")
        progress_val.set(0)

        def worker():
            total_songs = len(to_process)
            gui_log("=" * 55)
            gui_log(f"🚀 INICIANDO OPTIMIZACIÓN POR LOTE ({total_songs} CANCIONES)")
            gui_log("=" * 55)

            for s_idx, song in enumerate(to_process, 1):
                p = song['path']
                pct_song = int(((s_idx - 1) / total_songs) * 100)
                root.after(0, lambda v=pct_song, msg=f"Canción {s_idx}/{total_songs}: {p.name}": (progress_val.set(v), status_var.set(msg)))
                root.after(0, lambda item_id=str(p): tree.item(item_id, values=(song['name'], f"{song['size_mb']:.1f} MB", "⚙️ Procesando...")))

                def on_track(cur, tot, orig, target):
                    root.after(0, lambda: status_var.set(f"[{s_idx}/{total_songs}] Pista {cur}/{tot}: {target}"))

                try:
                    final_zip, savings = process_single_song(
                        p, ffmpeg, 
                        use_gemini=use_gemini_var.get(), 
                        api_key=api_key_var.get(),
                        track_progress_cb=on_track, 
                        log_cb=gui_log
                    )
                    root.after(0, lambda item_id=str(p), sav=savings: tree.item(item_id, values=(song['name'], f"{song['size_mb']:.1f} MB", f"✅ Listo ({sav:.0f}% ahorro)")))
                except Exception as e:
                    gui_log(f"❌ Error en {p.name}: {e}")
                    root.after(0, lambda item_id=str(p): tree.item(item_id, values=(song['name'], f"{song['size_mb']:.1f} MB", "❌ Error")))

            # Finish batch
            root.after(0, lambda: progress_val.set(100))
            root.after(0, lambda: status_var.set("✅ ¡Lote completado con éxito!"))
            gui_log("\n" + "=" * 55)
            gui_log("🎉 ¡TODOS LOS MULTITRACKS FUERON OPTIMIZADOS!")
            gui_log(f"📁 Encuéntralos en: {OUTPUT_DIR}")
            gui_log("=" * 55)

            def on_finish():
                is_processing[0] = False
                btn_start.config(state="normal", bg=GREEN, text="⚡ OPTIMIZAR TODOS LOS RAR / ZIP")
                if messagebox.askyesno("Completado", "¡Optimización por lote completada!\n\n¿Deseas abrir la carpeta con los archivos listos para el celular?"):
                    open_opt_folder()

            root.after(0, on_finish)

        threading.Thread(target=worker, daemon=True).start()

    btn_start.config(command=run_batch)
    root.mainloop()
    return True

# ==============================================================================
# CLI HANDLER
# ==============================================================================

if __name__ == '__main__':
    args = sys.argv[1:]
    target_arg = None
    force_cli = False

    for a in args:
        if a == '--cli':
            force_cli = True
        elif not target_arg:
            target_arg = a

    if not force_cli:
        try:
            launch_gui(target_arg)
            sys.exit(0)
        except Exception as e:
            print(f"No se pudo iniciar la interfaz ({e}). Usando modo consola...")

    # CLI mode
    ffmpeg = check_ffmpeg()
    if not ffmpeg:
        print("❌ Error: No se encontró FFmpeg.")
        sys.exit(1)

    targets = [Path(target_arg)] if target_arg else [it['path'] for it in scan_incoming_multitracks() if not it['already_done']]
    if not targets:
        print("No hay archivos para optimizar en multitracks_rar/.")
        sys.exit(0)

    print(f"Optimizando {len(targets)} canciones en modo CLI...")
    for t in targets:
        try:
            process_single_song(t, ffmpeg)
        except Exception as e:
            print(f"Error procesando {t}: {e}")
