from __future__ import annotations

import json
import mimetypes
import posixpath
import re
import threading
import urllib.parse
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen.flac import FLAC

from .models import AUDIO_EXTENSIONS, COVER_FILENAMES
from .scanner import is_ignored_name


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>meta-sonata</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <strong>meta-sonata</strong>
        <span id="root-label"></span>
      </div>
      <div class="status-pill">read only</div>
    </header>
    <main class="workspace">
      <aside class="sidebar" aria-label="Library tree">
        <div class="pane-title">
          <span>Library</span>
          <button id="refresh-tree" type="button">Refresh</button>
        </div>
        <div id="tree" class="tree"></div>
      </aside>
      <section class="viewer" aria-live="polite">
        <div id="empty-state" class="empty-state">
          <h1>No Track Selected</h1>
          <p>Browse the library tree to inspect embedded metadata.</p>
        </div>
        <div id="track-view" class="track-view hidden">
          <section class="track-hero">
            <div class="cover-frame">
              <img id="cover" alt="">
              <div id="cover-empty" class="cover-empty">No Cover</div>
            </div>
            <div class="track-title-block">
              <div id="track-path" class="path-line"></div>
              <h1 id="track-title"></h1>
              <div id="track-subtitle" class="subtitle"></div>
              <div id="track-badges" class="badges"></div>
            </div>
          </section>
          <section class="detail-grid">
            <div class="panel">
              <h2>File</h2>
              <dl id="file-info" class="kv"></dl>
            </div>
            <div class="panel">
              <h2>Core Tags</h2>
              <dl id="core-tags" class="kv"></dl>
            </div>
            <div class="panel">
              <h2>Source Tags</h2>
              <dl id="source-tags" class="kv"></dl>
            </div>
            <div class="panel">
              <h2>Lyrics</h2>
              <dl id="lyrics-summary" class="kv"></dl>
              <pre id="lyrics-preview" class="lyrics-preview"></pre>
            </div>
          </section>
          <section class="panel all-tags-panel">
            <h2>All Tags</h2>
            <div id="all-tags" class="tag-table"></div>
          </section>
        </div>
      </section>
    </main>
  </div>
  <script src="/static/app.js"></script>
</body>
</html>
"""


CSS = """
:root {
  color-scheme: light;
  --bg: #f6f7f8;
  --panel: #ffffff;
  --line: #d8dde3;
  --text: #1f2933;
  --muted: #607080;
  --accent: #2f6f73;
  --accent-weak: #e4f1ef;
  --warn: #9a5a00;
  --shadow: 0 1px 2px rgba(20, 30, 40, 0.08);
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  letter-spacing: 0;
}

button {
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
}

.shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  min-height: 48px;
  padding: 0 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--line);
  background: #fbfbfc;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.brand strong {
  font-size: 15px;
}

#root-label {
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 64vw;
}

.status-pill {
  border: 1px solid #aac8c6;
  color: #225d60;
  background: var(--accent-weak);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  white-space: nowrap;
}

.workspace {
  display: grid;
  grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
  min-height: calc(100vh - 49px);
}

.sidebar {
  border-right: 1px solid var(--line);
  background: #fbfbfc;
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.pane-title {
  height: 44px;
  padding: 0 12px 0 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--line);
  font-weight: 650;
}

.pane-title button {
  color: var(--accent);
  border-radius: 6px;
  padding: 5px 8px;
}

.pane-title button:hover {
  background: var(--accent-weak);
}

.tree {
  overflow: auto;
  padding: 8px;
}

.tree-row {
  min-height: 30px;
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  border-radius: 6px;
  padding: 4px 7px;
  text-align: left;
  color: var(--text);
}

.tree-row:hover {
  background: #eef2f5;
}

.tree-row.selected {
  background: var(--accent-weak);
  color: #164e50;
}

.tree-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-icon {
  width: 18px;
  flex: 0 0 18px;
  color: var(--muted);
  font-size: 12px;
  text-align: center;
}

.tree-children {
  margin-left: 16px;
}

.tree-note {
  color: var(--muted);
  padding: 8px 10px;
}

.viewer {
  min-width: 0;
  overflow: auto;
  padding: 20px;
}

.empty-state {
  max-width: 560px;
  padding-top: 12vh;
  color: var(--muted);
}

.empty-state h1 {
  color: var(--text);
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 8px;
}

.hidden {
  display: none;
}

