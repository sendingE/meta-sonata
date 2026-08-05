from __future__ import annotations

import json
import base64
import mimetypes
import posixpath
import re
import threading
import urllib.parse
from datetime import datetime
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from .catalog import CatalogDatabase, sync_library_in_background, try_default_catalog
from .lyrics import embedded_lyrics
from .models import AUDIO_EXTENSIONS, COVER_FILENAMES
from .scanner import is_ignored_name


ASSETS_DIR = Path(__file__).with_name("assets")
LOCALIZATION_DIR = ASSETS_DIR / "locales"
SUPPORTED_LOCALES = ("en", "zh-Hans", "zh-Hant", "ja", "ko", "fr", "de", "es", "pt-BR")
BRAND_ICON_SVG = (ASSETS_DIR / "MetaSonata.svg").read_text(encoding="utf-8")


def resolve_locale(value: str | None) -> str:
    normalized = (value or "").strip().replace("_", "-").lower()
    if normalized.startswith("zh"):
        if any(part in normalized for part in ("hant", "-tw", "-hk", "-mo")):
            return "zh-Hant"
        return "zh-Hans"
    if normalized == "pt" or normalized.startswith("pt-"):
        return "pt-BR"
    for locale in SUPPORTED_LOCALES:
        lowered = locale.lower()
        if normalized == lowered or normalized.startswith(f"{lowered}-"):
            return locale
    return "en"


