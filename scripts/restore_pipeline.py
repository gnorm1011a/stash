#!/usr/bin/env python3
"""Image Restoration Pipeline - multi-stage enhancement workflow.

Stage 1: Load directory and select images
Stage 2: Enhance full images with Real-ESRGAN
Stage 3: Apply face enhancement (GFPGAN / CodeFormer) and compare
Stage 4: Export chosen results
"""

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import tempfile
import urllib.parse
from pathlib import Path

# --- Configuration ---
HOST = "localhost"
PORT = 8766

ESRGAN_PYTHON = r"D:\Real-ESRGAN\venv\Scripts\python.exe"
ESRGAN_SCRIPT = r"D:\Real-ESRGAN\inference_realesrgan.py"
ESRGAN_CWD = r"D:\Real-ESRGAN"

GFPGAN_PYTHON = r"D:\GFPGAN\venv\Scripts\python.exe"
GFPGAN_SCRIPT = r"D:\GFPGAN\GFPGAN\inference_gfpgan.py"
GFPGAN_CWD = r"D:\GFPGAN\GFPGAN"

CODEFORMER_PYTHON = r"D:\CodeFormer\venv\Scripts\python.exe"
CODEFORMER_SCRIPT = r"D:\CodeFormer\inference_codeformer.py"
CODEFORMER_CWD = r"D:\CodeFormer"

FACE_MODELS = [
    {"id": "gfpgan", "name": "GFPGAN", "short": "GFPGAN"},
    {"id": "codeformer_w0.8", "name": "CodeFormer w=0.8", "short": "CF .8", "weight": "0.8"},
    {"id": "codeformer_w0.9", "name": "CodeFormer w=0.9", "short": "CF .9", "weight": "0.9"},
]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# --- Global State ---
state = {
    "input_dir": None,
    "images": [],          # list of {name, path}
    "selected": [],        # list of selected filenames
    "stage": "load",       # load -> esrgan -> face -> export
    "esrgan_dir": None,
    "face_dirs": {},       # model_id -> dir path
    "choices": {},         # filename -> model_id or "none"
    "progress": {
        "busy": False,
        "stage": "",
        "current": 0,
        "total": 0,
        "current_image": "",
        "status": "idle",
        "errors": [],
    },
}

# Working directory for intermediate results
WORK_DIR = None


def init_work_dir():
    global WORK_DIR
    WORK_DIR = Path(tempfile.mkdtemp(prefix="restore_pipeline_"))
    (WORK_DIR / "esrgan").mkdir(exist_ok=True)
    for m in FACE_MODELS:
        (WORK_DIR / m["id"]).mkdir(exist_ok=True)
    (WORK_DIR / "final").mkdir(exist_ok=True)


def reset_progress():
    state["progress"] = {
        "busy": False,
        "stage": "",
        "current": 0,
        "total": 0,
        "current_image": "",
        "status": "idle",
        "errors": [],
        "log": [],
    }


def log_msg(msg):
    """Add a message to the progress log and print to console."""
    print(f"[{state['progress']['stage']}] {msg}", flush=True)
    state["progress"]["log"].append(msg)
    # Keep log to last 200 lines
    if len(state["progress"]["log"]) > 200:
        state["progress"]["log"] = state["progress"]["log"][-200:]


def get_image_longest_side(img_path):
    """Get the longest dimension of an image without fully loading it."""
    try:
        from PIL import Image
        with Image.open(img_path) as img:
            return max(img.size)
    except Exception:
        return 0


def determine_esrgan_scale(longest_side):
    """Determine the appropriate ESRGAN output scale based on image size.
    
    Target: max output ~2000px on the longest side.
    - Large images (>= 2000px): scale=1 (enhance only, no upscaling)
    - Medium images (1000-2000px): scale=2
    - Small images (< 1000px): scale=4
    """
    if longest_side >= 2000:
        return 1
    elif longest_side >= 1000:
        return 2
    else:
        return 4


def run_esrgan_batch(input_dir, output_dir, scale=2):
    """Run Real-ESRGAN on a folder with intelligent per-image scaling.

    Groups images by scale category and runs ESRGAN separately for each group.
    """
    prog = state["progress"]
    prog["busy"] = True
    prog["stage"] = "esrgan"
    prog["status"] = "running"
    prog["errors"] = []
    prog["log"] = []

    # Count input images
    input_images = [f for f in Path(input_dir).iterdir() if f.suffix.lower() in IMAGE_EXTS]
    prog["total"] = len(input_images)
    prog["current"] = 0

    # Group images by scale based on dimensions
    scale_groups = {}  # scale -> list of filenames
    for img_path in input_images:
        longest = get_image_longest_side(img_path)
        s = determine_esrgan_scale(longest) if longest > 0 else scale
        scale_groups.setdefault(s, []).append(img_path.name)
        log_msg(f"  {img_path.name}: {longest}px -> scale={s}")

    log_msg(f"Scale groups: " + ", ".join(f"s={s}: {len(imgs)} images" for s, imgs in scale_groups.items()))

    try:
        for group_scale, filenames in sorted(scale_groups.items()):
            if not filenames:
                continue

            # Create a temp subfolder for this scale group
            scale_dir = Path(input_dir) / f"_scale_{group_scale}"
            scale_dir.mkdir(exist_ok=True)
            for fname in filenames:
                src = Path(input_dir) / fname
                if src.exists():
                    shutil.copy2(src, scale_dir / fname)

            cmd = [
                ESRGAN_PYTHON, "-u", ESRGAN_SCRIPT,
                "-i", str(scale_dir),
                "-o", str(output_dir),
                "-n", "RealESRGAN_x4plus",
                "-s", str(group_scale),
                "--fp32",
            ]

            log_msg(f"Running ESRGAN scale={group_scale}: {len(filenames)} images")
            log_msg(f"Command: {' '.join(cmd)}")

            proc = subprocess.Popen(
                cmd, cwd=ESRGAN_CWD,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("Testing "):
                    parts = line.split(None, 2)
                    if len(parts) >= 2:
                        prog["current"] = int(parts[1]) + 1
                        prog["current_image"] = parts[2] if len(parts) > 2 else ""
                        log_msg(f"Processing {prog['current']}/{prog['total']}: {prog['current_image']}")
                elif "Error" in line and "slow_conv2d" not in line:
                    prog["errors"].append(line)
                    log_msg(f"ERROR: {line}")
                elif "Traceback" in line or "RuntimeError" in line:
                    prog["errors"].append(line)
                    log_msg(f"ERROR: {line}")
                else:
                    log_msg(f"  {line}")

            proc.wait()
            log_msg(f"Process exited with code {proc.returncode}")
            if proc.returncode != 0 and not prog["errors"]:
                prog["errors"].append(f"Process exited with code {proc.returncode}")
                log_msg(f"ERROR: Process exited with code {proc.returncode}")

            # Clean up temp scale dir
            try:
                shutil.rmtree(scale_dir)
            except Exception:
                pass

        # Count actual outputs
        outputs = list(Path(output_dir).glob("*_out.*"))
        prog["current"] = len(outputs)
        log_msg(f"Output count: {len(outputs)} files in {output_dir}")
        prog["status"] = "done" if not prog["errors"] else "error"
        log_msg(f"ESRGAN {'completed successfully' if prog['status'] == 'done' else 'completed with errors'}")
    except Exception as e:
        prog["errors"].append(str(e))
        prog["status"] = "error"
        log_msg(f"EXCEPTION: {e}")
    finally:
        prog["busy"] = False


def run_face_model_batch(model, input_dir, output_dir, scale=1):
    """Run a face enhancement model (GFPGAN or CodeFormer) on a folder."""
    prog = state["progress"]
    prog["stage"] = f"face_{model['id']}"
    prog["current"] = 0
    prog["errors"] = []

    input_images = [f for f in Path(input_dir).iterdir() if f.suffix.lower() in IMAGE_EXTS]
    prog["total"] = len(input_images)

    if model["id"] == "gfpgan":
        cmd = [
            GFPGAN_PYTHON, "-u", GFPGAN_SCRIPT,
            "-i", str(input_dir),
            "-o", str(output_dir),
            "-v", "1.4",
            "--bg_upsampler", "None",
            "-s", str(scale),
        ]
        cwd = GFPGAN_CWD
        restored_subdir = "restored_imgs"
        progress_prefix = "Processing"
    else:
        cmd = [
            CODEFORMER_PYTHON, "-u", CODEFORMER_SCRIPT,
            "-i", str(input_dir),
            "-o", str(output_dir),
            "-w", model["weight"],
            "-s", str(scale),
            "--bg_upsampler", "None",
        ]
        cwd = CODEFORMER_CWD
        restored_subdir = "final_results"
        progress_prefix = "Processing"

    log_msg(f"Starting {model['name']}: {len(input_images)} images")
    log_msg(f"Command: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            if progress_prefix in line and "/" in line:
                if "[" in line and "]" in line:
                    bracket = line[line.index("[")+1:line.index("]")]
                    cur, total = bracket.split("/")
                    prog["current"] = int(cur)
                    prog["total"] = int(total)
                if ":" in line:
                    name_part = line.split(":")[-1].strip()
                    prog["current_image"] = name_part
                log_msg(f"Processing {prog['current']}/{prog['total']}: {prog['current_image']}")
            elif line.startswith("Error") or "Traceback" in line or "RuntimeError" in line:
                prog["errors"].append(line)
                log_msg(f"ERROR: {line}")
            else:
                log_msg(f"  {line}")

        proc.wait()
        log_msg(f"{model['name']} exited with code {proc.returncode}")
        prog["status"] = "done" if proc.returncode == 0 or not prog["errors"] else "error"
    except Exception as e:
        prog["errors"].append(str(e))
        prog["status"] = "error"
        log_msg(f"EXCEPTION: {e}")


def run_all_face_models(esrgan_dir):
    """Run all face models sequentially on ESRGAN outputs."""
    prog = state["progress"]
    prog["busy"] = True
    prog["status"] = "running"

    for i, model in enumerate(FACE_MODELS):
        prog["stage"] = f"face_{model['id']} ({i+1}/{len(FACE_MODELS)})"
        out_dir = WORK_DIR / model["id"]
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(exist_ok=True)
        run_face_model_batch(model, esrgan_dir, out_dir)
        state["face_dirs"][model["id"]] = str(out_dir)
        log_msg(f"Finished {model['name']}, status: {prog['status']}")

    prog["busy"] = False
    prog["status"] = "done"
    log_msg("All face models complete")


def find_esrgan_output(esrgan_dir, basename):
    """Find ESRGAN output for a given basename (files have _out suffix)."""
    for ext in [".png", ".jpg", ".jpeg"]:
        candidate = Path(esrgan_dir) / f"{basename}_out{ext}"
        if candidate.exists():
            return candidate.name
    return None


def find_face_output(model_id, face_dir, basename):
    """Find face model output for a given basename."""
    if model_id == "gfpgan":
        subdir = Path(face_dir) / "restored_imgs"
    else:
        subdir = Path(face_dir) / "final_results"
    if not subdir.exists():
        return None
    for ext in [".png", ".jpg", ".jpeg"]:
        candidate = subdir / f"{basename}{ext}"
        if candidate.exists():
            return f"{model_id}/restored_imgs/{candidate.name}" if model_id == "gfpgan" else f"{model_id}/final_results/{candidate.name}"
    return None


# --- HTTP Handler ---
class PipelineHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self.send_html()
        elif path == "/api/progress":
            self.send_json(state["progress"])
        elif path == "/api/state":
            self.send_json(get_full_state())
        elif path == "/api/browse":
            dir_path = query.get("dir", [""])[0]
            self.handle_browse(dir_path)
        elif path.startswith("/files/"):
            self.serve_file(urllib.parse.unquote(path[7:]))
        elif path.startswith("/thumb/"):
            self.serve_thumbnail(urllib.parse.unquote(path[7:]))
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        if path == "/api/scan":
            self.handle_scan(data)
        elif path == "/api/esrgan":
            self.handle_esrgan(data)
        elif path == "/api/face-enhance":
            self.handle_face_enhance(data)
        elif path == "/api/choose":
            self.handle_choose(data)
        elif path == "/api/export":
            self.handle_export(data)
        elif path == "/api/reset":
            self.handle_reset()
        else:
            self.send_error(404)

    def send_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_CONTENT.encode("utf-8"))

    def send_json(self, obj):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode("utf-8"))

    def serve_file(self, rel_path):
        # Handle original/ paths by serving from input directory
        if rel_path.startswith("original/"):
            orig_name = rel_path[9:]
            if state["input_dir"]:
                file_path = Path(state["input_dir"]) / orig_name
                if file_path.exists() and file_path.is_file():
                    self._send_image_file(file_path)
                    return
            self.send_error(404)
            return

        if not WORK_DIR:
            self.send_error(404)
            return
        file_path = WORK_DIR / rel_path
        if file_path.exists() and file_path.is_file():
            self._send_image_file(file_path)
        else:
            self.send_error(404)

    def _send_image_file(self, file_path):
        self.send_response(200)
        ext = file_path.suffix.lower()
        ct = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "bmp": "image/bmp"}.get(ext.lstrip("."), "application/octet-stream")
        self.send_header("Content-Type", ct)
        self.end_headers()
        with open(file_path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def serve_thumbnail(self, rel_path):
        """Serve a file from the input directory (for thumbnails)."""
        input_dir = state.get("input_dir")
        if not input_dir:
            self.send_error(404)
            return
        file_path = Path(input_dir) / urllib.parse.unquote(rel_path)
        if file_path.exists() and file_path.is_file():
            self.send_response(200)
            ext = file_path.suffix.lower()
            ct = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "bmp": "image/bmp"}.get(ext.lstrip("."), "application/octet-stream")
            self.send_header("Content-Type", ct)
            self.end_headers()
            with open(file_path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)
        else:
            self.send_error(404)

    def handle_browse(self, dir_path):
        """Browse directories — returns subdirectories and parent."""
        if not dir_path:
            # Return drive list on Windows
            try:
                import string
                drives = []
                for letter in string.ascii_uppercase:
                    drive = f"{letter}:\\"
                    if Path(drive).exists():
                        drives.append(drive)
                # Also add common UNC base
                self.send_json({"current": "", "parent": None, "dirs": drives, "drives": True})
                return
            except Exception:
                dir_path = "C:\\"

        try:
            p = Path(dir_path)
            if not p.is_dir():
                self.send_json({"error": "Not a valid directory"})
                return

            dirs = []
            try:
                with os.scandir(str(p)) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            dirs.append(entry.name)
            except (PermissionError, OSError):
                pass
            dirs.sort(key=str.lower)

            parent = str(p.parent) if p.parent != p else None
            self.send_json({"current": str(p), "parent": parent, "dirs": dirs, "drives": False})
        except Exception as e:
            self.send_json({"error": str(e)})

    def handle_scan(self, data):
        directory = data.get("directory", "").strip()
        if not directory or not Path(directory).exists():
            self.send_json({"error": "Directory not found"})
            return

        init_work_dir()
        reset_progress()
        state["input_dir"] = directory
        state["selected"] = []
        state["choices"] = {}
        state["face_dirs"] = {}
        state["stage"] = "load"

        images = []
        for f in sorted(Path(directory).iterdir()):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                images.append({"name": f.name, "stem": f.stem})

        state["images"] = images
        self.send_json({"images": images, "count": len(images)})

    def handle_esrgan(self, data):
        if state["progress"]["busy"]:
            self.send_json({"error": "Already processing"})
            return

        selected = data.get("selected", [])
        if not selected:
            self.send_json({"error": "No images selected"})
            return

        state["selected"] = selected
        state["stage"] = "esrgan"
        reset_progress()
        state["progress"]["busy"] = True
        state["progress"]["stage"] = "esrgan"
        state["progress"]["status"] = "preparing"

        # Copy selected images to work dir input folder
        input_copy = WORK_DIR / "input"
        if input_copy.exists():
            shutil.rmtree(input_copy)
        input_copy.mkdir(exist_ok=True)

        copied = 0
        for name in selected:
            src = Path(state["input_dir"]) / name
            if src.exists():
                shutil.copy2(src, input_copy / name)
                copied += 1

        print(f"[esrgan] Copied {copied}/{len(selected)} images to {input_copy}", flush=True)
        state["progress"]["log"].append(f"Copied {copied}/{len(selected)} images to work directory")

        esrgan_dir = WORK_DIR / "esrgan"
        if esrgan_dir.exists():
            shutil.rmtree(esrgan_dir)
        esrgan_dir.mkdir(exist_ok=True)
        state["esrgan_dir"] = str(esrgan_dir)

        # Run in background thread
        thread = threading.Thread(target=run_esrgan_batch, args=(input_copy, esrgan_dir), daemon=True)
        thread.start()

        self.send_json({"status": "started", "count": len(selected)})

    def handle_face_enhance(self, data):
        if state["progress"]["busy"]:
            self.send_json({"error": "Already processing"})
            return

        esrgan_dir = state.get("esrgan_dir")
        if not esrgan_dir or not Path(esrgan_dir).exists():
            self.send_json({"error": "ESRGAN output not found"})
            return

        state["stage"] = "face"

        # Run all face models in background thread
        thread = threading.Thread(target=run_all_face_models, args=(esrgan_dir,), daemon=True)
        thread.start()

        self.send_json({"status": "started"})

    def handle_choose(self, data):
        filename = data.get("filename")
        model_id = data.get("model")  # model_id or "none"
        if not filename:
            self.send_json({"error": "No filename"})
            return
        state["choices"][filename] = model_id
        self.send_json({"status": "ok", "choices": state["choices"]})

    def handle_export(self, data):
        output_dir = data.get("output_dir", "").strip()
        if not output_dir:
            self.send_json({"error": "No output directory"})
            return

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        exported = 0
        errors = []

        for filename, model_id in state["choices"].items():
            basename = Path(filename).stem
            try:
                if model_id == "none":
                    # Use ESRGAN output
                    src_name = find_esrgan_output(state["esrgan_dir"], basename)
                    if src_name:
                        src = Path(state["esrgan_dir"]) / src_name
                        dst = Path(output_dir) / filename
                        shutil.copy2(src, dst)
                        exported += 1
                else:
                    # Use face model output
                    face_dir = state["face_dirs"].get(model_id)
                    if face_dir:
                        if model_id == "gfpgan":
                            subdir = Path(face_dir) / "restored_imgs"
                        else:
                            subdir = Path(face_dir) / "final_results"
                        # Face model outputs may have _out suffix (from ESRGAN input naming)
                        for ext in [".png", ".jpg", ".jpeg"]:
                            for name_pattern in [f"{basename}{ext}", f"{basename}_out{ext}"]:
                                candidate = subdir / name_pattern
                                if candidate.exists():
                                    dst = Path(output_dir) / f"{basename}{ext}"
                                    shutil.copy2(candidate, dst)
                                    exported += 1
                                    break
                            else:
                                continue
                            break
            except Exception as e:
                errors.append(f"{filename}: {e}")

        self.send_json({"exported": exported, "errors": errors, "output_dir": output_dir})

    def handle_reset(self):
        state["input_dir"] = None
        state["images"] = []
        state["selected"] = []
        state["choices"] = {}
        state["face_dirs"] = {}
        state["esrgan_dir"] = None
        state["stage"] = "load"
        reset_progress()
        self.send_json({"status": "ok"})

    def log_message(self, format, *args):
        pass  # suppress logging