.track-hero {
  display: grid;
  grid-template-columns: 168px minmax(0, 1fr);
  gap: 20px;
  align-items: end;
  margin-bottom: 18px;
}

.cover-frame {
  width: 168px;
  aspect-ratio: 1;
  background: #e9edf1;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  box-shadow: var(--shadow);
}

.cover-frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cover-empty {
  padding: 12px;
  text-align: center;
}

.path-line {
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
  margin-bottom: 6px;
}

.track-title-block h1 {
  font-size: 30px;
  line-height: 1.12;
  margin: 0 0 8px;
}

.subtitle {
  color: var(--muted);
  font-size: 15px;
}

.badges {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.badge {
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 999px;
  padding: 4px 9px;
  font-size: 12px;
  color: var(--muted);
}

.badge.ok {
  border-color: #aac8c6;
  color: #225d60;
  background: var(--accent-weak);
}

.badge.warn {
  border-color: #e1c18a;
  color: var(--warn);
  background: #fff7e8;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(260px, 1fr));
  gap: 14px;
}

.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  box-shadow: var(--shadow);
  min-width: 0;
}

.panel h2 {
  margin: 0 0 12px;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0;
  color: var(--muted);
}

.kv {
  display: grid;
  grid-template-columns: minmax(104px, 0.34fr) minmax(0, 1fr);
  gap: 8px 12px;
  margin: 0;
}

.kv dt {
  color: var(--muted);
  overflow-wrap: anywhere;
}

.kv dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.lyrics-preview {
  margin: 12px 0 0;
  max-height: 320px;
  overflow: auto;
  background: #f5f7f8;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px;
  white-space: pre-wrap;
  line-height: 1.5;
}

.all-tags-panel {
  margin-top: 14px;
}

.tag-table {
  display: grid;
  grid-template-columns: minmax(160px, 0.28fr) minmax(0, 1fr);
  border-top: 1px solid var(--line);
}

.tag-key,
.tag-value {
  padding: 8px 0;
  border-bottom: 1px solid var(--line);
  overflow-wrap: anywhere;
}

.tag-key {
  color: var(--muted);
  padding-right: 14px;
}

@media (max-width: 880px) {
  .workspace {
    grid-template-columns: 1fr;
  }

  .sidebar {
    border-right: 0;
    border-bottom: 1px solid var(--line);
    max-height: 42vh;
  }

  .track-hero,
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .cover-frame {
    width: min(168px, 48vw);
  }
}
"""


JS = """
const state = {
  root: null,
  selectedRel: null,
  loaded: new Map(),
  expanded: new Set([""]),
};

const el = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "";
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(payload.error || response.statusText);
  }
  return response.json();
}

function relParam(rel) {
  return new URLSearchParams({ rel }).toString();
}

async function loadRoot() {
  state.loaded.clear();
  state.expanded = new Set([""]);
  state.selectedRel = null;
  const root = await fetchJson("/api/root");
  state.root = root;
  el("root-label").textContent = root.path;
  await loadChildren("");
  renderTree();
}

async function loadChildren(rel) {
  if (state.loaded.has(rel)) return state.loaded.get(rel);
  const data = await fetchJson(`/api/children?${relParam(rel)}`);
  state.loaded.set(rel, data.children);
  return data.children;
}

function renderTree() {
  const tree = el("tree");
  tree.innerHTML = "";
  const rootButton = document.createElement("button");
  rootButton.className = "tree-row";
  rootButton.type = "button";
  rootButton.innerHTML = `<span class="tree-icon">${state.expanded.has("") ? "v" : ">"}</span><span class="tree-label">${escapeHtml(state.root?.name || "Root")}</span>`;
  rootButton.addEventListener("click", async () => {
    toggleDirectory("");
  });
  tree.appendChild(rootButton);
  const children = document.createElement("div");
  children.className = "tree-children";
  tree.appendChild(children);
  renderChildren("", children);
}

