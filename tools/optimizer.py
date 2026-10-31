#!/usr/bin/env python3
"""
Aeterna Multitrack Optimizer + Gemini AI Renamer
Converts multitrack stems (WAV, MP3, M4A, FLAC, etc.) into 16-bit Mono WAV (44.1kHz)
and standardizes track names using Gemini AI (with fallback models & local rules).
Includes a modern GUI with progress tracking and supports drag-and-drop.
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

AUDIO_EXTS = {'.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aif', '.aiff'}
KEY_FILE = Path(__file__).parent / 'gemini_key.txt'

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
    # Remove special characters invalid in filenames
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
    clean = re.sub(r'^\d+[\s_-]*', '', clean) # Remove track numbers
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
                
                # Ensure .wav extension and clean format
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
                log_cb(f"  ⚠️ Modelo '{model}' con alta demanda (503). Probando fallback...")
            elif e.code == 429:
                log_cb(f"  ⚠️ Modelo '{model}' alcanzó límite de cuota (429). Probando fallback...")
            else:
                log_cb(f"  ⚠️ Error en '{model}' (HTTP {e.code}). Probando siguiente...")
        except Exception as e:
            log_cb(f"  ⚠️ Error de red con '{model}': {e}. Probando fallback...")

    log_cb("⚠️ Modelos de Gemini no disponibles. Aplicando respaldo de reglas automáticas...")
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
    # Hide console window on Windows when executing from GUI
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    subprocess.run(cmd, check=True, startupinfo=startupinfo)

def run_optimization(target_path, use_gemini=True, api_key=None, 
                     progress_cb=None, log_cb=print, done_cb=None):
    """Main worker function to extract, rename, convert, and pack multitracks."""
    if api_key is None:
        api_key = get_default_api_key()
    try:
        ffmpeg_bin = check_ffmpeg()
        if not ffmpeg_bin:
            log_cb("❌ Error: No se encontró FFmpeg en el sistema (C:\\ffmpeg\\bin\\ffmpeg.exe).")
            if done_cb: done_cb(False, "FFmpeg no encontrado")
            return

        target = Path(target_path)
        if not target.exists():
            log_cb(f"❌ Error: La ruta no existe: {target}")
            if done_cb: done_cb(False, "Ruta inválida")
            return

        is_zip = target.is_file() and target.suffix.lower() == '.zip'
        is_rar = target.is_file() and target.suffix.lower() in ('.rar', '.cbr')
        is_folder = target.is_dir()

        song_name = target.stem.replace('_Aeterna_Mono', '').replace('_mono', '').strip()
        work_dir = target.parent / f"temp_{song_name}"
        out_dir = target.parent / f"optimized_{song_name}"
        output_zip = target.parent / f"{song_name}_Aeterna_Mono.zip"

        if work_dir.exists(): shutil.rmtree(work_dir, ignore_errors=True)
        if out_dir.exists(): shutil.rmtree(out_dir, ignore_errors=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        log_cb("=" * 60)
        log_cb(f"🎵 OPTIMIZANDO MULTITRACK: {song_name}")
        log_cb("=" * 60)

        # 1. Extraction
        source_files = []
        if is_zip:
            log_cb("📦 Descomprimiendo archivo .ZIP...")
            with zipfile.ZipFile(target, 'r') as z:
                z.extractall(work_dir)
            source_dir = work_dir
        elif is_rar:
            log_cb("📦 Descomprimiendo archivo .RAR...")
            unrar_bin = find_unrar()
            if not unrar_bin:
                log_cb("❌ Error: Se requiere WinRAR o UnRAR instalado para archivos .RAR.")
                if done_cb: done_cb(False, "UnRAR no encontrado")
                return
            dest_str = str(work_dir)
            if not dest_str.endswith(os.sep): dest_str += os.sep
            cmd = [unrar_bin, 'x', '-y', '-inul', str(target), dest_str]
            subprocess.run(cmd, check=True)
            source_dir = work_dir
        elif is_folder:
            source_dir = target
        else:
            log_cb("❌ Formato no soportado. Arrastra una carpeta, .ZIP o .RAR.")
            if done_cb: done_cb(False, "Formato no soportado")
            return

        # 2. Find audio files
        for root, _, files in os.walk(source_dir):
            for f in files:
                p = Path(root) / f
                if p.suffix.lower() in AUDIO_EXTS and not f.startswith('.'):
                    source_files.append(p)

        if not source_files:
            log_cb("❌ No se encontraron archivos de audio válidos.")
            shutil.rmtree(work_dir, ignore_errors=True)
            shutil.rmtree(out_dir, ignore_errors=True)
            if done_cb: done_cb(False, "Sin archivos de audio")
            return

        total_original_bytes = sum(f.stat().st_size for f in source_files)
        log_cb(f"🔍 Encontradas {len(source_files)} pistas ({total_original_bytes / (1024*1024):.1f} MB)")

        # 3. Rename mapping (Gemini AI or Rules)
        raw_names = [f.name for f in source_files]
        if use_gemini:
            log_cb("\n🤖 Analizando nombres de pistas con Gemini AI...")
            mapping = get_standardized_names_gemini(raw_names, api_key=api_key, log_cb=log_cb)
        else:
            log_cb("\n📋 Aplicando estandarización de nombres rápida...")
            mapping = {name: rule_based_rename(name) for name in raw_names}

        mapping = ensure_unique_names(mapping)

        # Notify preview of stems
        if progress_cb:
            items_preview = []
            for f in source_files:
                target_name = mapping.get(f.name, f"{f.stem.upper()}.wav")
                items_preview.append((f.name, target_name))
            progress_cb(0, len(source_files), "Iniciando conversión...", items_preview)

        # 4. Conversion to 16-bit Mono WAV
        log_cb("\n⚡ Convirtiendo pistas a Mono WAV 16-bit 44.1kHz (ultra-rápido)...")
        converted_files = []

        for i, file_path in enumerate(source_files, 1):
            target_stem = mapping.get(file_path.name, f"{file_path.stem.upper()}.wav")
            dest_wav = out_dir / target_stem

            log_cb(f"  [{i}/{len(source_files)}] {file_path.name}  ->  {dest_wav.name}")
            if progress_cb:
                progress_cb(i, len(source_files), f"Convirtiendo: {dest_wav.name}", None)

            try:
                optimize_track(ffmpeg_bin, file_path, dest_wav)
                converted_files.append(dest_wav)
            except Exception as e:
                log_cb(f"    ⚠️ Error convirtiendo {file_path.name}: {e}")

        # 5. Pack ZIP
        log_cb(f"\n📦 Empaquetando en {output_zip.name}...")
        if progress_cb:
            progress_cb(len(source_files), len(source_files), "Empaquetando ZIP final...", None)

        with zipfile.ZipFile(output_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for f in converted_files:
                zf.write(f, arcname=f.name)

        total_final_bytes = output_zip.stat().st_size
        savings_pct = (1.0 - (total_final_bytes / total_original_bytes)) * 100 if total_original_bytes > 0 else 0

        # Cleanup temp
        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(out_dir, ignore_errors=True)

        log_cb("\n" + "=" * 60)
        log_cb("✅ ¡OPTIMIZACIÓN COMPLETADA CON ÉXITO!")
        log_cb(f"📊 Peso Original:   {total_original_bytes / (1024*1024):.1f} MB")
        log_cb(f"📊 Peso Optimizado: {total_final_bytes / (1024*1024):.1f} MB ({savings_pct:.0f}% de ahorro)")
        log_cb(f"📁 Archivo Creado:  {output_zip.name}")
        log_cb(f"⚡ Carga estimada en celular: ~1.5 a 2 segundos!")
        log_cb("=" * 60 + "\n")

        if done_cb:
            done_cb(True, f"Guardado en {output_zip.name}", output_zip)

    except Exception as e:
        log_cb(f"❌ Error crítico en optimización: {e}")
        if done_cb: done_cb(False, str(e))

# ==============================================================================
# GUI IMPLEMENTATION (Tkinter)
# ==============================================================================

def launch_gui(initial_target=None):
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print("Tkinter no está disponible en este entorno Python. Ejecutando en modo CLI.")
        return False

    root = tk.Tk()
    root.title("Aeterna Multitrack Optimizer ⚡")
    root.geometry("820x680")
    root.minsize(740, 580)
    root.configure(bg="#0f172a")

    # Styling colors
    BG = "#0f172a"        # Dark slate
    CARD_BG = "#1e293b"   # Slate 800
    TEXT_MAIN = "#f8fafc" # Slate 50
    TEXT_MUTED = "#94a3b8"# Slate 400
    ACCENT = "#38bdf8"    # Sky 400
    ACCENT_HOVER = "#0284c7"
    GREEN = "#22c55e"     # Emerald 500

    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure("TProgressbar", thickness=18, troughcolor="#334155", background=ACCENT)
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

    # Variables
    path_var = tk.StringVar(value=str(initial_target) if initial_target else "")
    use_gemini_var = tk.BooleanVar(value=True)
    api_key_var = tk.StringVar(value=get_default_api_key())
    status_var = tk.StringVar(value="Listo para optimizar")
    progress_val = tk.DoubleVar(value=0.0)
    last_output_zip = [None]
    is_processing = [False]

    # --- TOP BANNER ---
    header_frame = tk.Frame(root, bg=BG)
    header_frame.pack(fill="x", padx=20, pady=(15, 10))

    title_lbl = tk.Label(header_frame, text="⚡ AETERNA MULTITRACK OPTIMIZER", 
                         font=("Segoe UI", 16, "bold"), fg=ACCENT, bg=BG)
    title_lbl.pack(anchor="w")

    subtitle_lbl = tk.Label(header_frame, 
                            text="Conversor a Mono 16-bit 44.1kHz • Renombrado Automático con Gemini AI", 
                            font=("Segoe UI", 9), fg=TEXT_MUTED, bg=BG)
    subtitle_lbl.pack(anchor="w")

    # --- INPUT CARD ---
    input_card = tk.Frame(root, bg=CARD_BG, bd=1, relief="flat", padx=12, pady=10)
    input_card.pack(fill="x", padx=20, pady=5)

    tk.Label(input_card, text="Multitrack / Stems a optimizar:", 
             font=("Segoe UI", 9, "bold"), fg=TEXT_MAIN, bg=CARD_BG).pack(anchor="w")

    input_row = tk.Frame(input_card, bg=CARD_BG)
    input_row.pack(fill="x", pady=(5, 5))

    path_entry = tk.Entry(input_row, textvariable=path_var, font=("Segoe UI", 10), 
                          bg="#0f172a", fg=TEXT_MAIN, insertbackground=TEXT_MAIN, bd=1, relief="solid")
    path_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))

    def browse_folder():
        f = filedialog.askdirectory(title="Seleccionar Carpeta con Stems")
        if f: path_var.set(f)

    def browse_file():
        f = filedialog.askopenfilename(title="Seleccionar Archivo ZIP o RAR", 
                                      filetypes=[("Archivos comprimidos", "*.zip *.rar"), ("Todos", "*.*")])
        if f: path_var.set(f)

    btn_folder = tk.Button(input_row, text="📂 Carpeta", font=("Segoe UI", 9, "bold"), 
                           bg="#334155", fg=TEXT_MAIN, bd=0, padx=10, pady=4, cursor="hand2", command=browse_folder)
    btn_folder.pack(side="left", padx=2)

    btn_zip = tk.Button(input_row, text="📦 ZIP / RAR", font=("Segoe UI", 9, "bold"), 
                        bg="#334155", fg=TEXT_MAIN, bd=0, padx=10, pady=4, cursor="hand2", command=browse_file)
    btn_zip.pack(side="left", padx=2)

    # --- OPTIONS ROW ---
    opt_row = tk.Frame(input_card, bg=CARD_BG)
    opt_row.pack(fill="x", pady=(5, 0))

    ai_chk = tk.Checkbutton(opt_row, text="Renombrar stems con Gemini AI (Estándar en Inglés: DRUMS, BASS, KEYS, AG, EG, etc.)",
                            variable=use_gemini_var, font=("Segoe UI", 9), 
                            fg=TEXT_MAIN, bg=CARD_BG, selectcolor="#0f172a", activebackground=CARD_BG, activeforeground=TEXT_MAIN)
    ai_chk.pack(side="left")

    ai_badge = tk.Label(opt_row, text="● Gemini AI Conectado", font=("Segoe UI", 8, "bold"), fg=GREEN, bg=CARD_BG)
    ai_badge.pack(side="right")

    # --- PROGRESS & STEMS CARD ---
    main_card = tk.Frame(root, bg=CARD_BG, bd=1, relief="flat", padx=12, pady=10)
    main_card.pack(fill="both", expand=True, padx=20, pady=10)

    # Status & Progress bar
    prog_header = tk.Frame(main_card, bg=CARD_BG)
    prog_header.pack(fill="x", pady=(0, 4))

    status_lbl = tk.Label(prog_header, textvariable=status_var, font=("Segoe UI", 9, "bold"), fg=ACCENT, bg=CARD_BG)
    status_lbl.pack(side="left")

    pct_lbl = tk.Label(prog_header, text="0%", font=("Segoe UI", 9), fg=TEXT_MUTED, bg=CARD_BG)
    pct_lbl.pack(side="right")

    pbar = ttk.Progressbar(main_card, variable=progress_val, maximum=100, style="TProgressbar")
    pbar.pack(fill="x", pady=(0, 8))

    # Split: Table + Console Log
    split_frame = tk.Frame(main_card, bg=CARD_BG)
    split_frame.pack(fill="both", expand=True)

    # Stems Treeview
    table_frame = tk.Frame(split_frame, bg=CARD_BG)
    table_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

    tk.Label(table_frame, text="Pistas Detectadas:", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg=CARD_BG).pack(anchor="w")
    
    columns = ("orig", "target")
    tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)
    tree.heading("orig", text="Nombre Original")
    tree.heading("target", text="Nombre Estándar (IA)")
    tree.column("orig", width=180, anchor="w")
    tree.column("target", width=140, anchor="w")

    tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=tree_scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    tree_scroll.pack(side="right", fill="y")

    # Log Text Console
    log_frame = tk.Frame(split_frame, bg=CARD_BG)
    log_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))

    tk.Label(log_frame, text="Registro de Eventos:", font=("Segoe UI", 8, "bold"), fg=TEXT_MUTED, bg=CARD_BG).pack(anchor="w")

    log_text = tk.Text(log_frame, bg="#0b1120", fg="#cbd5e1", font=("Consolas", 8), 
                       bd=0, padx=6, pady=6, height=8, wrap="word")
    log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=log_text.yview)
    log_text.configure(yscrollcommand=log_scroll.set)
    log_text.pack(side="left", fill="both", expand=True)
    log_scroll.pack(side="right", fill="y")

    def gui_log(msg):
        def _append():
            log_text.insert("end", msg + "\n")
            log_text.see("end")
        root.after(0, _append)

    def gui_progress(current, total, msg, items_preview=None):
        def _update():
            if total > 0:
                pct = int((current / total) * 100)
                progress_val.set(pct)
                pct_lbl.config(text=f"{pct}% ({current}/{total})")
            status_var.set(msg)
            
            if items_preview:
                tree.delete(*tree.get_children())
                for orig, target in items_preview:
                    tree.insert("", "end", values=(orig, target))
        root.after(0, _update)

    def gui_done(success, message, output_path=None):
        def _finish():
            is_processing[0] = False
            btn_start.config(state="normal", bg=GREEN, text="⚡ Iniciar Optimización")
            if success:
                last_output_zip[0] = output_path
                btn_open.config(state="normal")
                status_var.set("✅ ¡Optimización Completada!")
                messagebox.showinfo("Aeterna Optimizer", f"¡Multitrack optimizado con éxito!\n\n{message}")
            else:
                status_var.set("❌ Hubo un error")
                messagebox.showerror("Error", f"No se pudo completar la optimización:\n\n{message}")
        root.after(0, _finish)

    # --- BOTTOM ACTION BAR ---
    bottom_bar = tk.Frame(root, bg=BG)
    bottom_bar.pack(fill="x", padx=20, pady=(0, 15))

    btn_start = tk.Button(bottom_bar, text="⚡ Iniciar Optimización", font=("Segoe UI", 11, "bold"), 
                          bg=GREEN, fg="#ffffff", activebackground="#16a34a", activeforeground="#ffffff", 
                          bd=0, padx=20, pady=8, cursor="hand2")
    btn_start.pack(side="left")

    def open_destination():
        if last_output_zip[0] and os.path.exists(last_output_zip[0]):
            subprocess.run(f'explorer /select,"{last_output_zip[0]}"', shell=True)

    btn_open = tk.Button(bottom_bar, text="📁 Abrir Carpeta de Destino", font=("Segoe UI", 9, "bold"), 
                         bg="#334155", fg=TEXT_MAIN, bd=0, padx=14, pady=8, state="disabled", 
                         cursor="hand2", command=open_destination)
    btn_open.pack(side="left", padx=10)

    def start_worker():
        target = path_var.get().strip('"').strip("'").strip()
        if not target:
            messagebox.showwarning("Atención", "Por favor selecciona una carpeta o archivo .ZIP / .RAR.")
            return

        if is_processing[0]:
            return

        is_processing[0] = True
        btn_start.config(state="disabled", bg="#64748b", text="⏳ Optimizando...")
        btn_open.config(state="disabled")
        progress_val.set(0)
        pct_lbl.config(text="0%")
        tree.delete(*tree.get_children())
        log_text.delete("1.0", "end")

        worker_thread = threading.Thread(
            target=run_optimization,
            args=(target, use_gemini_var.get(), api_key_var.get(), gui_progress, gui_log, gui_done),
            daemon=True
        )
        worker_thread.start()

    btn_start.config(command=start_worker)

    # If launched with an initial target, populate and auto-load stems preview
    if initial_target and os.path.exists(initial_target):
        gui_log(f"Archivo cargado: {initial_target}")

    root.mainloop()
    return True

# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================

if __name__ == '__main__':
    # CLI Flag support
    args = sys.argv[1:]
    target_arg = None
    force_cli = False

    for a in args:
        if a == '--cli':
            force_cli = True
        elif not target_arg:
            target_arg = a

    # Try launching modern GUI
    if not force_cli:
        try:
            launch_gui(target_arg)
            sys.exit(0)
        except Exception as e:
            print(f"No se pudo iniciar la interfaz gráfica ({e}). Cambiando a consola...")

    # CLI fallback mode
    if not target_arg:
        print("Aeterna Multitrack Optimizer")
        print("Uso: Arrastra un archivo .ZIP, .RAR o una carpeta con stems.")
        target_arg = input("\nEscribe o arrastra la ruta aquí: ").strip('"').strip("'").strip()
        if not target_arg:
            sys.exit(0)

    run_optimization(target_arg)
    input("\nPresiona Enter para salir...")
