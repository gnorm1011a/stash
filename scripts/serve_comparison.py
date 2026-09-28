"""
Face Restoration Comparison Viewer
Generates a manifest of all images and serves a static HTML comparison app.

Usage:
    python serve_comparison.py
    Then open http://localhost:8765/comparison.html in your browser
"""

import http.server
import json
import os
import socketserver
import sys
from pathlib import Path

# Configuration
REIMAGING_DIR = Path(r"\\192.168.0.31\Media\Files\Repositories\Personal\Stash\Reimaging")
INPUT_DIR = REIMAGING_DIR / "To restore"
PORT = 8765

# Model output folders and their display names
MODELS = [
    {
        "id": "gfpgan",
        "name": "GFPGAN v1.4",
        "settings": "2x upscale, weight=0.5",
        "output_dir": REIMAGING_DIR / "restored_gfpgan",
        "restored_subdir": "restored_imgs",
        "cropped_subdir": "cropped_faces",
    },
    {
        "id": "realesrgan",
        "name": "Real-ESRGAN x4plus",
        "settings": "2x upscale, full image enhancement",
        "output_dir": REIMAGING_DIR / "restored_realesrgan",
        "restored_subdir": "",
        "cropped_subdir": "",
        "suffix": "_out",
        "has_faces": False,
    },
    {
        "id": "codeformer_w0.8",
        "name": "CodeFormer w=0.8",
        "settings": "2x upscale, fidelity=0.8 (very high fidelity)",
        "output_dir": REIMAGING_DIR / "restored_codeformer_w0.8",
        "restored_subdir": "final_results",
        "cropped_subdir": "cropped_faces",
    },
    {
        "id": "codeformer_w0.7",
        "name": "CodeFormer w=0.7",
        "settings": "2x upscale, fidelity=0.7 (high fidelity)",
        "output_dir": REIMAGING_DIR / "restored_codeformer_w0.7",
        "restored_subdir": "final_results",
        "cropped_subdir": "cropped_faces",
    },
    {
        "id": "codeformer_w0.5",
        "name": "CodeFormer w=0.5",
        "settings": "2x upscale, fidelity=0.5 (balanced)",
        "output_dir": REIMAGING_DIR / "restored_codeformer_w0.5",
        "restored_subdir": "final_results",
        "cropped_subdir": "cropped_faces",
    },
    {
        "id": "codeformer_w0",
        "name": "CodeFormer w=0.0",
        "settings": "2x upscale, fidelity=0.0 (max quality)",
        "output_dir": REIMAGING_DIR / "restored_codeformer_w0",
        "restored_subdir": "final_results",
        "cropped_subdir": "cropped_faces",
    },
]


def get_basename(filepath):
    return Path(filepath).stem


def find_restored_image(model, basename):
    if model["restored_subdir"]:
        restored_dir = model["output_dir"] / model["restored_subdir"]
    else:
        restored_dir = model["output_dir"]
    if not restored_dir.exists():
        return None
    suffix = model.get("suffix", "")
    for ext in [".png", ".jpg", ".jpeg"]:
        candidate = restored_dir / f"{basename}{suffix}{ext}"
        if candidate.exists():
            return candidate
    return None


def find_cropped_faces(model, basename):
    cropped_dir = model["output_dir"] / model["cropped_subdir"]
    if not cropped_dir.exists():
        return []
    faces = []
    for f in sorted(cropped_dir.iterdir()):
        if f.name.startswith(f"{basename}_") and f.suffix in [".png", ".jpg", ".jpeg"]:
            faces.append(f.name)
    return faces


def find_restored_faces(model, basename):
    restored_faces_dir = model["output_dir"] / "restored_faces"
    if not restored_faces_dir.exists():
        return []
    faces = []
    for f in sorted(restored_faces_dir.iterdir()):
        if f.name.startswith(f"{basename}_") and f.suffix in [".png", ".jpg", ".jpeg"]:
            faces.append(f.name)
    return faces