function renderChildren(rel, container) {
  const nodes = state.loaded.get(rel) || [];
  if (!nodes.length) {
    const note = document.createElement("div");
    note.className = "tree-note";
    note.textContent = "Empty";
    container.appendChild(note);
    return;
  }

  for (const node of nodes) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `tree-row${state.selectedRel === node.rel ? " selected" : ""}`;
    row.style.paddingLeft = "7px";
    const icon = node.type === "directory" ? (state.expanded.has(node.rel) ? "v" : ">") : "*";
    row.innerHTML = `<span class="tree-icon">${icon}</span><span class="tree-label">${escapeHtml(node.name)}</span>`;
    row.addEventListener("click", async () => {
      if (node.type === "directory") {
        await toggleDirectory(node.rel);
      } else if (node.type === "audio") {
        await selectTrack(node.rel);
      }
    });
    container.appendChild(row);

    if (node.type === "directory" && state.expanded.has(node.rel)) {
      const childContainer = document.createElement("div");
      childContainer.className = "tree-children";
      container.appendChild(childContainer);
      renderChildren(node.rel, childContainer);
    }
  }
}

async function toggleDirectory(rel) {
  if (state.expanded.has(rel)) {
    state.expanded.delete(rel);
  } else {
    state.expanded.add(rel);
    await loadChildren(rel);
  }
  renderTree();
}

async function selectTrack(rel) {
  state.selectedRel = rel;
  renderTree();
  const detail = await fetchJson(`/api/track?${relParam(rel)}`);
  renderTrack(detail);
}

function renderTrack(detail) {
  el("empty-state").classList.add("hidden");
  el("track-view").classList.remove("hidden");

  el("track-path").textContent = detail.relative_path;
  el("track-title").textContent = firstTag(detail.tags, "title") || detail.file.name;
  const artist = firstTag(detail.tags, "artist") || firstTag(detail.tags, "albumartist");
  const album = firstTag(detail.tags, "album");
  el("track-subtitle").textContent = [artist, album].filter(Boolean).join(" - ");

  const cover = el("cover");
  const coverEmpty = el("cover-empty");
  if (detail.cover) {
    cover.src = `/api/cover?${relParam(detail.relative_path)}&v=${encodeURIComponent(detail.file.mtime || "")}`;
    cover.classList.remove("hidden");
    coverEmpty.classList.add("hidden");
  } else {
    cover.removeAttribute("src");
    cover.classList.add("hidden");
    coverEmpty.classList.remove("hidden");
  }

  renderBadges(detail);
  renderDefinitionList("file-info", fileRows(detail));
  renderDefinitionList("core-tags", pickTags(detail.tags, [
    "title", "artist", "albumartist", "album", "date", "tracknumber",
    "discnumber", "genre", "label", "catalognumber", "barcode",
  ]));
  renderDefinitionList("source-tags", pickTags(detail.tags, [
    "musicinfo_source", "musicbrainz_albumid", "musicbrainz_trackid",
    "lyrics_source", "lyrics_score",
  ]));
  renderLyrics(detail);
  renderAllTags(detail.tags);
}

function firstTag(tags, key) {
  const values = tags[key] || tags[key.toUpperCase()];
  return Array.isArray(values) && values.length ? values[0] : "";
}

function pickTags(tags, keys) {
  const rows = [];
  for (const key of keys) {
    const value = tags[key] || tags[key.toUpperCase()];
    rows.push([key, formatTagValue(value)]);
  }
  return rows;
}

function formatTagValue(value) {
  if (!value) return "";
  if (Array.isArray(value)) return value.join("; ");
  return String(value);
}

function fileRows(detail) {
  const info = detail.audio || {};
  return [
    ["Name", detail.file.name],
    ["Format", detail.file.suffix || detail.format || ""],
    ["Size", formatBytes(detail.file.size)],
    ["Modified", detail.file.modified || ""],
    ["Duration", formatDuration(info.length)],
    ["Bitrate", info.bitrate ? `${Math.round(info.bitrate / 1000)} kbps` : ""],
    ["Sample Rate", info.sample_rate ? `${info.sample_rate} Hz` : ""],
    ["Channels", info.channels || ""],
  ];
}

function renderDefinitionList(id, rows) {
  const node = el(id);
  node.innerHTML = "";
  for (const [key, value] of rows) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = key;
    dd.textContent = value || " ";
    node.appendChild(dt);
    node.appendChild(dd);
  }
}

function renderBadges(detail) {
  const badges = [];
  if (detail.cover) badges.push(["ok", "cover"]);
  else badges.push(["warn", "no cover"]);
  if (detail.lyrics.has_lyrics) badges.push(["ok", "lyrics"]);
  else badges.push(["warn", "no lyrics"]);
  if (firstTag(detail.tags, "musicbrainz_albumid")) badges.push(["ok", "musicbrainz"]);
  if (detail.warnings.length) badges.push(["warn", `${detail.warnings.length} warnings`]);
  el("track-badges").innerHTML = badges.map(([kind, label]) => `<span class="badge ${kind}">${escapeHtml(label)}</span>`).join("");
}