def get_full_state():
    s = {
        "stage": state["stage"],
        "input_dir": state["input_dir"],
        "images": state["images"],
        "selected": state["selected"],
        "choices": state["choices"],
        "progress": state["progress"],
        "face_models": [{"id": m["id"], "name": m["name"], "short": m["short"]} for m in FACE_MODELS],
    }

    # Original images (from input dir, keyed by basename)
    s["original_outputs"] = {}
    if state["input_dir"]:
        for f in Path(state["input_dir"]).iterdir():
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                s["original_outputs"][f.stem] = f"original/{f.name}"

    # ESRGAN (Enhanced) outputs
    if state["esrgan_dir"]:
        esrgan_dir = Path(state["esrgan_dir"])
        s["esrgan_outputs"] = {}
        for f in esrgan_dir.iterdir():
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                name = f.name
                if name.endswith("_out.png"):
                    stem = name[:-8]
                elif name.endswith("_out.jpg"):
                    stem = name[:-8]
                elif name.endswith("_out.jpeg"):
                    stem = name[:-9]
                else:
                    stem = f.stem
                s["esrgan_outputs"][stem] = f"esrgan/{f.name}"

    # Face outputs — full images, cropped faces, and restored faces
    s["face_outputs"] = {}
    s["cropped_faces"] = {}
    s["restored_faces"] = {}
    if state["face_dirs"]:
        for model_id, face_dir_path in state["face_dirs"].items():
            face_dir = Path(face_dir_path)
            # Full restored images
            if model_id == "gfpgan":
                subdir = face_dir / "restored_imgs"
            else:
                subdir = face_dir / "final_results"
            if subdir.exists():
                s["face_outputs"][model_id] = {}
                for f in subdir.iterdir():
                    if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                        stem = f.stem
                        if stem.endswith("_out"):
                            stem = stem[:-4]
                        s["face_outputs"][model_id][stem] = f"{model_id}/{subdir.name}/{f.name}"

            # Cropped faces (original crops before restoration)
            cropped_dir = face_dir / "cropped_faces"
            if cropped_dir.exists():
                s["cropped_faces"][model_id] = {}
                for f in sorted(cropped_dir.iterdir()):
                    if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                        stem = f.stem
                        # Split off face index suffix first (e.g. _00, _01)
                        parts = stem.rsplit("_", 1)
                        if len(parts) > 1 and parts[1].isdigit():
                            base = parts[0]
                            face_idx = parts[1]
                        else:
                            base = stem
                            face_idx = "0"
                        # Now strip _out suffix from base to match ESRGAN keys
                        if base.endswith("_out"):
                            base = base[:-4]
                        if base not in s["cropped_faces"][model_id]:
                            s["cropped_faces"][model_id][base] = []
                        s["cropped_faces"][model_id][base].append({
                            "idx": int(face_idx),
                            "path": f"{model_id}/cropped_faces/{f.name}"
                        })

            # Restored faces
            restored_dir = face_dir / "restored_faces"
            if restored_dir.exists():
                s["restored_faces"][model_id] = {}
                for f in sorted(restored_dir.iterdir()):
                    if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                        stem = f.stem
                        parts = stem.rsplit("_", 1)
                        if len(parts) > 1 and parts[1].isdigit():
                            base = parts[0]
                            face_idx = parts[1]
                        else:
                            base = stem
                            face_idx = "0"
                        if base.endswith("_out"):
                            base = base[:-4]
                        if base not in s["restored_faces"][model_id]:
                            s["restored_faces"][model_id][base] = []
                        s["restored_faces"][model_id][base].append({
                            "idx": int(face_idx),
                            "path": f"{model_id}/restored_faces/{f.name}"
                        })
    return s


# --- HTML UI ---
HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Image Restoration Pipeline</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a1a; color: #e0e0e0; }
body { display: flex; flex-direction: column; }