def generate_manifest():
    images = []
    input_files = sorted(
        f for f in INPUT_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in [".jpg", ".jpeg", ".png"]
    )

    for input_file in input_files:
        basename = input_file.stem
        entry = {
            "basename": basename,
            "filename": input_file.name,
            "original": f"To restore/{input_file.name}",
            "models": {},
        }

        for model in MODELS:
            restored = find_restored_image(model, basename)
            cropped = find_cropped_faces(model, basename)
            restored_faces = find_restored_faces(model, basename)

            entry["models"][model["id"]] = {
                "name": model["name"],
                "settings": model["settings"],
                "restored": f"restored_{model['id']}/{model['restored_subdir']}/{restored.name}" if restored else (f"restored_{model['id']}/{restored.name}" if restored and not model["restored_subdir"] else None),
                "cropped_faces": [f"restored_{model['id']}/{model['cropped_subdir']}/{f}" for f in cropped] if model.get("cropped_subdir") else [],
                "restored_faces": [f"restored_{model['id']}/restored_faces/{f}" for f in restored_faces] if model.get("has_faces", True) else [],
            }

        images.append(entry)

    return {
        "models": [{"id": m["id"], "name": m["name"], "settings": m["settings"]} for m in MODELS],
        "images": images,
    }


# Generate manifest on startup
print("Generating manifest...")
manifest = generate_manifest()
print(f"Found {len(manifest['images'])} images with {len(manifest['models'])} models")

MANIFEST_PATH = REIMAGING_DIR / "manifest.json"
with open(MANIFEST_PATH, "w") as f:
    json.dump(manifest, f, indent=2)
print(f"Manifest written to {MANIFEST_PATH}")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REIMAGING_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format, *args):
        pass


HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Face Restoration Comparison</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #1a1a1a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; overflow: hidden; height: 100vh; display: flex; flex-direction: column; }