@lru_cache(maxsize=len(SUPPORTED_LOCALES))
def localized_messages(locale: str) -> dict[str, str]:
    resolved = resolve_locale(locale)
    fallback = json.loads((LOCALIZATION_DIR / "en.json").read_text(encoding="utf-8"))
    if resolved == "en":
        return fallback
    translated = json.loads((LOCALIZATION_DIR / f"{resolved}.json").read_text(encoding="utf-8"))
    return {**fallback, **translated}


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>meta-sonata</title>
  <script>if (new URLSearchParams(location.search).has("embedded")) document.documentElement.classList.add("embedded");</script>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">
          <img src="/static/meta-sonata.svg" alt="">
        </div>
        <div class="brand-copy">
          <strong><span>meta</span><b>-</b><span>sonata</span></strong>
          <span data-i18n="web.brand.subtitle">library inspector</span>
        </div>
      </div>
      <div class="topbar-context">
        <span id="root-label" class="root-path"></span>
        <span class="status-pill"><span class="status-dot"></span><span data-i18n="web.status.local_readonly">Local / Read Only</span></span>
      </div>
    </header>
    <main class="workspace">
      <aside class="sidebar" aria-label="Library tree" data-i18n-aria-label="web.aria.library_tree">
        <div class="sidebar-heading">
          <div>
            <div class="eyebrow" data-i18n="web.workspace">Workspace</div>
            <h2 data-i18n="web.library">Library</h2>
          </div>
          <button id="refresh-tree" class="action-button" type="button" data-i18n="web.refresh">Refresh</button>
        </div>
        <div id="tree" class="tree"><div class="tree-note" data-i18n="web.loading_library">Loading library…</div></div>
        <div class="sidebar-footer">
          <span id="visible-count">0 items</span>
          <span data-i18n="web.local_files">Local files</span>
        </div>
      </aside>
      <section class="viewer" aria-live="polite">
        <div id="empty-state" class="empty-state">
          <div class="empty-mark" aria-hidden="true">
            <img src="/static/meta-sonata.svg" alt="">
          </div>
          <h1 data-i18n="web.select_track">Select a Track</h1>
          <p data-i18n="web.select_track_hint">Choose an audio file to inspect its embedded metadata, artwork, and lyrics.</p>
        </div>
        <div id="track-view" class="track-view hidden">
          <section class="track-hero">
            <div class="cover-frame">
              <img id="cover" alt="">
              <div id="cover-empty" class="cover-empty">
                <div class="placeholder-disc" aria-hidden="true">
                  <span class="placeholder-label"></span>
                </div>
                <span class="placeholder-caption" data-i18n="web.no_artwork">No Artwork</span>
              </div>
            </div>
            <div class="track-title-block">
              <div id="track-path" class="path-line"></div>
              <div class="track-kicker" data-i18n="web.now_inspecting">Now Inspecting</div>
              <h1 id="track-title"></h1>
              <div id="track-subtitle" class="subtitle"></div>
              <div id="track-badges" class="badges"></div>
              <div class="quick-stats">
                <div><span data-i18n="web.stat.format">Format</span><strong id="stat-format">-</strong></div>
                <div><span data-i18n="web.stat.duration">Duration</span><strong id="stat-duration">-</strong></div>
                <div><span data-i18n="web.stat.track">Track</span><strong id="stat-track">-</strong></div>
              </div>
            </div>
          </section>
          <nav class="view-tabs" aria-label="Metadata views" data-i18n-aria-label="web.aria.metadata_views">
            <button class="view-tab active" type="button" data-view="overview"><span data-i18n="web.overview">Overview</span></button>
            <button class="view-tab" type="button" data-view="raw"><span data-i18n="web.all_tags">All Tags</span> <span id="tag-count"></span></button>
          </nav>
          <div id="overview-view" class="metadata-view">
            <section class="detail-grid">
            <article class="panel file-panel">
              <div class="panel-heading"><h3 data-i18n="web.file">File</h3><span data-i18n="web.technical">Technical</span></div>
              <dl id="file-info" class="kv"></dl>
            </article>
            <article class="panel core-panel">
              <div class="panel-heading"><h3 data-i18n="web.core_metadata">Core Metadata</h3><span data-i18n="web.embedded">Embedded</span></div>
              <dl id="core-tags" class="kv"></dl>
            </article>
            <article class="panel source-panel">
              <div class="panel-heading"><h3 data-i18n="web.provenance">Provenance</h3><span data-i18n="web.sources">Sources</span></div>
              <dl id="source-tags" class="kv"></dl>
            </article>
            <article class="panel lyrics-panel">
              <div class="panel-heading"><h3 data-i18n="web.lyrics">Lyrics</h3><span id="lyrics-format">Embedded</span></div>
              <dl id="lyrics-summary" class="kv lyrics-summary"></dl>
              <pre id="lyrics-preview" class="lyrics-preview"></pre>
            </article>
            </section>
          </div>
          <section id="raw-view" class="metadata-view hidden panel all-tags-panel">
            <div class="panel-heading"><h3 data-i18n="web.all_tags">All Tags</h3><span data-i18n="web.raw_values">Raw Values</span></div>
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
/* Refined application shell. Kept dependency-free for offline library use. */
:root {
  --bg: #f4f4f2;
  --panel: #ffffff;
  --sidebar: #171817;
  --line: #dedfdb;
  --line-strong: #c9cac5;
  --text: #171817;
  --muted: #686b67;
  --faint: #90938e;
  --accent: #3457d5;
  --accent-strong: #2644b8;
  --accent-weak: #e7ebff;
  --signal: #c9f16f;
  --warm: #d34f32;
  --warm-weak: #fff0eb;
  --shadow: 0 1px 2px rgba(17, 18, 17, 0.06), 0 10px 32px rgba(17, 18, 17, 0.05);
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
  line-height: 1.45;
  letter-spacing: 0;
}

button {
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
}

button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.app-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  min-height: 66px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #111211;
  border-bottom: 1px solid #272927;
}

.brand {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 11px;
}

.brand-mark {
  width: 37px;
  height: 37px;
  flex: 0 0 auto;
}