function renderLyrics(detail) {
  const summary = [
    ["Has Lyrics", detail.lyrics.has_lyrics ? "yes" : "no"],
    ["Synced", detail.lyrics.has_synced ? "yes" : "no"],
    ["Characters", detail.lyrics.length || ""],
    ["Source", firstTag(detail.tags, "lyrics_source")],
  ];
  renderDefinitionList("lyrics-summary", summary);
  el("lyrics-preview").textContent = detail.lyrics.preview || "";
}

function renderAllTags(tags) {
  const table = el("all-tags");
  const rows = Object.entries(tags).sort(([a], [b]) => a.localeCompare(b));
  table.innerHTML = "";
  for (const [key, value] of rows) {
    const keyNode = document.createElement("div");
    const valueNode = document.createElement("div");
    keyNode.className = "tag-key";
    valueNode.className = "tag-value";
    keyNode.textContent = key;
    valueNode.textContent = summarizeTag(key, value);
    table.appendChild(keyNode);
    table.appendChild(valueNode);
  }
}

function summarizeTag(key, value) {
  const text = formatTagValue(value);
  if (/lyrics/i.test(key) && text.length > 180) {
    return `${text.slice(0, 180)} ... (${text.length} chars)`;
  }
  return text;
}

el("refresh-tree").addEventListener("click", () => {
  loadRoot().catch(showError);
});

function showError(error) {
  el("tree").innerHTML = `<div class="tree-note">${escapeHtml(error.message)}</div>`;
}