.topbar { background: #2a2a2a; padding: 10px 20px; display: flex; align-items: center; gap: 20px; border-bottom: 1px solid #3a3a3a; flex-shrink: 0; position: relative; }
.topbar h1 { font-size: 16px; font-weight: 600; white-space: nowrap; z-index: 1; }

.stepper { display: flex; gap: 4px; position: absolute; left: 50%; transform: translateX(-50%); }
.step { padding: 6px 16px; border-radius: 4px; font-size: 12px; background: #333; color: #666; border: 1px solid #444; }
.step.active { background: #5050dd; color: #fff; border-color: #5050dd; }
.step.done { background: #2a5a2a; color: #8c8; border-color: #3a7a3a; }

.content { flex: 1; overflow: hidden; display: flex; flex-direction: column; }
.panel { display: none; flex: 1; overflow: auto; padding: 20px; }
.panel.active { display: flex; flex-direction: column; }

/* Stage 1: Load */
.load-panel { align-items: flex-start; justify-content: flex-start; gap: 0; padding: 0; flex-direction: column; overflow: hidden; }
.dir-input { display: flex; gap: 8px; width: 100%; max-width: 600px; }
.dir-input input { flex: 1; background: #333; border: 1px solid #444; color: #e0e0e0; padding: 8px 12px; border-radius: 4px; font-size: 14px; }
.btn { background: #5050dd; border: none; color: #fff; padding: 8px 20px; border-radius: 4px; cursor: pointer; font-size: 14px; }
.btn:hover { background: #6060ee; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-secondary { background: #3a3a3a; border: 1px solid #4a4a4a; }
.btn-secondary:hover { background: #4a4a4a; }

/* Toggle button groups (matching face comparison app) */
.toggle-btns { display: flex; gap: 0; }
.toggle-btn { background: #3a3a3a; border: 1px solid #4a4a4a; color: #aaa; padding: 4px 14px; cursor: pointer; font-size: 12px; }
.toggle-btn:first-child { border-radius: 4px 0 0 4px; }
.toggle-btn:last-child { border-radius: 0 4px 4px 0; border-left: none; }
.toggle-btn.active { background: #5050dd; color: #fff; border-color: #5050dd; }

/* Step 1 header: search bar + collapsed search */
.step1-header { padding: 20px; width: 100%; text-align: center; }
.step1-header h2 { text-align: center; }
.step1-header .dir-input { margin: 0 auto; }
.step1-header.collapsed .dir-input { display: none; }
.step1-header.collapsed .scan-error { display: none; }
.step1-collapsed-path { display: none; align-items: center; gap: 8px; font-size: 13px; color: #888; justify-content: center; }
.step1-header.collapsed .step1-collapsed-path { display: flex; }
.step1-collapsed-path .path-text { color: #aaa; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 500px; }
.step1-collapsed-path .folder-icon-btn { background: none; border: none; color: #888; cursor: pointer; font-size: 16px; padding: 2px 6px; border-radius: 4px; flex-shrink: 0; }
.step1-collapsed-path .folder-icon-btn:hover { background: #333; color: #aaa; }

/* Sticky toolbar */
.sticky-toolbar { position: sticky; top: 0; z-index: 20; background: #2a2a2a; border-bottom: 1px solid #3a3a3a; padding: 10px 20px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; justify-content: center; }
.sticky-toolbar .selection-info { font-size: 14px; color: #888; min-width: 100px; text-align: center; }
.sticky-toolbar .size-control { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #888; }
.sticky-toolbar .size-control input[type="range"] { width: 100px; cursor: pointer; }

/* Gallery with virtual scroll wrapper */
.gallery-scroll { flex: 1; overflow-y: auto; padding: 16px 20px; width: 100%; }
.image-grid { display: grid; gap: 8px; width: 100%; }
.image-card { cursor: pointer; border-radius: 6px; overflow: hidden; border: 2px solid transparent; position: relative; aspect-ratio: 4/3; }
.image-card:hover { border-color: #666; }
.image-card.selected { border-color: #5050dd; }
.image-card img { width: 100%; height: 100%; object-fit: cover; display: block; }
.image-card .card-checkbox { position: absolute; top: 4px; left: 4px; width: 22px; height: 22px; background: rgba(0,0,0,0.6); border: 2px solid #888; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 14px; color: #fff; cursor: pointer; z-index: 2; transition: background 0.15s, border-color 0.15s; }
.image-card .card-checkbox:hover { background: rgba(80,80,221,0.5); border-color: #aaa; }
.image-card.selected .card-checkbox { background: #5050dd; border-color: #5050dd; }
.image-card .name-overlay { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.7); color: #ccc; font-size: 9px; padding: 2px 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; opacity: 0; transition: opacity 0.15s; }
.image-card:hover .name-overlay { opacity: 1; }

/* Stage 2: ESRGAN */
.process-panel { padding: 0; flex-direction: column; overflow: hidden; }
.esrgan-progress-view { flex: 1; display: flex; flex-direction: row; overflow: hidden; }
.esrgan-progress-sidebar { width: 140px; flex-shrink: 0; overflow-y: auto; border-right: 1px solid #333; padding: 6px; }
.esrgan-progress-sidebar .face-sidebar-thumb { margin-bottom: 4px; border-radius: 4px; overflow: hidden; border: 2px solid transparent; aspect-ratio: 4/3; position: relative; }
.esrgan-progress-sidebar .face-sidebar-thumb.done { border-color: #3a7a3a; }
.esrgan-progress-sidebar .face-sidebar-thumb.processing { border-color: #5050dd; }
.esrgan-progress-sidebar .face-sidebar-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.esrgan-progress-sidebar .face-sidebar-thumb .status-icon { position: absolute; top: 2px; right: 2px; width: 16px; height: 16px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 10px; color: #fff; }
.esrgan-progress-sidebar .face-sidebar-thumb.done .status-icon { background: #3a7a3a; }
.esrgan-progress-sidebar .face-sidebar-thumb.processing .status-icon { background: #5050dd; }
.esrgan-progress-sidebar .face-sidebar-thumb .status-icon.checkmark { background: #3a7a3a; }
.esrgan-progress-sidebar .face-sidebar-thumb .status-spinner { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 20px; height: 20px; border: 3px solid rgba(255,255,255,0.2); border-top-color: #5050dd; border-radius: 50%; animation: spin 0.8s linear infinite; }
.esrgan-progress-sidebar .face-sidebar-thumb .status-pending { position: absolute; top: 2px; right: 2px; width: 10px; height: 10px; border-radius: 50%; background: #444; }
@keyframes spin { to { transform: translate(-50%, -50%) rotate(360deg); } }
.esrgan-progress-center { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 20px; padding: 20px; overflow-y: auto; }
.progress-container { width: 100%; max-width: 500px; text-align: center; }
.progress-bar { width: 100%; height: 24px; background: #333; border-radius: 12px; overflow: hidden; margin: 12px 0; }
.progress-fill { height: 100%; background: #5050dd; transition: width 0.3s; }
.progress-text { font-size: 14px; color: #aaa; }
.progress-image { font-size: 12px; color: #666; margin-top: 4px; }
.progress-errors { color: #a55; font-size: 12px; margin-top: 8px; max-height: 100px; overflow-y: auto; }
.progress-log { text-align: left; background: #222; border: 1px solid #333; border-radius: 4px; padding: 10px; margin-top: 12px; max-height: 200px; overflow-y: auto; font-family: 'Consolas', 'Monaco', monospace; font-size: 11px; line-height: 1.5; color: #888; width: 100%; max-width: 600px; }
.progress-log .log-error { color: #a55; }
.progress-log .log-line { white-space: pre-wrap; word-break: break-all; }

/* Step 2 comparison view - matches Step 3 layout */
.esrgan-compare { flex: 1; display: flex; flex-direction: row; overflow: hidden; }
.esrgan-compare-sidebar { width: 160px; min-width: 80px; max-width: 400px; flex-shrink: 0; overflow-y: auto; border-right: 1px solid #333; padding: 6px; display: flex; flex-direction: column; }
.esrgan-compare-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.esrgan-compare-toolbar { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: #2a2a2a; border-bottom: 1px solid #3a3a3a; flex-shrink: 0; }
.esrgan-compare-toolbar .counter { font-size: 12px; color: #666; white-space: nowrap; }
.esrgan-compare-body { flex: 1; display: flex; overflow: hidden; }
.esrgan-compare-canvas { flex: 1; overflow: hidden; position: relative; display: flex; align-items: center; justify-content: center; }

/* Stage 3: Face comparison - matches face restoration app */
.face-panel { padding: 0; flex-direction: column; overflow: hidden; }
.face-sidebar { width: 160px; min-width: 80px; max-width: 400px; flex-shrink: 0; overflow-y: auto; border-right: 1px solid #333; padding: 6px; display: flex; flex-direction: column; }
.face-sidebar-thumbs { flex: 1; overflow-y: auto; }
.face-sidebar-thumb { cursor: pointer; border-radius: 4px; overflow: hidden; border: 2px solid transparent; margin-bottom: 4px; position: relative; }
.face-sidebar-thumb:hover { border-color: #555; }
.face-sidebar-thumb.active { border-color: #5050dd; }
.face-sidebar-thumb.completed { border-color: #3a7a3a; }
.face-sidebar-thumb img { width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block; }
.face-sidebar-thumb .choice-badge { position: absolute; bottom: 2px; left: 2px; background: rgba(80,80,221,0.9); color: #fff; font-size: 8px; padding: 1px 4px; border-radius: 3px; }
.face-sidebar-thumb .choice-badge.none { background: rgba(100,100,100,0.9); }
.face-sidebar-thumb .done-dot { position: absolute; top: 2px; right: 2px; width: 8px; height: 8px; border-radius: 50%; background: #3a7a3a; }
.face-sidebar-thumb .thumb-filename { font-size: 9px; color: #888; padding: 2px 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: #222; }
.face-sidebar-nav { display: flex; gap: 4px; padding: 6px 0; border-top: 1px solid #333; flex-shrink: 0; }
.face-sidebar-nav button { flex: 1; background: #3a3a3a; border: 1px solid #4a4a4a; color: #e0e0e0; padding: 6px; border-radius: 4px; cursor: pointer; font-size: 12px; }
.face-sidebar-nav button:hover { background: #4a4a4a; }
.face-sidebar-nav button:disabled { opacity: 0.3; cursor: not-allowed; }
.gallery-resizer { width: 6px; background: #3a3a3a; cursor: ew-resize; flex-shrink: 0; transition: background 0.15s; }
.gallery-resizer:hover { background: #5050dd; }

.face-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.face-toolbar { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: #2a2a2a; border-bottom: 1px solid #3a3a3a; flex-shrink: 0; }
.face-toolbar .filename { font-size: 13px; color: #aaa; flex: 1; min-width: 80px; }
.face-toolbar .counter { font-size: 12px; color: #666; white-space: nowrap; }

/* Main content area with right panel */
.face-body { flex: 1; display: flex; overflow: hidden; }
.face-canvas-area { flex: 1; overflow: hidden; position: relative; display: flex; align-items: center; justify-content: center; }

/* Right sidebar - always visible, matches face restoration app */
.faces-sidebar { width: 220px; background: #2a2a2a; border-left: 1px solid #3a3a3a; overflow-y: auto; flex-shrink: 0; padding: 10px; position: relative; }
.faces-sidebar-header { display: flex; justify-content: flex-end; margin-bottom: 8px; }
.expand-btn { background: #3a3a3a; border: 1px solid #4a4a4a; color: #aaa; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 11px; }
.expand-btn:hover { background: #4a4a4a; }
.face-group { margin-bottom: 16px; border-bottom: 1px solid #333; padding-bottom: 10px; }
.face-row { text-align: center; margin-bottom: 8px; cursor: pointer; }
.face-row img { width: 100%; max-width: 190px; border-radius: 4px; border: 2px solid #444; display: block; margin: 0 auto; }
.face-row.restored img { border-color: #5050dd; }
.face-row img:hover { border-color: #777; }
.face-row.restored img:hover { border-color: #7070ee; }
.face-row.active img { border-color: #5050dd; box-shadow: 0 0 8px rgba(80,80,221,0.4); }
.face-row-label { font-size: 10px; color: #888; margin-top: 3px; }
.face-row-badge { position: absolute; bottom: 4px; right: 4px; background: rgba(80,80,221,0.85); color: #fff; font-size: 8px; padding: 1px 5px; border-radius: 3px; pointer-events: none; }
.face-row { position: relative; }

/* Full-screen overlay for expanded faces/images */
.faces-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.95); z-index: 100; display: flex; flex-direction: column; padding: 20px; }
.faces-overlay-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-shrink: 0; }
.faces-overlay-grid { flex: 1; overflow-y: auto; width: 100%; max-width: 800px; margin: 0 auto; display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.faces-overlay-item { text-align: center; }
.faces-overlay-item img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 8px; border: 2px solid #444; cursor: pointer; }
.faces-overlay-item.restored img { border-color: #5050dd; }
.faces-overlay-item-label { font-size: 12px; color: #aaa; margin-top: 4px; }
.faces-overlay-face-sep { grid-column: 1 / -1; height: 1px; background: #444; margin: 8px 0; }

/* Model bar (small buttons above each comparison panel) */
.model-bar { display: flex; gap: 3px; margin-bottom: 4px; flex-wrap: wrap; justify-content: center; }
.model-toggle { background: #3a3a3a; border: 1px solid #4a4a4a; color: #888; padding: 3px 8px; border-radius: 3px; cursor: pointer; font-size: 10px; }
.model-toggle.active { background: #5050dd; color: #fff; border-color: #5050dd; }
.model-toggle:hover { background: #4a4a4a; }

/* Side-by-side */
.side-by-side { display: flex; gap: 6px; justify-content: center; align-items: flex-start; }
.side-panel { display: flex; flex-direction: column; align-items: center; }
.side-panel canvas { background: #111; border-radius: 4px; cursor: grab; }
.side-panel canvas:active { cursor: grabbing; }

/* Swipe */
.swipe-container { display: flex; flex-direction: column; align-items: center; }
.swipe-bars { display: flex; gap: 6px; margin-bottom: 4px; }
.swipe-img-area { display: flex; justify-content: center; }
.swipe-wrap { position: relative; }
.swipe-wrap canvas { background: #111; border-radius: 4px; cursor: grab; display: block; }
.swipe-wrap canvas:active { cursor: grabbing; }
.swipe-divider { position: absolute; top: 0; bottom: 0; width: 2px; background: #5050dd; cursor: ew-resize; z-index: 5; }
.swipe-divider::after { content: ''; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 20px; height: 20px; background: #5050dd; border-radius: 50%; }
.swipe-label { position: absolute; top: 4px; font-size: 10px; color: #fff; background: rgba(0,0,0,0.6); padding: 2px 6px; border-radius: 3px; pointer-events: none; }
.swipe-label-left { left: 4px; }
.swipe-label-right { right: 4px; }

.zoom-info { position: absolute; bottom: 8px; left: 12px; font-size: 10px; color: #888; background: rgba(0,0,0,0.5); padding: 2px 6px; border-radius: 3px; pointer-events: none; }

/* Floating dock */
.floating-dock { position: fixed; bottom: 16px; right: 16px; background: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 8px; padding: 12px 16px; z-index: 50; display: flex; flex-direction: column; gap: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }
.floating-dock .dock-title { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 1px; }
.floating-dock .dock-row { display: flex; gap: 6px; align-items: center; }
.floating-dock .dock-btn { background: #3a3a3a; border: 1px solid #4a4a4a; color: #ccc; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 12px; }
.floating-dock .dock-btn:hover { background: #4a4a4a; }
.floating-dock .dock-btn.chosen { background: #5050dd; color: #fff; border-color: #5050dd; }
.floating-dock .dock-btn.neutral { background: #3a3a3a; color: #888; }

/* Stage 3 pre-processing */
.face-pre { padding: 0; overflow: hidden; display: flex; flex-direction: row; }
.face-pre-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; margin-top: 16px; }
.face-pre-thumb { border-radius: 6px; overflow: hidden; border: 2px solid #333; aspect-ratio: 4/3; }
.face-pre-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.face-pre-thumb:hover { border-color: #555; }
.face-progress-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); gap: 6px; margin-top: 16px; max-width: 600px; margin-left: auto; margin-right: auto; }
.face-progress-item { border-radius: 4px; overflow: hidden; border: 2px solid #333; aspect-ratio: 4/3; position: relative; }
.face-progress-item.done { border-color: #3a7a3a; }
.face-progress-item.processing { border-color: #5050dd; }
.face-progress-item img { width: 100%; height: 100%; object-fit: cover; display: block; }
.face-progress-item .status-icon { position: absolute; top: 2px; right: 2px; width: 16px; height: 16px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 10px; color: #fff; }
.face-progress-item.done .status-icon { background: #3a7a3a; }
.face-progress-item.processing .status-icon { background: #5050dd; }
.face-progress-item .model-count { position: absolute; bottom: 2px; left: 2px; background: rgba(0,0,0,0.7); color: #ccc; font-size: 8px; padding: 1px 4px; border-radius: 3px; }

/* Stage 4: Export */
.export-panel { align-items: center; justify-content: flex-start; gap: 20px; padding-top: 40px; }
.export-summary { width: 100%; max-width: 600px; }
.export-summary table { width: 100%; border-collapse: collapse; }
.export-summary th, .export-summary td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #333; font-size: 13px; }
.export-summary th { color: #888; font-weight: 600; }
.export-count { font-size: 16px; color: #8c8; margin: 16px 0; }

/* Directory browser modal */
.modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.8); z-index: 200; display: flex; align-items: center; justify-content: center; }
.modal { background: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 8px; width: 90%; max-width: 600px; max-height: 80vh; display: flex; flex-direction: column; }
.modal-header { padding: 16px 20px; border-bottom: 1px solid #3a3a3a; display: flex; justify-content: space-between; align-items: center; }
.modal-header h3 { font-size: 15px; }
.modal-body { flex: 1; overflow-y: auto; padding: 12px 20px; }
.modal-footer { padding: 12px 20px; border-top: 1px solid #3a3a3a; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.modal-path { font-size: 12px; color: #888; word-break: break-all; flex: 1; }
.dir-list { list-style: none; }
.dir-list-item { padding: 8px 12px; cursor: pointer; border-radius: 4px; font-size: 14px; display: flex; align-items: center; gap: 8px; }
.dir-list-item:hover { background: #333; }
.dir-list-item.up { color: #888; font-style: italic; }
.dir-list-icon { font-size: 16px; }

/* Full-screen image viewer */
.viewer-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.97); z-index: 150; display: flex; flex-direction: column; }
.viewer-header { padding: 12px 20px; display: flex; align-items: center; gap: 16px; flex-shrink: 0; }
.viewer-header .filename { font-size: 14px; color: #aaa; flex: 1; }
.viewer-header .counter { font-size: 13px; color: #666; }
.viewer-body { flex: 1; display: flex; align-items: center; justify-content: center; position: relative; overflow: hidden; }
.viewer-body img { max-width: 90%; max-height: 100%; object-fit: contain; border-radius: 4px; }
.viewer-nav { position: absolute; top: 50%; transform: translateY(-50%); background: rgba(60,60,60,0.8); border: none; color: #fff; width: 48px; height: 48px; border-radius: 50%; cursor: pointer; font-size: 20px; display: flex; align-items: center; justify-content: center; }
.viewer-nav:hover { background: rgba(80,80,80,0.9); }
.viewer-nav.prev { left: 16px; }
.viewer-nav.next { right: 16px; }
.viewer-nav:disabled { opacity: 0.3; cursor: not-allowed; }
.viewer-footer { padding: 12px 20px; display: flex; align-items: center; gap: 12px; justify-content: center; flex-shrink: 0; }
.viewer-select-btn { background: #3a3a3a; border: 1px solid #4a4a4a; color: #aaa; padding: 8px 24px; border-radius: 4px; cursor: pointer; font-size: 14px; }
.viewer-select-btn:hover { background: #4a4a4a; }
.viewer-select-btn.selected { background: #5050dd; color: #fff; border-color: #5050dd; }
.viewer-close { background: #3a3a3a; border: 1px solid #4a4a4a; color: #aaa; padding: 6px 16px; border-radius: 4px; cursor: pointer; font-size: 13px; }
.viewer-close:hover { background: #4a4a4a; }
</style>
</head>
<body>

<div class="topbar">
    <h1>Restoration Pipeline</h1>
    <div class="stepper">
        <div class="step active" id="step1">1. Load &amp; Select</div>
        <div class="step" id="step2">2. Enhance (ESRGAN)</div>
        <div class="step" id="step3">3. Face Enhancement</div>
        <div class="step" id="step4">4. Export</div>
    </div>
</div>

<div class="content">

<!-- Stage 1: Load -->
<div class="panel load-panel active" id="panel1">
    <div class="gallery-scroll" id="galleryScroll">
        <div class="step1-header" id="step1Header">
            <h2 style="margin-bottom: 10px;">Step 1: Load images and select which to enhance</h2>
            <div class="dir-input">
                <input type="text" id="dirInput" value="Z:\Photos\" placeholder="Enter directory path or browse...">
                <button class="btn-secondary btn" onclick="openBrowser()">Browse</button>
                <button class="btn" onclick="scanDirectory()">Scan</button>
            </div>
            <div id="scanError" class="scan-error" style="color:#a55;font-size:13px;margin-top:8px;"></div>
            <div class="step1-collapsed-path">
                <button class="folder-icon-btn" onclick="expandSearch()" title="Change folder">&#128193;</button>
                <span class="path-text" id="collapsedPath"></span>
            </div>
        </div>
        <div class="sticky-toolbar" id="selectionBar" style="display:none;">
            <button class="btn-secondary btn" onclick="selectAll()">Select All</button>
            <button class="btn-secondary btn" onclick="selectNone()">Select None</button>
            <span class="selection-info" id="selectionInfo">0 selected</span>
            <div class="size-control">
                <span>Size</span>
                <input type="range" id="thumbSizeSlider" min="60" max="300" value="120" oninput="updateThumbSize()">
            </div>
            <button class="btn" onclick="startESRGAN()" id="esrganBtn" disabled>Enhance Selected &rarr;</button>
        </div>
        <div class="image-grid" id="imageGrid"></div>
    </div>
</div>

<!-- Stage 2: ESRGAN -->
<div class="panel process-panel" id="panel2">
    <div class="esrgan-progress-view" id="esrganProgressView">
        <div class="esrgan-progress-sidebar" id="esrganProgressSidebar"></div>
        <div class="esrgan-progress-center" id="esrganProgressCenter">
            <h2>Step 2: Enhancing full images with Real-ESRGAN</h2>
            <div class="progress-container">
                <div class="progress-bar"><div class="progress-fill" id="esrganProgress" style="width:0%"></div></div>
                <div class="progress-text" id="esrganProgressText">Waiting...</div>
                <div class="progress-image" id="esrganProgressImage"></div>
                <div class="progress-errors" id="esrganErrors"></div>
                <div class="progress-log" id="esrganLog"></div>
            </div>
            <div id="esrganDoneWrap" style="display:none; flex-direction: column; align-items: center; gap: 12px; margin-top: 20px;">
                <div id="esrganDoneMsg" style="font-size: 16px; color: #8c8;"></div>
                <button class="btn" id="esrganDoneBtn" onclick="showEsrganCompare()">Review Enhanced Images &rarr;</button>
            </div>
        </div>
    </div>
    <div class="esrgan-compare" id="esrganCompareView" style="display:none;">
        <div class="esrgan-compare-sidebar" id="esrganCompareSidebar">
            <div class="face-sidebar-thumbs" id="esrganCompareThumbs"></div>
            <div class="face-sidebar-nav">
                <button onclick="esrganCompareNav(-1)" id="esrganPrevBtn">&#9664; Prev</button>
                <button onclick="esrganCompareNav(1)" id="esrganNextBtn">Next &#9654;</button>
            </div>
        </div>
        <div class="gallery-resizer" id="esrganGalleryResizer"></div>
        <div class="esrgan-compare-main">
            <div class="esrgan-compare-toolbar">
                <div class="toggle-btns">
                    <button class="toggle-btn active" id="esrganSideBtn" onclick="setEsrganView('side')">Side-by-side</button>
                    <button class="toggle-btn" id="esrganSwipeBtn" onclick="setEsrganView('swipe')">Swipe</button>
                </div>
                <div style="flex:1;"></div>
                <button class="btn" onclick="goToFaceEnhance()">Continue to Face Enhancement &rarr;</button>
            </div>
            <div class="esrgan-compare-body">
                <div class="esrgan-compare-canvas" id="esrganCompareMain"></div>
            </div>
        </div>
    </div>
</div>

<!-- Stage 3: Face Enhancement -->
<div class="panel face-panel" id="panel3">
    <!-- Pre-processing: auto-runs face enhancement, shows progress -->
    <div class="face-pre" id="facePre">
        <div class="esrgan-progress-sidebar" id="faceProgressSidebar"></div>
        <div class="esrgan-progress-center">
            <h2>Step 3: Face Enhancement</h2>
            <p style="color:#888;margin-top:8px;text-align:center;">Running face enhancement models on enhanced images...</p>
            <div id="faceProgressContainer" style="margin-top: 20px; width: 100%; max-width: 500px;">
                <div class="progress-container" style="margin: 0 auto;">
                    <div class="progress-bar"><div class="progress-fill" id="faceProgress" style="width:0%"></div></div>
                    <div class="progress-text" id="faceProgressText">Starting...</div>
                    <div class="progress-image" id="faceProgressImage"></div>
                    <div class="progress-errors" id="faceErrors"></div>
                    <div class="progress-log" id="faceLog"></div>
                </div>
            </div>
        </div>
    </div>
    <!-- Post-processing: comparison UI -->
    <div id="faceCompareView" style="display:none; flex: 1; flex-direction: row; overflow: hidden;">
        <!-- Left: thumbnail sidebar with nav at bottom -->
        <div class="face-sidebar" id="faceSidebar">
            <div class="face-sidebar-thumbs" id="faceSidebarThumbs"></div>
            <div class="face-sidebar-nav">
                <button onclick="faceNav(-1)" id="facePrevBtn">&#9664; Prev</button>
                <button onclick="faceNav(1)" id="faceNextBtn">Next &#9654;</button>
            </div>
        </div>
        <div class="gallery-resizer" id="faceGalleryResizer"></div>
        <!-- Right: main comparison area -->
        <div class="face-main">
            <div class="face-toolbar">
                <div class="toggle-btns">
                    <button class="toggle-btn active" id="sideBtn" onclick="setView('side')">Side-by-side</button>
                    <button class="toggle-btn" id="swipeBtn" onclick="setView('swipe')">Swipe</button>
                </div>
                <div style="flex:1;"></div>
                <button class="btn" onclick="goToExport()">Export &rarr;</button>
            </div>
            <div class="face-body">
                <div class="face-canvas-area" id="faceContent"></div>
                <div class="faces-sidebar" id="facesSidebar">
                    <div class="faces-sidebar-header">
                        <button class="expand-btn" onclick="toggleFacesOverlay()">&#x2922; Expand</button>
                    </div>
                    <div id="facesContent"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- Floating dock for model selection -->
    <div class="floating-dock" id="floatingDock" style="display:none;">
        <div class="dock-title">Choose model to keep</div>
        <div class="dock-row" id="dockButtons"></div>
    </div>
</div>

<!-- Stage 4: Export -->
<div class="panel export-panel" id="panel4">
    <h2 style="margin-bottom: 10px;">Step 4: Export chosen results</h2>
    <div style="margin-bottom: 16px;">
        <button class="btn-secondary btn" onclick="goBackToFaceCompare()">&larr; Back to Face Comparison</button>
    </div>
    <div class="export-summary" id="exportSummary"></div>
    <div class="dir-input" style="margin-top: 20px;">
        <input type="text" id="exportDir" placeholder="Output directory path">
        <button class="btn-secondary btn" onclick="openBrowserForExport()">Browse</button>
        <button class="btn" onclick="doExport()">Export</button>
    </div>
    <div id="exportResult" style="margin-top: 16px;"></div>
</div>

</div>

<!-- Directory browser modal -->
<div class="modal-overlay" id="dirBrowser" style="display:none;">
    <div class="modal">
        <div class="modal-header">
            <h3>Browse Directory</h3>
            <button class="viewer-close" onclick="closeBrowser()">Cancel</button>
        </div>
        <div class="modal-body">
            <div class="modal-path" id="browserPath"></div>
            <ul class="dir-list" id="dirList"></ul>
        </div>
        <div class="modal-footer">
            <button class="btn-secondary btn" onclick="browserUp()">Up one level</button>
            <button class="btn" onclick="browserSelect()">Select this directory</button>
        </div>
    </div>
</div>

<!-- Full-screen image viewer -->
<div class="viewer-overlay" id="viewer" style="display:none;">
    <div class="viewer-header">
        <span class="filename" id="viewerFilename"></span>
        <span class="counter" id="viewerCounter"></span>
        <button class="viewer-close" onclick="closeViewer()">Close (Esc)</button>
    </div>
    <div class="viewer-body">
        <button class="viewer-nav prev" id="viewerPrev" onclick="viewerNav(-1)">&larr;</button>
        <img id="viewerImg" src="">
        <button class="viewer-nav next" id="viewerNext" onclick="viewerNav(1)">&rarr;</button>
    </div>
    <div class="viewer-footer">
        <button class="viewer-select-btn" id="viewerSelectBtn" onclick="viewerToggleSelect()">Select</button>
    </div>
</div>

<script>
let appState = { stage: 'load', images: [], selected: new Set(), choices: {}, faceModels: [], esrganOutputs: {}, faceOutputs: {} };
let currentFaceIdx = 0;
let faceImageList = [];
let progressPoll = null;

function showPanel(n) {
    document.querySelectorAll('.panel').forEach((p, i) => p.classList.toggle('active', i === n - 1));
    document.querySelectorAll('.step').forEach((s, i) => {
        s.classList.toggle('active', i === n - 1);
        if (i < n - 1) s.classList.add('done');
        else s.classList.remove('done');
    });
}

// --- Stage 1: Load ---
async function scanDirectory() {
    const dir = document.getElementById('dirInput').value.trim();
    if (!dir) return;
    document.getElementById('scanError').textContent = '';
    const res = await fetch('/api/scan', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({directory: dir})
    });
    const data = await res.json();
    if (data.error) {
        document.getElementById('scanError').textContent = data.error;
        return;
    }
    appState.images = data.images;
    appState.selected = new Set();
    // Collapse search bar after scan
    document.getElementById('step1Header').classList.add('collapsed');
    document.getElementById('collapsedPath').textContent = dir + ' (' + appState.images.length + ' images)';
    document.getElementById('selectionBar').style.display = 'flex';
    renderImageGrid();
}

function expandSearch() {
    document.getElementById('step1Header').classList.remove('collapsed');
}

let thumbSize = 120;
function updateThumbSize() {
    thumbSize = parseInt(document.getElementById('thumbSizeSlider').value);
    renderImageGrid();
}

// --- Directory browser ---
let browserCurrent = '';
let exportBrowserMode = false;

async function openBrowser() {
    document.getElementById('dirBrowser').style.display = 'flex';
    await browseTo('');
}

async function browseTo(dir) {
    const url = '/api/browse?dir=' + encodeURIComponent(dir);
    const res = await fetch(url);
    const data = await res.json();
    if (data.error) { alert(data.error); return; }

    browserCurrent = data.current || '';
    document.getElementById('browserPath').textContent = browserCurrent || 'My Computer';

    const list = document.getElementById('dirList');
    list.innerHTML = '';

    if (data.drives) {
        data.dirs.forEach(drive => {
            const li = document.createElement('li');
            li.className = 'dir-list-item';
            li.innerHTML = '<span class="dir-list-icon">&#128187;</span> ' + drive;
            li.onclick = () => browseTo(drive);
            list.appendChild(li);
        });
    } else {
        if (data.parent !== null) {
            const li = document.createElement('li');
            li.className = 'dir-list-item up';
            li.innerHTML = '<span class="dir-list-icon">&#8593;</span> ..';
            li.onclick = () => browseTo(data.parent);
            list.appendChild(li);
        }
        data.dirs.forEach(d => {
            const li = document.createElement('li');
            li.className = 'dir-list-item';
            li.innerHTML = '<span class="dir-list-icon">&#128193;</span> ' + d;
            li.onclick = () => browseTo(browserCurrent + (browserCurrent.endsWith('\\') ? '' : '\\') + d);
            list.appendChild(li);
        });
    }
}

function browserUp() {
    // Trigger the ".." item or go to drives
    const upItem = document.querySelector('.dir-list-item.up');
    if (upItem) upItem.click();
    else browseTo('');
}

function browserSelect() {
    if (browserCurrent) {
        if (exportBrowserMode) {
            document.getElementById('exportDir').value = browserCurrent;
            exportBrowserMode = false;
        } else {
            document.getElementById('dirInput').value = browserCurrent;
            scanDirectory();
        }
        closeBrowser();
    }
}

function closeBrowser() {
    document.getElementById('dirBrowser').style.display = 'none';
}

// --- Full-screen image viewer ---
let viewerIdx = 0;

function openViewer(idx) {
    viewerIdx = idx;
    document.getElementById('viewer').style.display = 'flex';
    renderViewer();
}

function closeViewer() {
    document.getElementById('viewer').style.display = 'none';
}

function renderViewer() {
    const img = appState.images[viewerIdx];
    if (!img) return;
    document.getElementById('viewerImg').src = '/thumb/' + encodeURIComponent(img.name);
    document.getElementById('viewerFilename').textContent = img.name;
    document.getElementById('viewerCounter').textContent = (viewerIdx + 1) + ' / ' + appState.images.length;
    document.getElementById('viewerPrev').disabled = viewerIdx === 0;
    document.getElementById('viewerNext').disabled = viewerIdx === appState.images.length - 1;

    const btn = document.getElementById('viewerSelectBtn');
    const isSelected = appState.selected.has(img.name);
    btn.classList.toggle('selected', isSelected);
    btn.textContent = isSelected ? '✓ Selected' : 'Select';
}

function viewerNav(dir) {
    const newIdx = viewerIdx + dir;
    if (newIdx >= 0 && newIdx < appState.images.length) {
        viewerIdx = newIdx;
        renderViewer();
    }
}

function viewerToggleSelect() {
    const img = appState.images[viewerIdx];
    if (!img) return;
    toggleSelect(img.name);
    renderViewer();
}

// Lazy loading: only render cards near the viewport
let imageGridObserver = null;
let lastClickedIdx = -1;

function renderImageGrid() {
    const grid = document.getElementById('imageGrid');
    // Set dynamic column size based on slider
    grid.style.gridTemplateColumns = `repeat(auto-fill, minmax(${thumbSize}px, 1fr))`;

    const total = appState.images.length;
    grid.innerHTML = '';

    function createCard(img, idx) {
        const card = document.createElement('div');
        card.className = 'image-card' + (appState.selected.has(img.name) ? ' selected' : '');
        card.dataset.idx = idx;
        card.dataset.name = img.name;
        const checkbox = document.createElement('div');
        checkbox.className = 'card-checkbox';
        checkbox.innerHTML = appState.selected.has(img.name) ? '&#10003;' : '';
        checkbox.onclick = (e) => {
            e.stopPropagation();
            if (e.shiftKey && lastClickedIdx >= 0) {
                // Range select
                const start = Math.min(lastClickedIdx, idx);
                const end = Math.max(lastClickedIdx, idx);
                for (let i = start; i <= end; i++) {
                    appState.selected.add(appState.images[i].name);
                }
                renderImageGrid();
            } else {
                toggleSelect(img.name);
                lastClickedIdx = idx;
            }
        };
        card.appendChild(checkbox);
        const imgEl = document.createElement('img');
        imgEl.src = '/thumb/' + encodeURIComponent(img.name);
        imgEl.loading = 'lazy';
        imgEl.onclick = () => openViewer(idx);
        card.appendChild(imgEl);
        const nameOverlay = document.createElement('div');
        nameOverlay.className = 'name-overlay';
        nameOverlay.textContent = img.name;
        card.appendChild(nameOverlay);
        return card;
    }

    if (total > 500) {
        // Virtual: create placeholder cards, load images on scroll into view
        appState.images.forEach((img, idx) => {
            const card = document.createElement('div');
            card.className = 'image-card' + (appState.selected.has(img.name) ? ' selected' : '');
            card.dataset.idx = idx;
            card.dataset.name = img.name;
            const checkbox = document.createElement('div');
            checkbox.className = 'card-checkbox';
            checkbox.innerHTML = appState.selected.has(img.name) ? '&#10003;' : '';
            checkbox.onclick = (e) => {
                e.stopPropagation();
                if (e.shiftKey && lastClickedIdx >= 0) {
                    const start = Math.min(lastClickedIdx, idx);
                    const end = Math.max(lastClickedIdx, idx);
                    for (let i = start; i <= end; i++) {
                        appState.selected.add(appState.images[i].name);
                    }
                    renderImageGrid();
                } else {
                    toggleSelect(img.name);
                    lastClickedIdx = idx;
                }
            };
            card.appendChild(checkbox);
            const nameOverlay = document.createElement('div');
            nameOverlay.className = 'name-overlay';
            nameOverlay.textContent = img.name;
            card.appendChild(nameOverlay);
            card.onclick = (e) => {
                if (e.target === checkbox || checkbox.contains(e.target)) return;
                openViewer(idx);
            };
            grid.appendChild(card);
        });

        // Observe cards and load images when visible
        if (imageGridObserver) imageGridObserver.disconnect();
        imageGridObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const card = entry.target;
                    if (!card.querySelector('img')) {
                        const name = card.dataset.name;
                        const img = document.createElement('img');
                        img.src = '/thumb/' + encodeURIComponent(name);
                        img.loading = 'lazy';
                        img.onclick = () => openViewer(parseInt(card.dataset.idx));
                        // Insert after checkbox
                        card.insertBefore(img, card.children[1]);
                    }
                }
            });
        }, { rootMargin: '200px' });
        grid.querySelectorAll('.image-card').forEach(c => imageGridObserver.observe(c));
    } else {
        // Small gallery: render all with native lazy loading
        appState.images.forEach((img, idx) => {
            grid.appendChild(createCard(img, idx));
        });
    }
    updateSelectionInfo();
}

function toggleSelect(name) {
    if (appState.selected.has(name)) appState.selected.delete(name);
    else appState.selected.add(name);
    // Update just the affected card(s) for performance
    const cards = document.querySelectorAll(`.image-card[data-name="${name}"]`);
    cards.forEach(card => {
        const isSelected = appState.selected.has(name);
        card.classList.toggle('selected', isSelected);
        const cb = card.querySelector('.card-checkbox');
        if (cb) cb.innerHTML = isSelected ? '&#10003;' : '';
    });
    updateSelectionInfo();
}

function selectAll() {
    appState.images.forEach(img => appState.selected.add(img.name));
    renderImageGrid();
}

function selectNone() {
    appState.selected.clear();
    renderImageGrid();
}

function updateSelectionInfo() {
    const n = appState.selected.size;
    document.getElementById('selectionInfo').textContent = n + ' selected';
    document.getElementById('esrganBtn').disabled = n === 0;
}

// --- Stage 2: ESRGAN ---
// Render ESRGAN progress sidebar filmstrip
let esrganProgressCompleted = new Set();
let esrganProgressCurrent = '';

function renderEsrganProgressSidebar(prog) {
    const sidebar = document.getElementById('esrganProgressSidebar');
    if (!sidebar) return;

    // Track completed images
    if (prog.current_image && prog.current_image !== esrganProgressCurrent) {
        if (esrganProgressCurrent) esrganProgressCompleted.add(esrganProgressCurrent);
        esrganProgressCurrent = prog.current_image;
    }

    // Build from selected images
    const images = appState.images.filter(img => appState.selected.has(img.name));
    if (images.length === 0) return;

    let html = '';
    images.forEach(img => {
        const name = img.name;
        const isProcessing = prog.current_image && (prog.current_image.includes(name.replace(/\.[^.]+$/, '')) || name.includes(prog.current_image.replace(/\.[^.]+$/, '')));
        const isDone = esrganProgressCompleted.has(name) || (prog.current > 0 && !isProcessing && esrganProgressCompleted.size >= prog.current);

        let cls = 'face-sidebar-thumb';
        let overlay = '';
        if (isDone) {
            cls += ' done';
            overlay = '<div class="status-icon checkmark">&#10003;</div>';
        } else if (isProcessing) {
            cls += ' processing';
            overlay = '<div class="status-spinner"></div>';
        } else {
            overlay = '<div class="status-pending"></div>';
        }

        html += `<div class="${cls}"><img src="/thumb/${encodeURIComponent(name)}" loading="lazy">${overlay}</div>`;
    });
    sidebar.innerHTML = html;
}

async function startESRGAN() {
    esrganProgressCompleted = new Set();
    esrganProgressCurrent = '';
    const selected = Array.from(appState.selected);
    const res = await fetch('/api/esrgan', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({selected})
    });
    const data = await res.json();
    if (data.error) { alert(data.error); return; }
    showPanel(2);
    startProgressPoll('esrgan');
}

function startProgressPoll(stage) {
    if (progressPoll) clearInterval(progressPoll);
    progressPoll = setInterval(() => pollProgress(stage), 500);
}

function renderLog(elemId, logLines) {
    const elem = document.getElementById(elemId);
    if (!elem) return;
    const wasAtBottom = elem.scrollTop + elem.clientHeight >= elem.scrollHeight - 5;
    elem.innerHTML = logLines.map(line => {
        const cls = (line.includes('ERROR') || line.includes('EXCEPTION')) ? 'log-line log-error' : 'log-line';
        return `<div class="${cls}">${line.replace(/</g, '&lt;')}</div>`;
    }).join('');
    if (wasAtBottom) elem.scrollTop = elem.scrollHeight;
}

async function pollProgress(stage) {
    const res = await fetch('/api/progress');
    const prog = await res.json();

    if (stage === 'esrgan') {
        const pct = prog.total > 0 ? (prog.current / prog.total * 100) : 0;
        document.getElementById('esrganProgress').style.width = pct + '%';
        document.getElementById('esrganProgressText').textContent = prog.current + ' / ' + prog.total + (prog.status !== 'idle' ? ' — ' + prog.status : '');
        document.getElementById('esrganProgressImage').textContent = prog.current_image ? 'Processing: ' + prog.current_image : '';
        document.getElementById('esrganErrors').textContent = prog.errors.join('; ');
        renderLog('esrganLog', prog.log || []);
        renderEsrganProgressSidebar(prog);
        if (!prog.busy && prog.status === 'done') {
            clearInterval(progressPoll); progressPoll = null;
            document.getElementById('esrganDoneMsg').textContent = 'Complete! ' + prog.current + ' images enhanced.';
            document.getElementById('esrganDoneWrap').style.display = 'flex';
        } else if (!prog.busy && prog.status === 'error') {
            clearInterval(progressPoll); progressPoll = null;
            document.getElementById('esrganDoneMsg').textContent = 'Completed with errors — see log below.';
            document.getElementById('esrganDoneWrap').style.display = 'flex';
        }
    } else if (stage === 'face') {
        const pct = prog.total > 0 ? (prog.current / prog.total * 100) : 0;
        document.getElementById('faceProgress').style.width = pct + '%';
        document.getElementById('faceProgressText').textContent = prog.stage + ': ' + prog.current + ' / ' + prog.total + ' — ' + prog.status;
        document.getElementById('faceProgressImage').textContent = prog.current_image ? 'Processing: ' + prog.current_image : '';
        document.getElementById('faceErrors').textContent = prog.errors.join('; ');
        renderLog('faceLog', prog.log || []);
        renderFaceProgressGrid(prog);
        if (!prog.busy && prog.status === 'done') {
            clearInterval(progressPoll); progressPoll = null;
            document.getElementById('faceProgressText').textContent = 'All face models complete!';
            loadFaceCompare();
        } else if (!prog.busy && prog.status === 'error') {
            clearInterval(progressPoll); progressPoll = null;
            document.getElementById('faceProgressText').textContent = 'Completed with errors — see log below.';
            loadFaceCompare();
        }
    }
}

function goToFaceEnhance() {
    showPanel(3);
    loadEsrganThumbnails();
    // Auto-start face enhancement
    startFaceEnhance();
}

// --- Step 2: ESRGAN comparison view ---
let esrganCompareList = [];
let esrganCompareIdx = 0;
let esrganCompareView = 'side';
let ecZoom = 1, ecPanX = 0, ecPanY = 0, ecSwipePos = 50;
let ecIsPanning = false, ecPanStartX = 0, ecPanStartY = 0, ecPanStartPanX = 0, ecPanStartPanY = 0;
let ecIsSwiping = false;

async function showEsrganCompare() {
    const res = await fetch('/api/state');
    const s = await res.json();
    appState.esrganOutputs = s.esrgan_outputs || {};
    appState.originalOutputs = s.original_outputs || {};

    document.getElementById('esrganProgressView').style.display = 'none';
    document.getElementById('esrganCompareView').style.display = 'flex';

    esrganCompareList = Object.keys(appState.esrganOutputs).sort();
    esrganCompareIdx = 0;
    ecZoom = 1; ecPanX = 0; ecPanY = 0; ecSwipePos = 50;
    esrganCompareView = 'side';
    renderEsrganCompareSidebar();
    renderEsrganCompare();
    initEsrganGalleryResizer();
}

function initEsrganGalleryResizer() {
    const resizer = document.getElementById('esrganGalleryResizer');
    if (!resizer || resizer._init) return;
    resizer._init = true;
    const gallery = document.getElementById('esrganCompareSidebar');
    let resizing = false, startX = 0, startW = 0;
    resizer.addEventListener('mousedown', (e) => {
        resizing = true; startX = e.clientX; startW = gallery.offsetWidth;
        document.body.style.cursor = 'ew-resize';
        e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
        if (!resizing) return;
        const newW = Math.max(80, Math.min(400, startW + e.clientX - startX));
        gallery.style.width = newW + 'px';
    });
    document.addEventListener('mouseup', () => {
        if (resizing) { resizing = false; document.body.style.cursor = ''; }
    });
}

function setEsrganView(v) {
    esrganCompareView = v;
    document.getElementById('esrganSideBtn').classList.toggle('active', v === 'side');
    document.getElementById('esrganSwipeBtn').classList.toggle('active', v === 'swipe');
    ecZoom = 1; ecPanX = 0; ecPanY = 0;
    renderEsrganCompare();
}

function renderEsrganCompareSidebar() {
    const sidebar = document.getElementById('esrganCompareThumbs');
    sidebar.innerHTML = '';
    esrganCompareList.forEach((basename, idx) => {
        const div = document.createElement('div');
        div.className = 'face-sidebar-thumb' + (idx === esrganCompareIdx ? ' active' : '');
        div.onclick = () => { esrganCompareIdx = idx; ecZoom = 1; ecPanX = 0; ecPanY = 0; renderEsrganCompareSidebar(); renderEsrganCompare(); };
        div.innerHTML = `<img src="/files/${appState.esrganOutputs[basename]}" loading="lazy">`;
        sidebar.appendChild(div);
    });
}

function esrganCompareNav(dir) {
    const newIdx = esrganCompareIdx + dir;
    if (newIdx >= 0 && newIdx < esrganCompareList.length) {
        esrganCompareIdx = newIdx;
        ecZoom = 1; ecPanX = 0; ecPanY = 0;
        renderEsrganCompareSidebar();
        renderEsrganCompare();
        const activeItem = document.querySelectorAll('#esrganCompareThumbs .face-sidebar-thumb')[esrganCompareIdx];
        if (activeItem) activeItem.scrollIntoView({ block: 'nearest' });
    }
}

function renderEsrganCompare() {
    if (esrganCompareList.length === 0) return;
    const basename = esrganCompareList[esrganCompareIdx];
    document.querySelectorAll('#esrganCompareThumbs .face-sidebar-thumb').forEach((el, idx) => el.classList.toggle('active', idx === esrganCompareIdx));
    document.getElementById('esrganPrevBtn').disabled = esrganCompareIdx === 0;
    document.getElementById('esrganNextBtn').disabled = esrganCompareIdx === esrganCompareList.length - 1;

    const origUrl = appState.originalOutputs[basename] ? '/files/' + appState.originalOutputs[basename] : null;
    const enhUrl = '/files/' + appState.esrganOutputs[basename];
    const main = document.getElementById('esrganCompareMain');

    if (!origUrl) {
        main.innerHTML = '<div style="color:#888;padding:40px;text-align:center;">Original not available</div>';
        return;
    }

    if (esrganCompareView === 'side') {
        main.innerHTML = '<div class="side-by-side">' +
            '<div class="side-panel"><div class="model-bar"><span class="model-toggle active">Original</span></div>' +
            '<canvas id="ecCanvasL"></canvas></div>' +
            '<div class="side-panel"><div class="model-bar"><span class="model-toggle active">Enhanced</span></div>' +
            '<canvas id="ecCanvasR"></canvas></div>' +
            '</div><div class="zoom-info" id="ecZoomInfo">' + Math.round(ecZoom * 100) + '%</div>';
        drawEsrganSideBySide(origUrl, enhUrl);
    } else {
        main.innerHTML = '<div class="swipe-container">' +
            '<div class="swipe-bars"><div class="model-bar"><span class="model-toggle active">Original</span></div><div class="model-bar"><span class="model-toggle active">Enhanced</span></div></div>' +
            '<div class="swipe-img-area"><div class="swipe-wrap" id="ecSwipeWrap">' +
            '<canvas id="ecSwipeCanvas"></canvas>' +
            '<div class="swipe-divider" id="ecSwipeDivider" style="left:' + ecSwipePos + '%"></div>' +
            '<div class="swipe-label swipe-label-left">Original</div>' +
            '<div class="swipe-label swipe-label-right">Enhanced</div>' +
            '</div></div></div>' +
            '<div class="zoom-info" id="ecZoomInfo">' + Math.round(ecZoom * 100) + '%</div>';
        drawEsrganSwipe(origUrl, enhUrl);
    }
}

function drawEsrganSideBySide(leftSrc, rightSrc) {
    const main = document.getElementById('esrganCompareMain');
    const canvasL = document.getElementById('ecCanvasL');
    const canvasR = document.getElementById('ecCanvasR');
    const ctxL = canvasL.getContext('2d');
    const ctxR = canvasR.getContext('2d');
    const imgL = new Image(), imgR = new Image();
    let lLoaded = false, rLoaded = false, baseW = 0, baseH = 0;

    function tryDraw() {
        if (!lLoaded || !rLoaded) return;
        const maxW = (main.clientWidth - 20) / 2;
        const maxH = main.clientHeight - 40;
        const lW = imgL.naturalWidth || 1, lH = imgL.naturalHeight || 1;
        const rW = imgR.naturalWidth || 1, rH = imgR.naturalHeight || 1;
        const ar = Math.max(lW / lH, rW / rH);
        let w = maxW, h = w / ar;
        if (h > maxH) { h = maxH; w = h * ar; }
        baseW = Math.round(w); baseH = Math.round(h);
        canvasL.width = baseW; canvasL.height = baseH;
        canvasR.width = baseW; canvasR.height = baseH;
        draw();
    }

    function draw() {
        ctxL.clearRect(0, 0, baseW, baseH); ctxL.fillStyle = '#111'; ctxL.fillRect(0, 0, baseW, baseH);
        drawZoomed(ctxL, imgL, baseW, baseH, ecZoom, ecPanX, ecPanY);
        ctxR.clearRect(0, 0, baseW, baseH); ctxR.fillStyle = '#111'; ctxR.fillRect(0, 0, baseW, baseH);
        drawZoomed(ctxR, imgR, baseW, baseH, ecZoom, ecPanX, ecPanY);
        document.getElementById('ecZoomInfo').textContent = Math.round(ecZoom * 100) + '%';
    }

    imgL.onload = () => { lLoaded = true; tryDraw(); };
    imgR.onload = () => { rLoaded = true; tryDraw(); };
    imgL.onerror = () => { console.error('Failed to load left image:', leftSrc); lLoaded = true; tryDraw(); };
    imgR.onerror = () => { console.error('Failed to load right image:', rightSrc); rLoaded = true; tryDraw(); };
    imgL.src = leftSrc; imgR.src = rightSrc;

    [canvasL, canvasR].forEach(c => {
        c.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY > 0 ? 0.9 : 1.1;
            const newZoom = Math.max(0.5, Math.min(10, ecZoom * delta));
            const rect = c.getBoundingClientRect();
            const mx = e.clientX - rect.left, my = e.clientY - rect.top;
            ecPanX = mx - (mx - ecPanX) * (newZoom / ecZoom);
            ecPanY = my - (my - ecPanY) * (newZoom / ecZoom);
            ecZoom = newZoom; draw();
        });
        c.addEventListener('mousedown', (e) => {
            ecIsPanning = true; ecPanStartX = e.clientX; ecPanStartY = e.clientY;
            ecPanStartPanX = ecPanX; ecPanStartPanY = ecPanY; e.preventDefault();
        });
    });
    document.addEventListener('mousemove', ecMouseMoveHandler);
    document.addEventListener('mouseup', ecMouseUpHandler);
    window.addEventListener('resize', tryDraw);
    main._tryDraw = tryDraw;
}

function drawEsrganSwipe(leftSrc, rightSrc) {
    const main = document.getElementById('esrganCompareMain');
    const canvas = document.getElementById('ecSwipeCanvas');
    const ctx = canvas.getContext('2d');
    const wrap = document.getElementById('ecSwipeWrap');
    const divider = document.getElementById('ecSwipeDivider');
    const leftImg = new Image(), rightImg = new Image();
    let lLoaded = false, rLoaded = false, drawW = 0, drawH = 0;

    function tryDraw() {
        if (!lLoaded || !rLoaded) return;
        const maxW = main.clientWidth - 40;
        const maxH = main.clientHeight - 60;
        const ar = Math.max(leftImg.naturalWidth / leftImg.naturalHeight, rightImg.naturalWidth / rightImg.naturalHeight);
        let w = maxW, h = w / ar;
        if (h > maxH) { h = maxH; w = h * ar; }
        drawW = Math.round(w); drawH = Math.round(h);
        canvas.width = drawW; canvas.height = drawH;
        wrap.style.width = drawW + 'px'; wrap.style.height = drawH + 'px';
        doDraw();
    }

    function doDraw() {
        ctx.clearRect(0, 0, drawW, drawH); ctx.fillStyle = '#111'; ctx.fillRect(0, 0, drawW, drawH);
        drawZoomedFill(ctx, rightImg, drawW, drawH, ecZoom, ecPanX, ecPanY);
        const splitX = Math.round(drawW * ecSwipePos / 100);
        if (splitX > 0) {
            ctx.save(); ctx.beginPath(); ctx.rect(0, 0, splitX, drawH); ctx.clip();
            drawZoomedFill(ctx, leftImg, drawW, drawH, ecZoom, ecPanX, ecPanY);
            ctx.restore();
        }
        divider.style.left = ecSwipePos + '%';
        document.getElementById('ecZoomInfo').textContent = Math.round(ecZoom * 100) + '%';
    }

    leftImg.onload = () => { lLoaded = true; tryDraw(); };
    rightImg.onload = () => { rLoaded = true; tryDraw(); };
    leftImg.src = leftSrc; rightImg.src = rightSrc;

    canvas.addEventListener('mousedown', (e) => {
        ecIsPanning = true; ecPanStartX = e.clientX; ecPanStartY = e.clientY;
        ecPanStartPanX = ecPanX; ecPanStartPanY = ecPanY; e.preventDefault();
    });
    divider.addEventListener('mousedown', (e) => { ecIsSwiping = true; e.preventDefault(); e.stopPropagation(); });
    document.addEventListener('mousemove', ecMouseMoveHandler);
    document.addEventListener('mouseup', ecMouseUpHandler);
    canvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newZoom = Math.max(0.5, Math.min(10, ecZoom * delta));
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left, my = e.clientY - rect.top;
        ecPanX = mx - (mx - ecPanX) * (newZoom / ecZoom);
        ecPanY = my - (my - ecPanY) * (newZoom / ecZoom);
        ecZoom = newZoom; doDraw();
    });
    window.addEventListener('resize', tryDraw);
    main._tryDraw = tryDraw;
}

function ecMouseMoveHandler(e) {
    if (ecIsPanning) {
        ecPanX = ecPanStartPanX + (e.clientX - ecPanStartX);
        ecPanY = ecPanStartPanY + (e.clientY - ecPanStartY);
        const main = document.getElementById('esrganCompareMain');
        if (main._tryDraw) main._tryDraw();
    } else if (ecIsSwiping) {
        const canvas = document.getElementById('ecSwipeCanvas');
        if (canvas) {
            const rect = canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            ecSwipePos = Math.max(0, Math.min(100, (x / rect.width) * 100));
            const main = document.getElementById('esrganCompareMain');
            if (main._tryDraw) main._tryDraw();
        }
    }
}

function ecMouseUpHandler() { ecIsPanning = false; ecIsSwiping = false; }

async function loadEsrganThumbnails() {
    const res = await fetch('/api/state');
    const s = await res.json();
    appState.esrganOutputs = s.esrgan_outputs || {};
    appState.originalOutputs = s.original_outputs || {};
}

// Track face progress per image
let faceProgressCompleted = new Set();
let faceProgressCurrentImg = '';

function renderFaceProgressGrid(prog) {
    const sidebar = document.getElementById('faceProgressSidebar');
    if (!sidebar) return;

    // Track completed images
    if (prog.current_image && prog.current_image !== faceProgressCurrentImg) {
        if (faceProgressCurrentImg) faceProgressCompleted.add(faceProgressCurrentImg);
        faceProgressCurrentImg = prog.current_image;
    }

    // Count which model we're on from prog.stage (e.g. "face_gfpgan (1/3)")
    const stageMatch = prog.stage && prog.stage.match(/\((\d+)\/(\d+)\)/);
    const modelNum = stageMatch ? parseInt(stageMatch[1]) : 0;
    const modelTotal = stageMatch ? parseInt(stageMatch[2]) : 0;

    // Build from ESRGAN outputs (the images being processed)
    const images = Object.keys(appState.esrganOutputs || {}).sort();
    if (images.length === 0) return;

    let html = '';
    images.forEach(basename => {
        const esrganPath = appState.esrganOutputs[basename];
        const currentImgName = prog.current_image || '';
        const isProcessing = currentImgName.includes(basename) || basename.includes(currentImgName.replace(/\.[^.]+$/, ''));
        const isDone = faceProgressCompleted.has(basename) || (prog.current > 0 && !isProcessing && faceProgressCompleted.size >= prog.current && modelNum === modelTotal);

        let cls = 'face-sidebar-thumb';
        let overlay = '';
        if (isDone) {
            cls += ' done';
            overlay = '<div class="status-icon checkmark">&#10003;</div>';
        } else if (isProcessing) {
            cls += ' processing';
            overlay = '<div class="status-spinner"></div>';
        } else {
            overlay = '<div class="status-pending"></div>';
        }

        html += `<div class="${cls}"><img src="/files/${esrganPath}" loading="lazy">${overlay}</div>`;
    });
    sidebar.innerHTML = html;
}

// --- Stage 3: Face Enhancement ---
async function startFaceEnhance() {
    faceProgressCompleted = new Set();
    faceProgressCurrentImg = '';
    const res = await fetch('/api/face-enhance', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({})
    });
    const data = await res.json();
    if (data.error) { alert(data.error); return; }
    startProgressPoll('face');
}

async function loadFaceCompare() {
    const res = await fetch('/api/state');
    const s = await res.json();
    appState.esrganOutputs = s.esrgan_outputs || {};
    appState.faceOutputs = s.face_outputs || {};
    appState.faceModels = s.face_models || [];
    appState.choices = s.choices || {};
    appState.originalOutputs = s.original_outputs || {};
    appState.croppedFaces = s.cropped_faces || {};
    appState.restoredFaces = s.restored_faces || {};

    faceImageList = Object.keys(appState.esrganOutputs).sort();
    currentFaceIdx = 0;
    fcZoom = 1; fcPanX = 0; fcPanY = 0; fcSwipePos = 50;
    fcView = 'side';
    fcLeftId = 'original'; fcRightId = 'gfpgan';
    fcCurrentFace = 0;

    document.getElementById('facePre').style.display = 'none';
    document.getElementById('faceCompareView').style.display = 'flex';
    document.getElementById('floatingDock').style.display = 'flex';
    renderFaceSidebar();
    renderFaceCompare();
    renderDock();
    renderSidebar();
    initFaceGalleryResizer();
}

function initFaceGalleryResizer() {
    const resizer = document.getElementById('faceGalleryResizer');
    if (!resizer || resizer._init) return;
    resizer._init = true;
    const gallery = document.getElementById('faceSidebar');
    let resizing = false, startX = 0, startW = 0;
    resizer.addEventListener('mousedown', (e) => {
        resizing = true; startX = e.clientX; startW = gallery.offsetWidth;
        document.body.style.cursor = 'ew-resize';
        e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
        if (!resizing) return;
        const newW = Math.max(80, Math.min(400, startW + e.clientX - startX));
        gallery.style.width = newW + 'px';
    });
    document.addEventListener('mouseup', () => {
        if (resizing) { resizing = false; document.body.style.cursor = ''; }
    });
}

// Face compare state
let fcZoom = 1, fcPanX = 0, fcPanY = 0, fcSwipePos = 50;
let fcView = 'side';
let fcLeftId = 'original', fcRightId = 'gfpgan';
let fcIsPanning = false, fcPanStartX = 0, fcPanStartY = 0, fcPanStartPanX = 0, fcPanStartPanY = 0;
let fcIsSwiping = false;
let fcCurrentFace = 0;

// All comparison sources: Original, Enhanced (ESRGAN), face models
function getAllSources() {
    const sources = [
        {id: 'original', short: 'Original', name: 'Original'},
        {id: 'esrgan', short: 'Enhanced', name: 'Enhanced (ESRGAN)'},
    ];
    appState.faceModels.forEach(m => sources.push({id: m.id, short: m.short, name: m.name}));
    return sources;
}

function getSourceShort(id) {
    const s = getAllSources().find(x => x.id === id);
    return s ? s.short : id;
}

function getCompareUrl(basename, sourceId) {
    if (sourceId === 'original') return appState.originalOutputs[basename] ? '/files/' + appState.originalOutputs[basename] : null;
    if (sourceId === 'esrgan') return appState.esrganOutputs[basename] ? '/files/' + appState.esrganOutputs[basename] : null;
    const fo = appState.faceOutputs[sourceId] && appState.faceOutputs[sourceId][basename];
    return fo ? '/files/' + fo : null;
}

function getCroppedFaceUrl(basename, sourceId, faceIdx) {
    if (sourceId === 'original' || sourceId === 'esrgan') return null;
    const faces = appState.croppedFaces[sourceId] && appState.croppedFaces[sourceId][basename];
    if (!faces) return null;
    const face = faces.find(f => f.idx === faceIdx);
    return face ? '/files/' + face.path : null;
}

function getRestoredFaceUrl(basename, sourceId, faceIdx) {
    if (sourceId === 'original' || sourceId === 'esrgan') return null;
    const faces = appState.restoredFaces[sourceId] && appState.restoredFaces[sourceId][basename];
    if (!faces) return null;
    const face = faces.find(f => f.idx === faceIdx);
    return face ? '/files/' + face.path : null;
}

function getMaxFaces(basename) {
    let max = 0;
    getAllSources().forEach(s => {
        if (s.id === 'original' || s.id === 'esrgan') return;
        const faces = appState.croppedFaces[s.id] && appState.croppedFaces[s.id][basename];
        if (faces && faces.length > max) max = faces.length;
    });
    return max;
}

function setView(v) {
    fcView = v;
    document.getElementById('sideBtn').classList.toggle('active', v === 'side');
    document.getElementById('swipeBtn').classList.toggle('active', v === 'swipe');
    fcZoom = 1; fcPanX = 0; fcPanY = 0;
    renderFaceCompare();
}

function selectLeft(id) { fcLeftId = id; renderFaceCompare(); }
function selectRight(id) { fcRightId = id; renderFaceCompare(); }

function buildModelBar(containerId, currentId, onSelect) {
    let html = '<div class="model-bar" id="' + containerId + '">';
    getAllSources().forEach(s => {
        const active = s.id === currentId ? ' active' : '';
        html += '<button class="model-toggle' + active + '" onclick="' + onSelect + '(\'' + s.id + '\')">' + s.short + '</button>';
    });
    html += '</div>';
    return html;
}

function renderFaceSidebar() {
    const sidebar = document.getElementById('faceSidebarThumbs');
    sidebar.innerHTML = '';
    faceImageList.forEach((basename, idx) => {
        const div = document.createElement('div');
        const choice = appState.choices[basename];
        let cls = 'face-sidebar-thumb';
        if (idx === currentFaceIdx) cls += ' active';
        if (choice && choice !== 'none') cls += ' completed';
        div.className = cls;
        div.onclick = () => { currentFaceIdx = idx; fcZoom = 1; fcPanX = 0; fcPanY = 0; fcCurrentFace = 0; renderFaceSidebar(); renderFaceCompare(); renderDock(); renderSidebar(); };
        let badge = '';
        if (choice) {
            if (choice === 'none') { badge = '<div class="choice-badge none">Enh</div>'; }
            else { const m = appState.faceModels.find(fm => fm.id === choice); if (m) badge = `<div class="choice-badge">${m.short}</div>`; }
        }
        let dot = '';
        if (choice && choice !== 'none') dot = '<div class="done-dot"></div>';
        div.innerHTML = `<img src="/files/${appState.esrganOutputs[basename]}" loading="lazy"><div class="thumb-filename">${basename}</div>${badge}${dot}`;
        sidebar.appendChild(div);
    });
}

function renderFaceCompare() {
    if (faceImageList.length === 0) return;
    const basename = faceImageList[currentFaceIdx];
    document.getElementById('facePrevBtn').disabled = currentFaceIdx === 0;
    document.getElementById('faceNextBtn').disabled = currentFaceIdx === faceImageList.length - 1;

    document.querySelectorAll('#faceSidebarThumbs .face-sidebar-thumb').forEach((el, idx) => el.classList.toggle('active', idx === currentFaceIdx));

    if (fcView === 'side') renderSideBySide(basename);
    else renderSwipe(basename);

    renderSidebar();
    renderDock();
}

// --- Canvas drawing helpers ---
function drawZoomed(ctx, img, w, h, z, px, py) {
    const ar = img.naturalWidth / img.naturalHeight;
    let dw = w, dh = w / ar;
    if (dh > h) { dh = h; dw = h * ar; }
    const dx = (w - dw) / 2, dy = (h - dh) / 2;
    const sw = dw * z, sh = dh * z;
    const sx = dx + px - (sw - dw) / 2, sy = dy + py - (sh - dh) / 2;
    ctx.drawImage(img, 0, 0, img.naturalWidth, img.naturalHeight, sx, sy, sw, sh);
}

function drawZoomedFill(ctx, img, w, h, z, px, py) {
    const ar = img.naturalWidth / img.naturalHeight;
    const car = w / h;
    let dw, dh;
    if (ar > car) { dh = h; dw = h * ar; } else { dw = w; dh = w / ar; }
    const dx = (w - dw) / 2, dy = (h - dh) / 2;
    const sw = dw * z, sh = dh * z;
    const sx = dx + px - (sw - dw) / 2, sy = dy + py - (sh - dh) / 2;
    ctx.drawImage(img, 0, 0, img.naturalWidth, img.naturalHeight, sx, sy, sw, sh);
}

function getImageForMode(basename, sourceId, faceIdx) {
    // Always full image mode - faces are shown in the right sidebar
    return getCompareUrl(basename, sourceId);
}

function renderSideBySide(basename) {
    const faceIdx = fcCurrentFace;
    const leftSrc = getImageForMode(basename, fcLeftId, faceIdx);
    const rightSrc = getImageForMode(basename, fcRightId, faceIdx);
    const display = document.getElementById('faceContent');

    if (!leftSrc || !rightSrc) {
        display.innerHTML = '<div style="color:#888;padding:40px;">No image available for ' + getSourceShort(!leftSrc ? fcLeftId : fcRightId) + '</div>';
        return;
    }

    display.innerHTML = '<div class="side-by-side">' +
        '<div class="side-panel">' + buildModelBar('leftBar', fcLeftId, 'selectLeft') +
        '<canvas id="fcCanvasL"></canvas></div>' +
        '<div class="side-panel">' + buildModelBar('rightBar', fcRightId, 'selectRight') +
        '<canvas id="fcCanvasR"></canvas></div>' +
        '</div><div class="zoom-info" id="fcZoomInfo">' + Math.round(fcZoom * 100) + '%</div>';

    const canvasL = document.getElementById('fcCanvasL');
    const canvasR = document.getElementById('fcCanvasR');
    const ctxL = canvasL.getContext('2d');
    const ctxR = canvasR.getContext('2d');
    const imgL = new Image(), imgR = new Image();
    let lLoaded = false, rLoaded = false, baseW = 0, baseH = 0;

    function tryDraw() {
        if (!lLoaded || !rLoaded) return;
        const maxW = (display.clientWidth - 20) / 2;
        const maxH = display.clientHeight - 40;
        const ar = Math.max(imgL.naturalWidth / imgL.naturalHeight, imgR.naturalWidth / imgR.naturalHeight);
        let w = maxW, h = w / ar;
        if (h > maxH) { h = maxH; w = h * ar; }
        baseW = Math.round(w); baseH = Math.round(h);
        canvasL.width = baseW; canvasL.height = baseH;
        canvasR.width = baseW; canvasR.height = baseH;
        draw();
    }

    function draw() {
        ctxL.clearRect(0, 0, baseW, baseH); ctxL.fillStyle = '#111'; ctxL.fillRect(0, 0, baseW, baseH);
        drawZoomed(ctxL, imgL, baseW, baseH, fcZoom, fcPanX, fcPanY);
        ctxR.clearRect(0, 0, baseW, baseH); ctxR.fillStyle = '#111'; ctxR.fillRect(0, 0, baseW, baseH);
        drawZoomed(ctxR, imgR, baseW, baseH, fcZoom, fcPanX, fcPanY);
        document.getElementById('fcZoomInfo').textContent = Math.round(fcZoom * 100) + '%';
    }

    imgL.onload = () => { lLoaded = true; tryDraw(); };
    imgR.onload = () => { rLoaded = true; tryDraw(); };
    imgL.src = leftSrc; imgR.src = rightSrc;

    [canvasL, canvasR].forEach(c => {
        c.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY > 0 ? 0.9 : 1.1;
            const newZoom = Math.max(0.5, Math.min(10, fcZoom * delta));
            const rect = c.getBoundingClientRect();
            const mx = e.clientX - rect.left, my = e.clientY - rect.top;
            fcPanX = mx - (mx - fcPanX) * (newZoom / fcZoom);
            fcPanY = my - (my - fcPanY) * (newZoom / fcZoom);
            fcZoom = newZoom; draw();
        });
        c.addEventListener('mousedown', (e) => {
            fcIsPanning = true; fcPanStartX = e.clientX; fcPanStartY = e.clientY;
            fcPanStartPanX = fcPanX; fcPanStartPanY = fcPanY; e.preventDefault();
        });
    });
    document.addEventListener('mousemove', fcMouseMoveHandler);
    document.addEventListener('mouseup', fcMouseUpHandler);
    window.addEventListener('resize', tryDraw);
    display._tryDraw = tryDraw;
}

function renderSwipe(basename) {
    const faceIdx = fcCurrentFace;
    const leftSrc = getImageForMode(basename, fcLeftId, faceIdx);
    const rightSrc = getImageForMode(basename, fcRightId, faceIdx);
    const display = document.getElementById('faceContent');

    if (!leftSrc || !rightSrc) {
        display.innerHTML = '<div style="color:#888;padding:40px;">No image available</div>';
        return;
    }

    display.innerHTML = '<div class="swipe-container">' +
        '<div class="swipe-bars">' + buildModelBar('leftBar', fcLeftId, 'selectLeft') + buildModelBar('rightBar', fcRightId, 'selectRight') + '</div>' +
        '<div class="swipe-img-area"><div class="swipe-wrap" id="fcSwipeWrap">' +
        '<canvas id="fcSwipeCanvas"></canvas>' +
        '<div class="swipe-divider" id="fcSwipeDivider" style="left:' + fcSwipePos + '%"></div>' +
        '<div class="swipe-label swipe-label-left">' + getSourceShort(fcLeftId) + '</div>' +
        '<div class="swipe-label swipe-label-right">' + getSourceShort(fcRightId) + '</div>' +
        '</div></div></div>' +
        '<div class="zoom-info" id="fcZoomInfo">' + Math.round(fcZoom * 100) + '%</div>';

    const canvas = document.getElementById('fcSwipeCanvas');
    const ctx = canvas.getContext('2d');
    const wrap = document.getElementById('fcSwipeWrap');
    const divider = document.getElementById('fcSwipeDivider');
    const leftImg = new Image(), rightImg = new Image();
    let lLoaded = false, rLoaded = false, drawW = 0, drawH = 0;

    function tryDraw() {
        if (!lLoaded || !rLoaded) return;
        const maxW = display.clientWidth - 40;
        const maxH = display.clientHeight - 60;
        const ar = Math.max(leftImg.naturalWidth / leftImg.naturalHeight, rightImg.naturalWidth / rightImg.naturalHeight);
        let w = maxW, h = w / ar;
        if (h > maxH) { h = maxH; w = h * ar; }
        drawW = Math.round(w); drawH = Math.round(h);
        canvas.width = drawW; canvas.height = drawH;
        wrap.style.width = drawW + 'px'; wrap.style.height = drawH + 'px';
        doDraw();
    }

    function doDraw() {
        ctx.clearRect(0, 0, drawW, drawH); ctx.fillStyle = '#111'; ctx.fillRect(0, 0, drawW, drawH);
        drawZoomedFill(ctx, rightImg, drawW, drawH, fcZoom, fcPanX, fcPanY);
        const splitX = Math.round(drawW * fcSwipePos / 100);
        if (splitX > 0) {
            ctx.save(); ctx.beginPath(); ctx.rect(0, 0, splitX, drawH); ctx.clip();
            drawZoomedFill(ctx, leftImg, drawW, drawH, fcZoom, fcPanX, fcPanY);
            ctx.restore();
        }
        divider.style.left = fcSwipePos + '%';
        document.getElementById('fcZoomInfo').textContent = Math.round(fcZoom * 100) + '%';
    }

    leftImg.onload = () => { lLoaded = true; tryDraw(); };
    rightImg.onload = () => { rLoaded = true; tryDraw(); };
    leftImg.src = leftSrc; rightImg.src = rightSrc;

    canvas.addEventListener('mousedown', (e) => {
        fcIsPanning = true; fcPanStartX = e.clientX; fcPanStartY = e.clientY;
        fcPanStartPanX = fcPanX; fcPanStartPanY = fcPanY; e.preventDefault();
    });
    divider.addEventListener('mousedown', (e) => { fcIsSwiping = true; e.preventDefault(); e.stopPropagation(); });
    document.addEventListener('mousemove', fcMouseMoveHandler);
    document.addEventListener('mouseup', fcMouseUpHandler);
    canvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newZoom = Math.max(0.5, Math.min(10, fcZoom * delta));
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left, my = e.clientY - rect.top;
        fcPanX = mx - (mx - fcPanX) * (newZoom / fcZoom);
        fcPanY = my - (my - fcPanY) * (newZoom / fcZoom);
        fcZoom = newZoom; doDraw();
    });
    window.addEventListener('resize', tryDraw);
    display._tryDraw = tryDraw;
}

function fcMouseMoveHandler(e) {
    if (fcIsPanning) {
        fcPanX = fcPanStartPanX + (e.clientX - fcPanStartX);
        fcPanY = fcPanStartPanY + (e.clientY - fcPanStartY);
        const display = document.getElementById('faceContent');
        if (display._tryDraw) display._tryDraw();
    } else if (fcIsSwiping) {
        const canvas = document.getElementById('fcSwipeCanvas');
        if (canvas) {
            const rect = canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            fcSwipePos = Math.max(0, Math.min(100, (x / rect.width) * 100));
            const display = document.getElementById('faceContent');
            if (display._tryDraw) display._tryDraw();
        }
    }
}

function fcMouseUpHandler() { fcIsPanning = false; fcIsSwiping = false; }

function faceNav(dir) {
    const newIdx = currentFaceIdx + dir;
    if (newIdx >= 0 && newIdx < faceImageList.length) {
        currentFaceIdx = newIdx;
        fcZoom = 1; fcPanX = 0; fcPanY = 0;
        fcCurrentFace = 0;
        renderFaceSidebar();
        renderFaceCompare();
        renderDock();
        // Scroll active thumb into view
        const activeItem = document.querySelectorAll('#faceSidebarThumbs .face-sidebar-thumb')[currentFaceIdx];
        if (activeItem) activeItem.scrollIntoView({ block: 'nearest' });
    }
}

// --- Right sidebar (always visible, shows cropped faces) ---
function renderSidebar() {
    renderSidebarFaces();
}

function renderSidebarFaces() {
    const basename = faceImageList[currentFaceIdx];
    if (!basename) return;
    const content = document.getElementById('facesContent');

    const maxFaces = getMaxFaces(basename);
    if (maxFaces === 0) {
        content.innerHTML = '<div style="color:#555;font-size:12px;">No faces detected</div>';
        return;
    }

    let html = '';
    for (let faceIdx = 0; faceIdx < maxFaces; faceIdx++) {
        html += '<div class="face-group">';
        // Cropped face (original)
        const firstModel = appState.faceModels[0];
        if (firstModel) {
            const cropUrl = getCroppedFaceUrl(basename, firstModel.id, faceIdx);
            if (cropUrl) {
                const isActive = faceIdx === fcCurrentFace;
                html += `<div class="face-row${isActive ? ' active' : ''}" onclick="selectFace(${faceIdx})"><img src="${cropUrl}" loading="lazy"><div class="face-row-label">Face ${faceIdx + 1}</div><div class="face-row-badge">Original</div></div>`;
            }
        }
        // Restored faces with model name badges
        appState.faceModels.forEach(m => {
            const restoredUrl = getRestoredFaceUrl(basename, m.id, faceIdx);
            if (restoredUrl) {
                const isActive = faceIdx === fcCurrentFace;
                html += `<div class="face-row restored${isActive ? ' active' : ''}" onclick="selectFace(${faceIdx})"><img src="${restoredUrl}" loading="lazy"><div class="face-row-label">Face ${faceIdx + 1}</div><div class="face-row-badge">${m.short}</div></div>`;
            }
        });
        html += '</div>';
    }
    content.innerHTML = html;
}

function selectFace(idx) {
    fcCurrentFace = idx;
    renderSidebar();
    renderFaceCompare();
}

// --- Full-screen overlay (Expand button) ---
function toggleFacesOverlay() {
    const existing = document.getElementById('facesOverlay');
    if (existing) { existing.remove(); return; }

    const basename = faceImageList[currentFaceIdx];
    if (!basename) return;
    let gridHtml = '';

    // Show all faces in a 2-column grid: cropped + restored per face
    const maxFaces = getMaxFaces(basename);
    for (let faceIdx = 0; faceIdx < maxFaces; faceIdx++) {
        const firstModel = appState.faceModels[0];
        if (firstModel) {
            const cropUrl = getCroppedFaceUrl(basename, firstModel.id, faceIdx);
            if (cropUrl) {
                gridHtml += `<div class="faces-overlay-item"><img src="${cropUrl}" onclick="openImageViewer('${cropUrl}')"><div class="faces-overlay-item-label">Face ${faceIdx + 1} — Original</div></div>`;
            }
        }
        appState.faceModels.forEach(m => {
            const restoredUrl = getRestoredFaceUrl(basename, m.id, faceIdx);
            if (restoredUrl) {
                gridHtml += `<div class="faces-overlay-item restored"><img src="${restoredUrl}" onclick="openImageViewer('${restoredUrl}')"><div class="faces-overlay-item-label">Face ${faceIdx + 1} — ${m.short}</div></div>`;
            }
        });
    }

    const overlay = document.createElement('div');
    overlay.id = 'facesOverlay';
    overlay.className = 'faces-overlay';
    overlay.innerHTML = '<div class="faces-overlay-header"><h2>Faces Comparison</h2><button class="expand-btn" onclick="toggleFacesOverlay()">Close</button></div><div class="faces-overlay-grid">' + gridHtml + '</div>';
    document.body.appendChild(overlay);
}

// --- Floating dock ---
function renderDock() {
    const dock = document.getElementById('dockButtons');
    if (!dock) return;
    const basename = faceImageList[currentFaceIdx];
    if (!basename) return;
    const choice = appState.choices[basename];

    let html = '';
    const enhChosen = choice === 'none';
    html += `<button class="dock-btn${enhChosen ? ' neutral' : ''}" onclick="dockChoose('none')">Enhanced</button>`;
    appState.faceModels.forEach(m => {
        const chosen = choice === m.id;
        html += `<button class="dock-btn${chosen ? ' chosen' : ''}" onclick="dockChoose('${m.id}')">${m.short}</button>`;
    });
    dock.innerHTML = html;
}

async function dockChoose(modelId) {
    const basename = faceImageList[currentFaceIdx];
    appState.choices[basename] = modelId;
    await fetch('/api/choose', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({filename: basename, model: modelId}) });
    renderFaceSidebar();
    renderDock();
}

function openImageViewer(url) {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.95);z-index:300;display:flex;align-items:center;justify-content:center;cursor:zoom-out;';
    overlay.innerHTML = `<img src="${url}" style="max-width:95%;max-height:95%;border-radius:4px;">`;
    overlay.onclick = () => overlay.remove();
    document.body.appendChild(overlay);
}

// --- Stage 4: Export ---
function goBackToFaceCompare() {
    showPanel(3);
}

async function openBrowserForExport() {
    // Reuse the directory browser, but direct selection to export dir
    exportBrowserMode = true;
    openBrowser();
}

async function goToExport() {
    showPanel(4);
    const res = await fetch('/api/state');
    const s = await res.json();
    appState.choices = s.choices || {};
    appState.esrganOutputs = s.esrgan_outputs || {};
    appState.faceOutputs = s.face_outputs || {};
    appState.faceModels = s.face_models || [];

    let html = '<table><tr><th>Image</th><th>Chosen Model</th></tr>';
    let chosen = 0;
    let unchosen = 0;
    faceImageList.forEach(basename => {
        const choice = appState.choices[basename];
        let label;
        if (!choice) { label = '<span style="color:#a55;">Not chosen (will use Enhanced only)</span>'; unchosen++; }
        else if (choice === 'none') { label = 'Enhanced only'; chosen++; }
        else { const m = appState.faceModels.find(fm => fm.id === choice); label = m ? m.name : choice; chosen++; }
        html += `<tr><td>${basename}</td><td>${label}</td></tr>`;
    });
    html += '</table>';
    html += `<div class="export-count">${chosen} images with choices, ${unchosen} using Enhanced only by default</div>`;
    document.getElementById('exportSummary').innerHTML = html;
}

async function doExport() {
    const dir = document.getElementById('exportDir').value.trim();
    if (!dir) return;
    const res = await fetch('/api/export', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({output_dir: dir})
    });
    const data = await res.json();
    if (data.error) {
        document.getElementById('exportResult').innerHTML = `<span style="color:#a55;">${data.error}</span>`;
        return;
    }
    let html = `<span style="color:#8c8;font-size:16px;">Exported ${data.exported} images to ${data.output_dir}</span>`;
    if (data.errors.length > 0) {
        html += `<div style="color:#a55;margin-top:8px;">Errors:<br>${data.errors.join('<br>')}</div>`;
    }
    document.getElementById('exportResult').innerHTML = html;
}

// Keyboard nav for face compare and viewer
document.addEventListener('keydown', (e) => {
    // Don't interfere with input fields
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;

    // Viewer shortcuts
    if (document.getElementById('viewer').style.display !== 'none') {
        if (e.key === 'Escape') closeViewer();
        if (e.key === 'ArrowLeft') viewerNav(-1);
        if (e.key === 'ArrowRight') viewerNav(1);
        if (e.key === ' ') { e.preventDefault(); viewerToggleSelect(); }
        return;
    }
    // Directory browser
    if (document.getElementById('dirBrowser').style.display !== 'none') {
        if (e.key === 'Escape') closeBrowser();
        return;
    }
    // ESRGAN compare shortcuts (Step 2, post-processing)
    if (document.getElementById('panel2').classList.contains('active') &&
        document.getElementById('esrganCompareView').style.display !== 'none') {
        if (e.key === 'ArrowLeft') esrganCompareNav(-1);
        if (e.key === 'ArrowRight') esrganCompareNav(1);
        if (e.key === 's' || e.key === 'S') setEsrganView('side');
        if (e.key === 'w' || e.key === 'W') setEsrganView('swipe');
    }
    // Face compare shortcuts (Step 3, post-processing)
    if (document.getElementById('panel3').classList.contains('active') &&
        document.getElementById('faceCompareView').style.display !== 'none') {
        if (e.key === 'ArrowLeft') faceNav(-1);
        if (e.key === 'ArrowRight') faceNav(1);
        if (e.key === 's' || e.key === 'S') setView('side');
        if (e.key === 'w' || e.key === 'W') setView('swipe');
        if (e.key === 'p' || e.key === 'P') toggleFacesOverlay();
    }
});
</script>
</body>
</html>"""


def main():
    init_work_dir()
    print(f"Work directory: {WORK_DIR}")
    print(f"Pipeline server starting on http://{HOST}:{PORT}")
    print(f"Open http://{HOST}:{PORT} in your browser")

    server = http.server.HTTPServer((HOST, PORT), PipelineHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