.brand-mark img,
.empty-mark img {
  width: 100%;
  height: 100%;
  display: block;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.brand-copy strong {
  color: #ffffff;
  font-size: 15px;
  line-height: 1.25;
}

.brand-copy strong span {
  color: inherit;
}

.brand-copy strong b {
  color: var(--signal);
  font-weight: inherit;
}

.brand-copy > span {
  color: #8f948f;
  font-size: 11px;
}

.topbar-context {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
  min-width: 0;
}

.root-path {
  max-width: min(46vw, 680px);
  color: #9a9e99;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 28px;
  border: 1px solid var(--signal);
  border-radius: 4px;
  background: var(--signal);
  color: #1a2412;
  padding: 5px 9px;
  font-size: 11px;
  font-weight: 650;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #263719;
}

.workspace {
  display: grid;
  grid-template-columns: minmax(286px, 316px) minmax(0, 1fr);
  min-height: calc(100vh - 67px);
}

.embedded .topbar {
  display: none;
}

.embedded .workspace {
  min-height: 100vh;
}

.sidebar {
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #272927;
  background: var(--sidebar);
}

.sidebar-heading {
  min-height: 86px;
  padding: 18px 16px 14px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #2c2e2c;
}

.eyebrow {
  margin-bottom: 2px;
  color: #797e79;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.sidebar-heading h2 {
  margin: 0;
  color: #ffffff;
  font-size: 19px;
  line-height: 1.2;
}

.action-button {
  min-height: 32px;
  padding: 5px 10px;
  border: 1px solid #414441;
  border-radius: 4px;
  background: #232523;
  color: #eceeeb;
  font-size: 12px;
  font-weight: 650;
  box-shadow: 0 1px 1px rgba(23, 32, 31, 0.04);
}

.action-button:hover {
  border-color: #616561;
  background: #2c2f2c;
}

.tree {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 10px;
}

.tree-row {
  position: relative;
  min-height: 36px;
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 4px;
  padding: 6px 9px;
  color: #b9bdb8;
  font-size: 13px;
  text-align: left;
}

.tree-row:hover {
  background: #242624;
}

.tree-row.selected {
  background: var(--accent);
  color: #ffffff;
  font-weight: 650;
}

.tree-row.selected::before {
  display: none;
}

.tree-row.root-row {
  font-weight: 700;
  color: #ffffff;
}

.tree-icon {
  position: relative;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  color: transparent;
  font-size: 0;
}

.tree-icon.directory::before {
  content: "";
  position: absolute;
  width: 6px;
  height: 6px;
  left: 4px;
  top: 5px;
  border-right: 1.5px solid #8d928d;
  border-bottom: 1.5px solid #8d928d;
  transform: rotate(-45deg);
  transition: transform 120ms ease, top 120ms ease;
}

.tree-icon.directory.open::before {
  top: 3px;
  transform: rotate(45deg);
}

.file-extension {
  width: 32px;
  flex: 0 0 32px;
  color: #858a85;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 9px;
  font-weight: 700;
  text-align: center;
}

.tree-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-row.selected .file-extension {
  color: #dce3ff;
}

.tree-row.selected .tree-icon.directory::before {
  border-color: #ffffff;
}

.tree-children {
  margin-left: 14px;
  border-left: 1px solid #303330;
  padding-left: 2px;
}

.tree-note {
  padding: 10px;
  font-size: 12px;
  color: #858a85;
}

.sidebar-footer {
  min-height: 42px;
  padding: 0 16px 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid #2c2e2c;
  color: #767b76;
  font-size: 11px;
}

.viewer {
  min-width: 0;
  overflow: auto;
  padding: 34px clamp(24px, 4vw, 58px) 56px;
}

@media (min-width: 901px) {
  html,
  body {
    height: 100%;
    overflow: hidden;
  }

  .app-shell {
    height: 100%;
    min-height: 0;
  }

  .workspace {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  .embedded .workspace {
    min-height: 0;
  }

  .sidebar,
  .viewer {
    min-height: 0;
  }

  .tree,
  .viewer {
    overscroll-behavior: contain;
  }
}

.track-view {
  width: min(1220px, 100%);
  margin: 0 auto;
}

.empty-state {
  width: min(460px, 100%);
  margin: 0 auto;
  padding: clamp(80px, 16vh, 180px) 24px 40px;
  text-align: center;
  color: var(--muted);
}

.empty-mark {
  width: 60px;
  height: 60px;
  margin: 0 auto 18px;
}

.empty-state h1 {
  margin-bottom: 7px;
  font-size: 24px;
}

.empty-state p {
  margin: 0;
  line-height: 1.6;
}

.hidden {
  display: none !important;
}

.track-hero {
  display: grid;
  grid-template-columns: 210px minmax(0, 1fr);
  gap: 36px;
  align-items: center;
  margin: 0 0 24px;
  padding: 2px 0 34px;
  border-bottom: 1px solid var(--line);
}

.cover-frame {
  width: 210px;
  aspect-ratio: 1;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #e7e8e3;
  border: 1px solid #d2d4ce;
  border-radius: 5px;
  color: var(--text);
  box-shadow: 14px 14px 0 #dfe1da;
}

.cover-frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cover-empty {
  position: relative;
  width: 100%;
  height: 100%;
  padding: 17px;
  display: grid;
  place-items: center;
  overflow: hidden;
  background: #eceee8;
}

.cover-empty::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(90deg, transparent 0 50%, rgba(23, 24, 23, 0.045) 50% 50.8%, transparent 50.8%),
    linear-gradient(0deg, transparent 0 50%, rgba(23, 24, 23, 0.045) 50% 50.8%, transparent 50.8%);
}

.placeholder-disc {
  position: relative;
  width: 74%;
  aspect-ratio: 1;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: repeating-radial-gradient(circle, #292b28 0 2px, #1d1f1d 3px 6px);
  box-shadow: 0 16px 28px rgba(23, 24, 23, 0.18);
}

.placeholder-label {
  width: 35%;
  aspect-ratio: 1;
  border: 7px solid var(--signal);
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 3px #1d1f1d;
}

.placeholder-caption {
  position: absolute;
  right: 13px;
  bottom: 10px;
  color: #777b75;
  font-size: 9px;
  font-weight: 800;
  line-height: 1;
  text-transform: uppercase;
}

.placeholder-caption {
  letter-spacing: 0;
}

.path-line {
  margin-bottom: 9px;
  color: var(--faint);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  overflow-wrap: anywhere;
}

.track-kicker {
  margin: 0 0 7px;
  color: var(--accent);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.track-title-block h1 {
  max-width: 850px;
  margin-bottom: 8px;
  font-size: clamp(34px, 4vw, 54px);
  line-height: 1.08;
  overflow-wrap: anywhere;
}

.subtitle {
  color: #555954;
  font-size: 17px;
}

.badges {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.badge {
  min-height: 26px;
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 4px;
  padding: 3px 9px;
  font-size: 11px;
  font-weight: 650;
}

.badge.ok {
  border-color: #bdc8f6;
  color: #2744b3;
  background: #edf0ff;
}

.badge.warn {
  border-color: #efb2a3;
  color: #9f351f;
  background: var(--warm-weak);
}

.quick-stats {
  margin-top: 22px;
  display: flex;
  flex-wrap: wrap;
  gap: 22px;
}

.quick-stats div {
  min-width: 76px;
  padding-left: 10px;
  border-left: 2px solid var(--accent);
  display: flex;
  flex-direction: column;
}

.quick-stats span {
  color: var(--faint);
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
}

.quick-stats strong {
  margin-top: 2px;
  font-size: 13px;
}

.view-tabs {
  min-height: 46px;
  margin-bottom: 18px;
  display: flex;
  align-items: flex-end;
  gap: 22px;
  border-bottom: 1px solid var(--line-strong);
}

.view-tab {
  position: relative;
  min-height: 46px;
  padding: 0;
  color: #737772;
  font-size: 13px;
  font-weight: 700;
}

.view-tab:hover,
.view-tab.active {
  color: var(--text);
}

.view-tab.active::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 3px;
  background: var(--accent);
}

.view-tab span {
  margin-left: 4px;
  color: var(--faint);
  font-size: 10px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 14px;
}

.file-panel,
.source-panel {
  grid-column: span 5;
}

.core-panel,
.lyrics-panel {
  grid-column: span 7;
}

.panel {
  padding: 20px;
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--panel);
  box-shadow: var(--shadow);
}

.panel-heading {
  min-height: 28px;
  margin-bottom: 14px;
  padding-bottom: 11px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid #ecece8;
}

.panel-heading h3 {
  margin: 0;
  font-size: 14px;
  line-height: 1.3;
}

.panel-heading span {
  color: var(--faint);
  font-size: 10px;
  font-weight: 650;
}

.kv {
  display: grid;
  grid-template-columns: minmax(96px, 0.34fr) minmax(0, 1fr);
  gap: 9px 14px;
  margin: 0;
}

.kv dt {
  color: #747873;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.kv dd {
  margin: 0;
  color: #252725;
  font-size: 12px;
  font-weight: 550;
  overflow-wrap: anywhere;
}

.empty-value {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--faint);
  font-size: 12px;
}

.lyrics-summary {
  grid-template-columns: repeat(2, minmax(78px, 0.34fr) minmax(0, 1fr));
  gap: 7px 10px;
}

.lyrics-preview {
  min-height: 84px;
  max-height: 260px;
  overflow: auto;
  margin-top: 14px;
  border-color: #dedfdb;
  background: #f6f6f3;
  padding: 13px;
  color: #34413e;
  font-size: 11px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.all-tags-panel {
  margin-top: 16px;
}

.tag-table {
  display: grid;
  grid-template-columns: minmax(150px, 0.24fr) minmax(0, 1fr);
  border-top: 0;
}

.tag-key,
.tag-value {
  padding: 9px 0;
  border-bottom-color: #edf0ee;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.tag-key {
  color: #6d7875;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

@media (max-width: 900px) {
  .topbar {
    min-height: 58px;
    padding: 0 16px;
  }

  .root-path {
    display: none;
  }

  .workspace {
    grid-template-columns: 1fr;
    min-height: calc(100vh - 59px);
  }

  .sidebar {
    max-height: 310px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .sidebar-heading {
    min-height: 68px;
    padding: 12px 16px;
  }

  .tree {
    min-height: 150px;
  }

  .viewer {
    padding: 22px 18px 40px;
  }
}

@media (max-width: 620px) {
  .brand-copy > span,
  .sidebar-footer {
    display: none;
  }

  .track-hero,
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .file-panel,
  .core-panel,
  .source-panel,
  .lyrics-panel {
    grid-column: 1;
  }

  .track-hero {
    gap: 18px;
    align-items: start;
  }

  .cover-frame {
    width: 132px;
  }

  .placeholder-label {
    border-width: 5px;
  }

  .track-title-block h1 {
    font-size: 29px;
  }

  .lyrics-summary {
    grid-template-columns: minmax(88px, 0.4fr) minmax(0, 1fr);
  }

  .tag-table {
    grid-template-columns: 1fr;
  }

  .tag-key {
    padding-bottom: 2px;
    border-bottom: 0;
  }

  .tag-value {
    padding-top: 2px;
  }
}
"""


JS = r"""
const state = {
  root: null,
  selectedRel: null,
  loaded: new Map(),
  expanded: new Set([""]),
  locale: "en",
  messages: {},
};

const el = (id) => document.getElementById(id);

function t(key, values = {}) {
  let value = state.messages[key] || key;
  for (const [name, replacement] of Object.entries(values)) {
    value = value.replaceAll(`{${name}}`, String(replacement));
  }
  return value;
}

function plural(base, count) {
  return t(`${base}.${count === 1 ? "one" : "other"}`, { count });
}

function applyTranslations() {
  document.documentElement.lang = state.locale;
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
    node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
  });
}

async function loadLocale() {
  const requested = new URLSearchParams(location.search).get("lang") || navigator.language || "en";
  const payload = await fetchJson(`/api/i18n?lang=${encodeURIComponent(requested)}`);
  state.locale = payload.locale;
  state.messages = payload.messages;
  applyTranslations();
}

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
  const formatted = new Intl.NumberFormat(state.locale, {
    minimumFractionDigits: 0,
    maximumFractionDigits: unit === 0 ? 0 : 1,
  }).format(size);
  return `${formatted} ${units[unit]}`;
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
  el("track-view").classList.add("hidden");
  el("empty-state").classList.remove("hidden");
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
  rootButton.className = "tree-row root-row";
  rootButton.type = "button";
  rootButton.innerHTML = `<span class="tree-icon directory ${state.expanded.has("") ? "open" : ""}"></span><span class="tree-label">${escapeHtml(state.root?.name || t("web.root"))}</span>`;
  rootButton.addEventListener("click", async () => {
    toggleDirectory("");
  });
  tree.appendChild(rootButton);
  const children = document.createElement("div");
  children.className = "tree-children";
  tree.appendChild(children);
  renderChildren("", children);
  updateVisibleCount();
}

function renderChildren(rel, container) {
  const nodes = state.loaded.get(rel) || [];
  if (!nodes.length) {
    const note = document.createElement("div");
    note.className = "tree-note";
    note.textContent = t("web.empty");
    container.appendChild(note);
    return;
  }

  for (const node of nodes) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `tree-row${state.selectedRel === node.rel ? " selected" : ""}`;
    row.style.paddingLeft = "7px";
    const icon = node.type === "directory"
      ? `<span class="tree-icon directory ${state.expanded.has(node.rel) ? "open" : ""}"></span>`
      : `<span class="file-extension">${escapeHtml(fileExtension(node.name))}</span>`;
    row.innerHTML = `${icon}<span class="tree-label">${escapeHtml(node.name)}</span>`;
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

function fileExtension(name) {
  const part = String(name).split(".").pop() || "audio";
  return part.slice(0, 5).toUpperCase();
}

function updateVisibleCount() {
  const nodes = [...state.loaded.values()].flat();
  const unique = new Set(nodes.map((node) => node.rel));
  const tracks = nodes.filter((node) => node.type === "audio" && unique.has(node.rel)).length;
  const label = tracks ? plural("web.count.tracks", tracks) : plural("web.count.items", unique.size);
  el("visible-count").textContent = label;
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
  const title = firstTag(detail.tags, "title") || detail.file.name;
  el("track-title").textContent = title;
  const artist = firstTag(detail.tags, "artist") || firstTag(detail.tags, "albumartist");
  const album = firstTag(detail.tags, "album");
  el("track-subtitle").textContent = [artist, album].filter(Boolean).join(" - ");
  const tagTotal = Object.keys(detail.raw_tags || detail.tags || {}).length;
  el("tag-count").textContent = tagTotal;
  const format = String(detail.file.suffix || detail.format || "").replace(/^\./, "").toUpperCase();
  el("stat-format").textContent = format || "-";
  el("stat-duration").textContent = formatDuration(detail.audio?.length) || "-";
  el("stat-track").textContent = firstTag(detail.tags, "tracknumber") || "-";
  setMetadataView("overview");

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
    "musicinfo_source", "musicbrainz_artistid", "musicbrainz_albumartistid",
    "musicbrainz_recordingid", "musicbrainz_albumid", "musicbrainz_releasegroupid",
    "musicbrainz_trackid",
    "lyrics_source", "lyrics_score",
  ]));
  renderLyrics(detail);
  renderAllTags(detail.raw_tags || detail.tags);
}