loadRoot().catch(showError);
"""


def serve_web(root: Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    root = root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    handler = make_handler(root)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    url = f"http://{host}:{server.server_port}/"
    print(f"meta-sonata web serving {root}")
    print(f"url: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nmeta-sonata web stopped")
    finally:
        server.server_close()


def make_handler(root: Path):
    class MetaSonataWebHandler(BaseHTTPRequestHandler):
        server_version = "MetaSonataWeb/0.1"

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            try:
                if parsed.path == "/":
                    self.send_text(HTML, "text/html; charset=utf-8")
                elif parsed.path == "/static/app.css":
                    self.send_text(CSS, "text/css; charset=utf-8")
                elif parsed.path == "/static/app.js":
                    self.send_text(JS, "application/javascript; charset=utf-8")
                elif parsed.path == "/api/root":
                    self.send_json({"name": root.name or str(root), "path": str(root)})
                elif parsed.path == "/api/children":
                    rel = query_value(parsed.query, "rel")
                    self.send_json({"children": build_child_listing(root, rel)})
                elif parsed.path == "/api/track":
                    rel = query_value(parsed.query, "rel")
                    self.send_json(track_detail(root, rel))
                elif parsed.path == "/api/cover":
                    rel = query_value(parsed.query, "rel")
                    self.send_cover(root, rel)
                else:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
            except ValueError as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            except FileNotFoundError as exc:
                self.send_error_json(HTTPStatus.NOT_FOUND, str(exc))
            except Exception as exc:
                self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

        def log_message(self, format: str, *args) -> None:
            return

        def send_text(self, body: str, content_type: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def send_json(self, body: Any) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def send_error_json(self, status: HTTPStatus, message: str) -> None:
            payload = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def send_cover(self, root: Path, rel: str) -> None:
            path = safe_join(root, rel)
            data, mime = cover_bytes(path)
            if not data:
                self.send_error_json(HTTPStatus.NOT_FOUND, "cover not found")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return MetaSonataWebHandler


def query_value(query: str, key: str) -> str:
    values = urllib.parse.parse_qs(query, keep_blank_values=True).get(key, [""])
    return values[0]


def safe_join(root: Path, rel: str) -> Path:
    root = root.resolve()
    rel = urllib.parse.unquote(rel or "")
    normalized = posixpath.normpath(rel.replace("\\", "/"))
    if normalized in {".", "/"}:
        normalized = ""
    if normalized.startswith("../") or normalized == ".." or posixpath.isabs(normalized):
        raise ValueError("path escapes web root")
    target = (root / normalized).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes web root") from exc
    return target


def relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def build_child_listing(root: Path, rel: str = "") -> list[dict[str, Any]]:
    directory = safe_join(root, rel)
    if not directory.exists():
        raise FileNotFoundError(directory)
    if not directory.is_dir():
        raise ValueError("not a directory")

    rows: list[dict[str, Any]] = []
    for child in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold())):
        if is_ignored_name(child.name):
            continue
        if child.is_dir():
            rows.append(
                {
                    "name": child.name,
                    "rel": relative_path(root, child),
                    "type": "directory",
                }
            )
        elif child.is_file() and child.suffix.lower() in AUDIO_EXTENSIONS:
            rows.append(
                {
                    "name": child.name,
                    "rel": relative_path(root, child),
                    "type": "audio",
                }
            )
    return rows


def track_detail(root: Path, rel: str) -> dict[str, Any]:
    path = safe_join(root, rel)
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError("not an audio file")

    audio = MutagenFile(str(path), easy=False)
    tags = normalize_tags(getattr(audio, "tags", None))
    info = audio_info(audio)
    lyrics = lyrics_info(tags)
    warnings = []
    if not tags:
        warnings.append("no readable tags")
    if not lyrics["has_lyrics"]:
        warnings.append("no embedded lyrics")
    return {
        "relative_path": relative_path(root, path),
        "file": file_info(path),
        "format": audio.__class__.__name__ if audio else None,
        "audio": info,
        "tags": tags,
        "lyrics": lyrics,
        "cover": bool(cover_bytes(path)[0]),
        "warnings": warnings,
    }


def file_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "suffix": path.suffix.lower(),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }


def audio_info(audio) -> dict[str, Any]:
    info = getattr(audio, "info", None)
    if info is None:
        return {}
    return {
        "length": getattr(info, "length", None),
        "bitrate": getattr(info, "bitrate", None),
        "sample_rate": getattr(info, "sample_rate", None),
        "channels": getattr(info, "channels", None),
        "bits_per_sample": getattr(info, "bits_per_sample", None),
    }


def normalize_tags(tags) -> dict[str, list[str]]:
    if not tags:
        return {}
    normalized: dict[str, list[str]] = {}
    try:
        items = tags.items()
    except Exception:
        return {}

    for key, value in items:
        if is_binary_tag(value):
            continue
        values = value if isinstance(value, list) else [value]
        rendered = []
        for item in values:
            if is_binary_tag(item):
                continue
            text = str(item).strip()
            if text:
                rendered.append(text)
        if rendered:
            normalized[str(key).lower()] = rendered
    return normalized


def is_binary_tag(value: Any) -> bool:
    if isinstance(value, (bytes, bytearray)):
        return True
    if hasattr(value, "data") and isinstance(getattr(value, "data", None), (bytes, bytearray)):
        return True
    return False


def lyrics_info(tags: dict[str, list[str]]) -> dict[str, Any]:
    lyrics = first_tag(tags, "lyrics") or first_tag(tags, "unsyncedlyrics")
    synced = first_tag(tags, "syncedlyrics")
    text = synced or lyrics or ""
    return {
        "has_lyrics": bool(lyrics or synced),
        "has_synced": bool(synced),
        "length": len(text),
        "preview": trim_lines(text, max_lines=80),
    }


def first_tag(tags: dict[str, list[str]], key: str) -> str:
    values = tags.get(key.lower()) or []
    return values[0] if values else ""


def trim_lines(value: str, *, max_lines: int) -> str:
    lines = value.splitlines()
    if len(lines) <= max_lines:
        return value
    return "\n".join(lines[:max_lines] + [f"... {len(lines) - max_lines} more lines"])


def cover_bytes(path: Path) -> tuple[bytes | None, str]:
    try:
        audio = MutagenFile(str(path), easy=False)
    except Exception:
        audio = None

    if isinstance(audio, FLAC) and audio.pictures:
        picture = audio.pictures[0]
        return picture.data, picture.mime or "image/jpeg"

    local = local_cover(path.parent)
    if local:
        return local.read_bytes(), mimetypes.guess_type(str(local))[0] or "image/jpeg"
    return None, "application/octet-stream"


def local_cover(directory: Path) -> Path | None:
    for child in sorted(directory.iterdir()):
        if child.is_file() and child.name.lower() in COVER_FILENAMES:
            return child
    return None


def run_server_in_thread(root: Path, *, host: str = "127.0.0.1", port: int = 8765) -> tuple[ThreadingHTTPServer, str]:
    root = root.expanduser().resolve()
    server = ThreadingHTTPServer((host, port), make_handler(root))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{host}:{server.server_port}/"