.topbar { background: #2a2a2a; padding: 10px 20px; display: flex; align-items: center; gap: 20px; border-bottom: 1px solid #3a3a3a; flex-shrink: 0; }
.topbar h1 { font-size: 16px; font-weight: 600; white-space: nowrap; }
.nav-btns { display: flex; gap: 8px; }
.nav-btn { background: #3a3a3a; border: 1px solid #4a4a4a; color: #e0e0e0; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 13px; }
.nav-btn:hover { background: #4a4a4a; }
.nav-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.image-info { font-size: 13px; color: #888; margin-left: auto; }

.controls { display: flex; gap: 16px; padding: 8px 20px; background: #2a2a2a; border-bottom: 1px solid #3a3a3a; align-items: center; flex-shrink: 0; }
.control-group { display: flex; align-items: center; gap: 6px; }
.control-group label { font-size: 12px; color: #888; }
.control-group select { background: #3a3a3a; color: #e0e0e0; border: 1px solid #4a4a4a; padding: 4px 8px; border-radius: 4px; font-size: 12px; cursor: pointer; }
.control-group select:hover { border-color: #6a6a6a; }
.toggle-btns { display: flex; gap: 0; }
.toggle-btn { background: #3a3a3a; border: 1px solid #4a4a4a; color: #aaa; padding: 4px 14px; cursor: pointer; font-size: 12px; }
.toggle-btn:first-child { border-radius: 4px 0 0 4px; }
.toggle-btn:last-child { border-radius: 0 4px 4px 0; border-left: none; }
.toggle-btn.active { background: #5050dd; color: #fff; border-color: #5050dd; }

.main { display: flex; flex: 1; overflow: hidden; }

.gallery { width: 200px; min-width: 80px; max-width: 500px; background: #2a2a2a; border-right: 1px solid #3a3a3a; overflow-y: auto; flex-shrink: 0; padding: 4px; }
.gallery-item { cursor: pointer; border-radius: 4px; overflow: hidden; margin-bottom: 6px; aspect-ratio: 4/3; }
.gallery-item:hover { outline: 2px solid #666; }
.gallery-item.active { outline: 2px solid #5050dd; }
.gallery-thumb { width: 100%; height: 100%; object-fit: cover; display: block; border-radius: 3px; }
.gallery-resizer { width: 6px; background: #3a3a3a; cursor: ew-resize; flex-shrink: 0; transition: background 0.15s; }
.gallery-resizer:hover { background: #5050dd; }

.compare-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.image-display { flex: 1; display: flex; align-items: center; justify-content: center; overflow: hidden; position: relative; background: #111; }

/* Side-by-side */
.side-by-side { display: flex; gap: 4px; height: 100%; justify-content: center; }
.side-panel { display: flex; flex-direction: column; align-items: center; overflow: hidden; flex: 0 1 auto; }
.side-panel canvas { display: block; cursor: grab; }
.side-panel canvas:active { cursor: grabbing; }

/* Model toggle bar above each panel */
.model-bar { display: flex; gap: 2px; flex-wrap: wrap; padding: 4px 0; justify-content: center; max-width: 100%; }
.model-toggle { background: #333; border: 1px solid #444; color: #888; padding: 3px 8px; border-radius: 3px; cursor: pointer; font-size: 10px; white-space: nowrap; }
.model-toggle:hover { background: #3a3a3a; color: #bbb; }
.model-toggle.active { background: #5050dd; color: #fff; border-color: #5050dd; }

/* Swipe */
.swipe-container { display: flex; flex-direction: column; width: 100%; height: 100%; align-items: center; }
.swipe-bars { display: flex; width: 100%; max-width: 100%; padding: 4px 8px; box-sizing: border-box; gap: 4px; }
.swipe-bars .model-bar { flex: 1; justify-content: center; }
.swipe-img-area { flex: 1; display: flex; align-items: center; justify-content: center; width: 100%; overflow: hidden; }
.swipe-wrap { position: relative; }
.swipe-wrap canvas { display: block; cursor: grab; }
.swipe-wrap canvas:active { cursor: grabbing; }
.swipe-divider { position: absolute; top: 0; bottom: 0; width: 3px; background: #fff; cursor: ew-resize; z-index: 10; }
.swipe-divider::after { content: ''; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 36px; height: 36px; background: #fff; border-radius: 50%; }
.swipe-divider::before { content: '\21C4'; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: #333; font-size: 18px; z-index: 11; font-weight: bold; }
.swipe-label { position: absolute; bottom: 8px; padding: 4px 10px; background: rgba(0,0,0,0.75); border-radius: 4px; font-size: 11px; color: #fff; z-index: 5; pointer-events: none; }
.swipe-label-left { left: 8px; }
.swipe-label-right { right: 8px; }

/* Zoom indicator */
.zoom-info { position: absolute; top: 8px; right: 8px; padding: 4px 10px; background: rgba(0,0,0,0.75); border-radius: 4px; font-size: 11px; color: #fff; z-index: 5; pointer-events: none; }

/* Faces sidebar (right) */
.faces-sidebar { width: 220px; background: #2a2a2a; border-left: 1px solid #3a3a3a; overflow-y: auto; flex-shrink: 0; padding: 10px; position: relative; }
.faces-sidebar-header { display: flex; justify-content: flex-end; margin-bottom: 8px; }
.expand-btn { background: #3a3a3a; border: 1px solid #4a4a4a; color: #aaa; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 11px; }
.expand-btn:hover { background: #4a4a4a; color: #fff; }
.face-group { margin-bottom: 16px; border-bottom: 1px solid #333; padding-bottom: 10px; }
.face-row { text-align: center; margin-bottom: 8px; }
.face-row img { width: 100%; max-width: 190px; border-radius: 4px; border: 1px solid #444; display: block; margin: 0 auto; }
.face-row.restored img { border-color: #5050dd; }
.face-row-label { font-size: 10px; color: #888; margin-top: 3px; }

/* Faces expanded overlay */
.faces-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.95); z-index: 100; display: flex; flex-direction: column; padding: 20px; }
.faces-overlay-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-shrink: 0; }
.faces-overlay-header h2 { font-size: 16px; color: #ccc; }
.faces-overlay-grid { flex: 1; overflow-y: auto; width: 100%; display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.faces-overlay-item { text-align: center; }
.faces-overlay-item img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 8px; border: 2px solid #444; }
.faces-overlay-item.restored img { border-color: #5050dd; }
.faces-overlay-item-label { font-size: 12px; color: #aaa; margin-top: 6px; }
.faces-overlay-face-sep { grid-column: 1 / -1; border-top: 1px solid #333; margin: 8px 0; padding-top: 4px; }
.faces-overlay-face-sep span { font-size: 13px; color: #888; font-weight: 600; }

.no-image { display: flex; align-items: center; justify-content: center; color: #555; font-size: 14px; padding: 40px; }
</style>
</head>
<body>

<div class="topbar">
    <h1>Face Restoration Comparison</h1>
    <div class="nav-btns">
        <button class="nav-btn" id="prevBtn" onclick="navigate(-1)">&#9664; Prev</button>
        <button class="nav-btn" id="nextBtn" onclick="navigate(1)">Next &#9654;</button>
    </div>
    <div class="image-info" id="imageInfo"></div>
</div>

<div class="controls">
    <div class="toggle-btns">
        <button class="toggle-btn active" id="fullBtn" onclick="setContentMode('full')">Full Image</button>
        <button class="toggle-btn" id="facesBtn" onclick="setContentMode('faces')">Faces</button>
    </div>
    <div class="toggle-btns">
        <button class="toggle-btn active" id="sideBtn" onclick="setView('side')">Side-by-side</button>
        <button class="toggle-btn" id="swipeBtn" onclick="setView('swipe')">Swipe</button>
    </div>
    <div class="control-group" id="faceSelector" style="display:none;">
        <label>Face:</label>
        <select id="faceSelect" onchange="onFaceChange()"></select>
    </div>
</div>

<div class="main">
    <div class="gallery" id="gallery"></div>
    <div class="gallery-resizer" id="galleryResizer"></div>
    <div class="compare-area">
        <div class="image-display" id="imageDisplay"></div>
    </div>
    <div class="faces-sidebar" id="facesSidebar">
        <div class="faces-sidebar-header">
            <button class="expand-btn" onclick="toggleFacesOverlay()">&#x2922; Expand</button>
        </div>
        <div id="facesContent"></div>
    </div>
</div>

<script>
let manifest = null;
let currentIdx = 0;
let swipePos = 50;
let zoom = 1;
let panX = 0, panY = 0;
let isPanning = false;
let panStartX = 0, panStartY = 0;
let panStartPanX = 0, panStartPanY = 0;
let leftId = 'original';
let rightId = 'gfpgan';
let contentMode = 'full'; // 'full' or 'faces'
let currentFace = 0;

let sources = [];

fetch('manifest.json')
    .then(r => r.json())
    .then(data => { manifest = data; init(); })
    .catch(err => {
        document.getElementById('imageDisplay').innerHTML = '<div class="no-image">Failed to load manifest.json</div>';
    });

function init() {
    sources = [{ id: 'original', name: 'Original', short: 'Original' }];
    const shortNames = { 'gfpgan': 'GFPGAN', 'realesrgan': 'ESRGAN', 'codeformer_w0': 'CF .0', 'codeformer_w0.5': 'CF .5', 'codeformer_w0.7': 'CF .7', 'codeformer_w0.8': 'CF .8' };
    manifest.models.forEach(m => sources.push({ id: m.id, name: m.name, short: shortNames[m.id] || m.name }));
    rightId = manifest.models[0].id;

    const gallery = document.getElementById('gallery');
    manifest.images.forEach((img, idx) => {
        const item = document.createElement('div');
        item.className = 'gallery-item';
        item.onclick = () => selectImage(idx);
        item.innerHTML = '<img class="gallery-thumb" src="' + img.original + '" loading="lazy">';
        gallery.appendChild(item);
    });

    selectImage(0);
}

function getImageSrc(sourceId, imgEntry) {
    if (contentMode === 'full') {
        if (sourceId === 'original') return imgEntry.original;
        const m = imgEntry.models[sourceId];
        return m ? m.restored : null;
    } else {
        // Faces mode: show cropped/restored faces for the selected face index
        if (sourceId === 'original') {
            // Original cropped face — from GFPGAN's cropped_faces (same across all models)
            const gfpganData = imgEntry.models['gfpgan'];
            if (gfpganData.cropped_faces && gfpganData.cropped_faces[currentFace]) return gfpganData.cropped_faces[currentFace];
            return null;
        }
        const m = imgEntry.models[sourceId];
        return (m && m.restored_faces && m.restored_faces[currentFace]) ? m.restored_faces[currentFace] : null;
    }
}

function selectImage(idx) {
    currentIdx = idx;
    currentFace = 0;
    zoom = 1; panX = 0; panY = 0;
    document.querySelectorAll('.gallery-item').forEach((el, i) => el.classList.toggle('active', i === idx));
    const img = manifest.images[idx];
    document.getElementById('imageInfo').textContent = (idx + 1) + ' / ' + manifest.images.length + ' \u2014 ' + img.filename;
    document.getElementById('prevBtn').disabled = idx === 0;
    document.getElementById('nextBtn').disabled = idx === manifest.images.length - 1;
    const activeItem = document.querySelectorAll('.gallery-item')[idx];
    if (activeItem) activeItem.scrollIntoView({ block: 'nearest' });
    updateFaceSelector();
    render();
}

function updateFaceSelector() {
    const img = manifest.images[currentIdx];
    let maxFaces = 0;
    manifest.models.forEach(model => {
        const data = img.models[model.id];
        if (data.cropped_faces && data.cropped_faces.length > maxFaces) maxFaces = data.cropped_faces.length;
    });
    const sel = document.getElementById('faceSelect');
    sel.innerHTML = '';
    for (let i = 0; i < maxFaces; i++) {
        sel.add(new Option('Face ' + (i + 1), i));
    }
    sel.value = currentFace;
    document.getElementById('faceSelector').style.display = (contentMode === 'faces' && maxFaces > 1) ? 'flex' : 'none';
}

function setContentMode(mode) {
    contentMode = mode;
    document.getElementById('fullBtn').classList.toggle('active', mode === 'full');
    document.getElementById('facesBtn').classList.toggle('active', mode === 'faces');
    zoom = 1; panX = 0; panY = 0;
    updateFaceSelector();
    render();
}

function onFaceChange() {
    currentFace = parseInt(document.getElementById('faceSelect').value) || 0;
    zoom = 1; panX = 0; panY = 0;
    render();
}

function navigate(dir) {
    const newIdx = currentIdx + dir;
    if (newIdx >= 0 && newIdx < manifest.images.length) selectImage(newIdx);
}

let currentView = 'side';

function setView(mode) {
    currentView = mode;
    document.getElementById('sideBtn').classList.toggle('active', mode === 'side');
    document.getElementById('swipeBtn').classList.toggle('active', mode === 'swipe');
    render();
}

function buildModelBar(containerId, currentId, onSelect) {
    let html = '<div class="model-bar" id="' + containerId + '">';
    sources.forEach(s => {
        const active = s.id === currentId ? ' active' : '';
        html += '<button class="model-toggle' + active + '" onclick="' + onSelect + '(\'' + s.id + '\')">' + s.short + '</button>';
    });
    html += '</div>';
    return html;
}

function selectLeft(id) { leftId = id; render(); }
function selectRight(id) { rightId = id; render(); }

function render() {
    if (currentView === 'side') renderSideBySide();
    else renderSwipe();
    renderSidebar();
}

function renderSideBySide() {
    const img = manifest.images[currentIdx];
    const leftSrc = getImageSrc(leftId, img);
    const rightSrc = getImageSrc(rightId, img);
    const leftName = sources.find(s => s.id === leftId).name;
    const rightName = sources.find(s => s.id === rightId).name;
    const display = document.getElementById('imageDisplay');

    if (!leftSrc || !rightSrc) {
        display.innerHTML = '<div class="no-image">No image available</div>';
        return;
    }

    display.innerHTML = '<div class="side-by-side">' +
        '<div class="side-panel">' + buildModelBar('leftBar', leftId, 'selectLeft') +
        '<canvas id="sideCanvasL"></canvas></div>' +
        '<div class="side-panel">' + buildModelBar('rightBar', rightId, 'selectRight') +
        '<canvas id="sideCanvasR"></canvas></div>' +
        '</div><div class="zoom-info" id="zoomInfo">' + Math.round(zoom * 100) + '%</div>';

    const canvasL = document.getElementById('sideCanvasL');
    const canvasR = document.getElementById('sideCanvasR');
    const ctxL = canvasL.getContext('2d');
    const ctxR = canvasR.getContext('2d');

    const imgL = new Image();
    const imgR = new Image();
    let lLoaded = false, rLoaded = false;
    let baseW = 0, baseH = 0;

    function tryDrawSide() {
        if (!lLoaded || !rLoaded) return;
        const maxW = (display.clientWidth - 20) / 2;
        const maxH = display.clientHeight - 60;
        const arL = imgL.naturalWidth / imgL.naturalHeight;
        const arR = imgR.naturalWidth / imgR.naturalHeight;
        const aspect = Math.max(arL, arR);
        let w = maxW, h = w / aspect;
        if (h > maxH) { h = maxH; w = h * aspect; }
        baseW = Math.round(w); baseH = Math.round(h);
        canvasL.width = baseW; canvasL.height = baseH;
        canvasR.width = baseW; canvasR.height = baseH;
        drawSide();
    }

    function drawSide() {
        ctxL.clearRect(0, 0, baseW, baseH);
        ctxL.fillStyle = '#111'; ctxL.fillRect(0, 0, baseW, baseH);
        drawZoomed(ctxL, imgL, baseW, baseH, zoom, panX, panY);
        ctxR.clearRect(0, 0, baseW, baseH);
        ctxR.fillStyle = '#111'; ctxR.fillRect(0, 0, baseW, baseH);
        drawZoomed(ctxR, imgR, baseW, baseH, zoom, panX, panY);
        document.getElementById('zoomInfo').textContent = Math.round(zoom * 100) + '%';
    }

    imgL.onload = () => { lLoaded = true; tryDrawSide(); };
    imgR.onload = () => { rLoaded = true; tryDrawSide(); };
    imgL.src = leftSrc; imgR.src = rightSrc;

    [canvasL, canvasR].forEach(c => {
        c.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY > 0 ? 0.9 : 1.1;
            const newZoom = Math.max(0.5, Math.min(10, zoom * delta));
            const rect = c.getBoundingClientRect();
            const mx = e.clientX - rect.left, my = e.clientY - rect.top;
            panX = mx - (mx - panX) * (newZoom / zoom);
            panY = my - (my - panY) * (newZoom / zoom);
            zoom = newZoom; drawSide();
        });
        c.addEventListener('mousedown', (e) => {
            isPanning = true;
            panStartX = e.clientX; panStartY = e.clientY;
            panStartPanX = panX; panStartPanY = panY;
            e.preventDefault();
        });
    });
    document.addEventListener('mousemove', (e) => {
        if (!isPanning) return;
        panX = panStartPanX + (e.clientX - panStartX);
        panY = panStartPanY + (e.clientY - panStartY);
        drawSide();
    });
    document.addEventListener('mouseup', () => { isPanning = false; });
    window.addEventListener('resize', tryDrawSide);
}

function drawZoomed(ctx, img, w, h, z, px, py) {
    const ar = img.naturalWidth / img.naturalHeight;
    let dw = w, dh = w / ar;
    if (dh > h) { dh = h; dw = h * ar; }
    const dx = (w - dw) / 2, dy = (h - dh) / 2;
    const sw = dw * z, sh = dh * z;
    const sx = dx + px - (sw - dw) / 2, sy = dy + py - (sh - dh) / 2;
    ctx.drawImage(img, 0, 0, img.naturalWidth, img.naturalHeight, sx, sy, sw, sh);
}

function renderSwipe() {
    const img = manifest.images[currentIdx];
    const leftSrc = getImageSrc(leftId, img);
    const rightSrc = getImageSrc(rightId, img);
    const leftName = sources.find(s => s.id === leftId).name;
    const rightName = sources.find(s => s.id === rightId).name;
    const display = document.getElementById('imageDisplay');

    if (!leftSrc || !rightSrc) {
        display.innerHTML = '<div class="no-image">No image available</div>';
        return;
    }

    // Model bars above the swipe image, all in a column container
    display.innerHTML = '<div class="swipe-container">' +
        '<div class="swipe-bars">' + buildModelBar('leftBar', leftId, 'selectLeft') + buildModelBar('rightBar', rightId, 'selectRight') + '</div>' +
        '<div class="swipe-img-area">' +
        '<div class="swipe-wrap" id="swipeWrap">' +
        '<canvas id="swipeCanvas"></canvas>' +
        '<div class="swipe-divider" id="swipeDivider" style="left:' + swipePos + '%"></div>' +
        '<div class="swipe-label swipe-label-left">' + leftName + '</div>' +
        '<div class="swipe-label swipe-label-right">' + rightName + '</div>' +
        '</div>' +
        '</div>' +
        '</div><div class="zoom-info" id="zoomInfo">' + Math.round(zoom * 100) + '%</div>';

    const canvas = document.getElementById('swipeCanvas');
    const ctx = canvas.getContext('2d');
    const wrap = document.getElementById('swipeWrap');
    const divider = document.getElementById('swipeDivider');

    const leftImg = new Image();
    const rightImg = new Image();
    let leftLoaded = false, rightLoaded = false;
    let drawW = 0, drawH = 0;

    function tryDraw() {
        if (!leftLoaded || !rightLoaded) return;
        const maxW = display.clientWidth - 40;
        const maxH = display.clientHeight - 100;
        const arL = leftImg.naturalWidth / leftImg.naturalHeight;
        const arR = rightImg.naturalWidth / rightImg.naturalHeight;
        const aspect = Math.max(arL, arR);
        let w = maxW, h = w / aspect;
        if (h > maxH) { h = maxH; w = h * aspect; }
        drawW = Math.round(w); drawH = Math.round(h);
        canvas.width = drawW; canvas.height = drawH;
        wrap.style.width = drawW + 'px'; wrap.style.height = drawH + 'px';
        doDraw();
    }

    function doDraw() {
        ctx.clearRect(0, 0, drawW, drawH);
        ctx.fillStyle = '#111'; ctx.fillRect(0, 0, drawW, drawH);
        drawZoomedFill(ctx, rightImg, drawW, drawH, zoom, panX, panY);
        const splitX = Math.round(drawW * swipePos / 100);
        if (splitX > 0) {
            ctx.save(); ctx.beginPath(); ctx.rect(0, 0, splitX, drawH); ctx.clip();
            drawZoomedFill(ctx, leftImg, drawW, drawH, zoom, panX, panY);
            ctx.restore();
        }
        divider.style.left = swipePos + '%';
        document.getElementById('zoomInfo').textContent = Math.round(zoom * 100) + '%';
    }

    leftImg.onload = () => { leftLoaded = true; tryDraw(); };
    rightImg.onload = () => { rightLoaded = true; tryDraw(); };
    leftImg.src = leftSrc; rightImg.src = rightSrc;

    // Pan on canvas, swipe on divider only
    let isSwiping = false;

    canvas.addEventListener('mousedown', (e) => {
        isPanning = true;
        panStartX = e.clientX; panStartY = e.clientY;
        panStartPanX = panX; panStartPanY = panY;
        e.preventDefault();
    });

    divider.addEventListener('mousedown', (e) => {
        isSwiping = true; e.preventDefault(); e.stopPropagation();
    });

    document.addEventListener('mousemove', (e) => {
        if (isPanning) {
            panX = panStartPanX + (e.clientX - panStartX);
            panY = panStartPanY + (e.clientY - panStartY);
            doDraw();
        } else if (isSwiping) {
            const rect = canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            swipePos = Math.max(0, Math.min(100, (x / rect.width) * 100));
            doDraw();
        }
    });

    document.addEventListener('mouseup', () => { isPanning = false; isSwiping = false; });

    canvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newZoom = Math.max(0.5, Math.min(10, zoom * delta));
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left, my = e.clientY - rect.top;
        panX = mx - (mx - panX) * (newZoom / zoom);
        panY = my - (my - panY) * (newZoom / zoom);
        zoom = newZoom; doDraw();
    });

    window.addEventListener('resize', tryDraw);
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

function renderSidebar() {
    if (contentMode === 'full') renderSidebarFaces();
    else renderSidebarFull();
}

function renderSidebarFaces() {
    const img = manifest.images[currentIdx];
    const content = document.getElementById('facesContent');

    let maxFaces = 0;
    manifest.models.forEach(model => {
        const data = img.models[model.id];
        if (data.cropped_faces && data.cropped_faces.length > maxFaces) maxFaces = data.cropped_faces.length;
    });

    if (maxFaces === 0) {
        content.innerHTML = '<div style="color:#555;font-size:12px;">No faces detected</div>';
        return;
    }

    let html = '';
    for (let faceIdx = 0; faceIdx < maxFaces; faceIdx++) {
        html += '<div class="face-group">';
        const gfpganData = img.models['gfpgan'];
        if (gfpganData.cropped_faces && gfpganData.cropped_faces[faceIdx]) {
            html += '<div class="face-row"><img src="' + gfpganData.cropped_faces[faceIdx] + '"><div class="face-row-label">Original</div></div>';
        }
        manifest.models.forEach(model => {
            const data = img.models[model.id];
            if (data.restored_faces && data.restored_faces[faceIdx]) {
                const sn = sources.find(s => s.id === model.id);
                const label = sn ? sn.short : model.name;
                html += '<div class="face-row restored"><img src="' + data.restored_faces[faceIdx] + '"><div class="face-row-label">' + label + '</div></div>';
            }
        });
        html += '</div>';
    }
    content.innerHTML = html;
}

function renderSidebarFull() {
    const img = manifest.images[currentIdx];
    const content = document.getElementById('facesContent');

    // Show full images: original + each model's restored full image
    let html = '<div class="face-group">';
    html += '<div class="face-row"><img src="' + img.original + '"><div class="face-row-label">Original</div></div>';
    manifest.models.forEach(model => {
        const data = img.models[model.id];
        if (data.restored) {
            const sn = sources.find(s => s.id === model.id);
            const label = sn ? sn.short : model.name;
            html += '<div class="face-row restored"><img src="' + data.restored + '"><div class="face-row-label">' + label + '</div></div>';
        }
    });
    html += '</div>';
    content.innerHTML = html;
}

// Faces expanded overlay
function toggleFacesOverlay() {
    const existing = document.getElementById('facesOverlay');
    if (existing) { existing.remove(); return; }

    const img = manifest.images[currentIdx];
    let gridHtml = '';

    if (contentMode === 'full') {
        // Show all faces in grid
        let maxFaces = 0;
        manifest.models.forEach(model => {
            const data = img.models[model.id];
            if (data.cropped_faces && data.cropped_faces.length > maxFaces) maxFaces = data.cropped_faces.length;
        });
        for (let faceIdx = 0; faceIdx < maxFaces; faceIdx++) {
            if (faceIdx > 0) gridHtml += '<div class="faces-overlay-face-sep"></div>';
            const gfpganData = img.models['gfpgan'];
            if (gfpganData.cropped_faces && gfpganData.cropped_faces[faceIdx]) {
                gridHtml += '<div class="faces-overlay-item"><img src="' + gfpganData.cropped_faces[faceIdx] + '"><div class="faces-overlay-item-label">Original</div></div>';
            }
            manifest.models.forEach(model => {
                const data = img.models[model.id];
                if (data.restored_faces && data.restored_faces[faceIdx]) {
                    const sn = sources.find(s => s.id === model.id);
                    const label = sn ? sn.short : model.name;
                    gridHtml += '<div class="faces-overlay-item restored"><img src="' + data.restored_faces[faceIdx] + '"><div class="faces-overlay-item-label">' + label + '</div></div>';
                }
            });
        }
    } else {
        // Show full images in grid
        gridHtml += '<div class="faces-overlay-item"><img src="' + img.original + '"><div class="faces-overlay-item-label">Original</div></div>';
        manifest.models.forEach(model => {
            const data = img.models[model.id];
            if (data.restored) {
                const sn = sources.find(s => s.id === model.id);
                const label = sn ? sn.short : model.name;
                gridHtml += '<div class="faces-overlay-item restored"><img src="' + data.restored + '"><div class="faces-overlay-item-label">' + label + '</div></div>';
            }
        });
    }

    const title = contentMode === 'full' ? 'Faces Comparison' : 'Full Image Comparison';
    const overlay = document.createElement('div');
    overlay.id = 'facesOverlay';
    overlay.className = 'faces-overlay';
    overlay.innerHTML = '<div class="faces-overlay-header"><h2>' + title + '</h2><button class="expand-btn" onclick="toggleFacesOverlay()">Close</button></div><div class="faces-overlay-grid">' + gridHtml + '</div>';
    document.body.appendChild(overlay);
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') navigate(-1);
    if (e.key === 'ArrowRight') navigate(1);
    if (e.key === 'Escape') { const o = document.getElementById('facesOverlay'); if (o) o.remove(); }
});

// Gallery resizer
(function() {
    const resizer = document.getElementById('galleryResizer');
    const gallery = document.getElementById('gallery');
    let resizing = false, startX = 0, startW = 0;
    resizer.addEventListener('mousedown', (e) => {
        resizing = true; startX = e.clientX; startW = gallery.offsetWidth;
        document.body.style.cursor = 'ew-resize';
        e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
        if (!resizing) return;
        const newW = Math.max(80, Math.min(500, startW + e.clientX - startX));
        gallery.style.width = newW + 'px';
    });
    document.addEventListener('mouseup', () => {
        if (resizing) { resizing = false; document.body.style.cursor = ''; }
    });
})();
</script>
</body>
</html>"""

HTML_PATH = REIMAGING_DIR / "comparison.html"
with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(HTML_CONTENT)
print(f"HTML app written to {HTML_PATH}")

print(f"\nServing on http://localhost:{PORT}")
print(f"Open http://localhost:{PORT}/comparison.html in your browser")
print("Press Ctrl+C to stop")

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