function firstTag(tags, key) {
  const values = tags[key] || tags[key.toUpperCase()];
  return Array.isArray(values) && values.length ? values[0] : "";
}

function pickTags(tags, keys) {
  const rows = [];
  for (const key of keys) {
    const value = tags[key] || tags[key.toUpperCase()];
    rows.push([tagLabel(key), formatTagValue(value)]);
  }
  return rows;
}

function tagLabel(key) {
  const labels = {
    title: "field.title",
    artist: "field.artist",
    albumartist: "field.album_artist",
    album: "field.album",
    date: "field.date",
    tracknumber: "field.track",
    discnumber: "field.disc",
    genre: "field.genre",
    label: "field.label",
    catalognumber: "field.catalog",
    barcode: "field.barcode",
    musicinfo_source: "field.metadata_source",
    musicbrainz_artistid: "field.musicbrainz_artist",
    musicbrainz_albumartistid: "field.musicbrainz_release_artist",
    musicbrainz_recordingid: "field.musicbrainz_recording",
    musicbrainz_albumid: "field.musicbrainz_release",
    musicbrainz_releasegroupid: "field.musicbrainz_release_group",
    musicbrainz_trackid: "field.musicbrainz_track",
    lyrics_source: "field.lyrics_source",
    lyrics_score: "field.lyrics_score",
  };
  return labels[key] ? t(labels[key]) : key;
}

function formatTagValue(value) {
  if (!value) return "";
  if (Array.isArray(value)) return value.join("; ");
  return String(value);
}

function fileRows(detail) {
  const info = detail.audio || {};
  const format = String(detail.file.suffix || detail.format || "").replace(/^\./, "").toUpperCase();
  return [
    [t("web.file.name"), detail.file.name],
    [t("web.file.format"), format],
    [t("web.file.size"), formatBytes(detail.file.size)],
    [t("web.file.modified"), detail.file.modified || ""],
    [t("web.file.duration"), formatDuration(info.length)],
    [t("web.file.bitrate"), info.bitrate ? `${Math.round(info.bitrate / 1000)} kbps` : ""],
    [t("web.file.sample_rate"), info.sample_rate ? `${info.sample_rate} Hz` : ""],
    [t("web.file.channels"), info.channels || ""],
  ];
}

function renderDefinitionList(id, rows) {
  const node = el(id);
  node.innerHTML = "";
  const visibleRows = rows.filter(([, value]) => value !== "" && value !== null && value !== undefined);
  if (!visibleRows.length) {
    const empty = document.createElement("dd");
    empty.className = "empty-value";
    empty.textContent = t("web.not_available");
    node.appendChild(empty);
    return;
  }
  for (const [key, value] of visibleRows) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = key;
    dd.textContent = value;
    node.appendChild(dt);
    node.appendChild(dd);
  }
}

function renderBadges(detail) {
  const badges = [];
  if (detail.cover) badges.push(["ok", t("web.artwork")]);
  else badges.push(["warn", t("web.no_artwork")]);
  if (detail.lyrics.has_lyrics) badges.push(["ok", detail.lyrics.has_synced ? t("web.synced_lyrics") : t("web.lyrics")]);
  else badges.push(["warn", t("web.no_lyrics")]);
  if (
    firstTag(detail.tags, "musicbrainz_albumid")
    || firstTag(detail.tags, "musicbrainz_recordingid")
  ) badges.push(["ok", "MusicBrainz"]);
  if (detail.warnings.length) badges.push(["warn", plural("web.warning", detail.warnings.length)]);
  el("track-badges").innerHTML = badges.map(([kind, label]) => `<span class="badge ${kind}">${escapeHtml(label)}</span>`).join("");
}

function renderLyrics(detail) {
  const summary = [
    [t("web.lyrics.has"), detail.lyrics.has_lyrics ? t("web.yes") : t("web.no")],
    [t("web.lyrics.synced"), detail.lyrics.has_synced ? t("web.yes") : t("web.no")],
    [t("web.lyrics.characters"), detail.lyrics.length || ""],
    [t("web.lyrics.source"), firstTag(detail.tags, "lyrics_source")],
  ];
  renderDefinitionList("lyrics-summary", summary);
  el("lyrics-format").textContent = detail.lyrics.has_synced ? t("web.lyrics.synced_lrc") : (detail.lyrics.has_lyrics ? t("web.lyrics.plain_text") : t("web.lyrics.not_found"));
  el("lyrics-preview").textContent = detail.lyrics.preview || t("web.lyrics.no_embedded");
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

function setMetadataView(view) {
  const raw = view === "raw";
  el("overview-view").classList.toggle("hidden", raw);
  el("raw-view").classList.toggle("hidden", !raw);
  document.querySelectorAll(".view-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === view);
  });
}

function summarizeTag(key, value) {
  const text = formatTagValue(value);
  if (/lyrics/i.test(key) && text.length > 180) {
    return t("web.summary.characters", { preview: text.slice(0, 180), count: text.length });
  }
  return text;
}

el("refresh-tree").addEventListener("click", () => {
  loadRoot().catch(showError);
});

document.querySelectorAll(".view-tab").forEach((tab) => {
  tab.addEventListener("click", () => setMetadataView(tab.dataset.view));
});

function showError(error) {
  el("tree").innerHTML = `<div class="tree-note">${escapeHtml(t("web.error.loading"))}</div>`;
}

async function bootstrap() {
  await loadLocale();
  await loadRoot();
}

bootstrap().catch(showError);
"""


def serve_web(root: Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    root = root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    catalog = try_default_catalog()
    handler = make_handler(root, catalog=catalog)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    url = f"http://{host}:{server.server_port}/"
    print(f"meta-sonata web serving {root}")
    print(f"url: {url}")
    if catalog:
        sync_library_in_background(catalog, root)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nmeta-sonata web stopped")
    finally:
        server.server_close()


def make_handler(root: Path, *, catalog: CatalogDatabase | None = None):
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
                elif parsed.path == "/static/meta-sonata.svg":
                    self.send_text(BRAND_ICON_SVG, "image/svg+xml; charset=utf-8")
                elif parsed.path == "/api/i18n":
                    locale = resolve_locale(query_value(parsed.query, "lang"))
                    self.send_json({"locale": locale, "messages": localized_messages(locale)})
                elif parsed.path == "/api/root":
                    self.send_json(
                        {
                            "name": root.name or str(root),
                            "path": str(root),
                            "catalog_enabled": catalog is not None,
                        }
                    )
                elif parsed.path == "/api/children":
                    rel = query_value(parsed.query, "rel")
                    self.send_json({"children": build_child_listing(root, rel)})
                elif parsed.path == "/api/track":
                    rel = query_value(parsed.query, "rel")
                    detail = track_detail(root, rel)
                    if catalog:
                        try:
                            catalog.index_audio_file(
                                root,
                                safe_join(root, rel),
                                tags=detail["tags"],
                            )
                        except Exception:
                            pass
                    self.send_json(detail)
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
    raw_tags = normalize_tags(getattr(audio, "tags", None))
    easy_audio = MutagenFile(str(path), easy=True)
    tags = normalize_tags(getattr(easy_audio, "tags", None))
    for key, value in embedded_lyrics(path).items():
        tags[key] = [value]
    add_canonical_raw_tags(tags, raw_tags)
    info = audio_info(audio)
    lyrics = lyrics_info(tags)
    warnings = []
    if not tags and not raw_tags:
        warnings.append("no readable tags")
    if not lyrics["has_lyrics"]:
        warnings.append("no embedded lyrics")
    return {
        "relative_path": relative_path(root, path),
        "file": file_info(path),
        "format": audio.__class__.__name__ if audio else None,
        "audio": info,
        "tags": tags,
        "raw_tags": raw_tags,
        "lyrics": lyrics,
        "cover": bool(cover_bytes(path)[0]),
        "warnings": warnings,
    }


RAW_TAG_ALIASES = {
    "tit2": "title",
    "tpe1": "artist",
    "tpe2": "albumartist",
    "talb": "album",
    "tdrc": "date",
    "tyer": "date",
    "tcon": "genre",
    "trck": "tracknumber",
    "tpos": "discnumber",
    "txxx:musicinfo_source": "musicinfo_source",
    "txxx:musicbrainz artist id": "musicbrainz_artistid",
    "txxx:musicbrainz_artistid": "musicbrainz_artistid",
    "txxx:musicbrainz album artist id": "musicbrainz_albumartistid",
    "txxx:musicbrainz_albumartistid": "musicbrainz_albumartistid",
    "txxx:musicbrainz album id": "musicbrainz_albumid",
    "txxx:musicbrainz_albumid": "musicbrainz_albumid",
    "txxx:musicbrainz release group id": "musicbrainz_releasegroupid",
    "txxx:musicbrainz_releasegroupid": "musicbrainz_releasegroupid",
    "txxx:musicbrainz recording id": "musicbrainz_recordingid",
    "txxx:musicbrainz_recordingid": "musicbrainz_recordingid",
    "txxx:musicbrainz track id": "musicbrainz_trackid",
    "txxx:musicbrainz_trackid": "musicbrainz_trackid",
    "txxx:lyrics_source": "lyrics_source",
    "txxx:lyrics_score": "lyrics_score",
}


def add_canonical_raw_tags(
    tags: dict[str, list[str]],
    raw_tags: dict[str, list[str]],
) -> None:
    for raw_key, canonical_key in RAW_TAG_ALIASES.items():
        if canonical_key not in tags and raw_key in raw_tags:
            tags[canonical_key] = raw_tags[raw_key]


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

    if path.suffix.lower() == ".mp3":
        try:
            frames = ID3(str(path)).getall("APIC")
        except Exception:
            frames = []
        if frames:
            return frames[0].data, frames[0].mime or "image/jpeg"

    if isinstance(audio, MP4):
        covers = (audio.tags or {}).get("covr") or []
        if covers:
            image = covers[0]
            mime = "image/png" if getattr(image, "imageformat", None) == 14 else "image/jpeg"
            return bytes(image), mime

    picture_tags = (getattr(audio, "tags", None) or {}).get("metadata_block_picture") if audio else None
    if picture_tags:
        try:
            from mutagen.flac import Picture

            picture = Picture(base64.b64decode(picture_tags[0]))
            return picture.data, picture.mime or "image/jpeg"
        except Exception:
            pass

    local = local_cover(path.parent)
    if local:
        return local.read_bytes(), mimetypes.guess_type(str(local))[0] or "image/jpeg"
    return None, "application/octet-stream"


def local_cover(directory: Path) -> Path | None:
    for child in sorted(directory.iterdir()):
        if child.is_file() and child.name.lower() in COVER_FILENAMES:
            return child
    return None


def run_server_in_thread(
    root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    catalog: CatalogDatabase | None = None,
) -> tuple[ThreadingHTTPServer, str]:
    root = root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)
    server = ThreadingHTTPServer((host, port), make_handler(root, catalog=catalog))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if catalog:
        sync_library_in_background(catalog, root)
    return server, f"http://{host}:{server.server_port}/"
