# meta-sonata

[![Tests](https://github.com/sendingE/meta-sonata/actions/workflows/tests.yml/badge.svg)](https://github.com/sendingE/meta-sonata/actions/workflows/tests.yml)
[![macOS App](https://img.shields.io/github/v/release/sendingE/meta-sonata?label=macOS%20app)](https://github.com/sendingE/meta-sonata/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/meta-sonata)](https://pypi.org/project/meta-sonata/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/license-MIT-2f6f73)](https://github.com/sendingE/meta-sonata/blob/main/LICENSE)

**English** | [简体中文](https://github.com/sendingE/meta-sonata/blob/main/README.zh-CN.md)

Meta Sonata is a local-first music metadata workspace. It completes tags,
artwork, and synced lyrics through a standalone macOS app or an automation-ready
CLI, while keeping the original music and long-term identity data under your
control.

## Two Core Advantages

### A Real Standalone macOS App

Drop in one track, inspect the proposed metadata, then drag the enriched copy
back to Finder. The source file is never modified. The same app can open a local
music folder as a read-only library for browsing tags, artwork, technical
details, source IDs, and full lyrics.

The app is self-contained: no Python, terminal, or separate web service is
required. It supports English, Simplified Chinese, Traditional Chinese,
Japanese, Korean, French, German, Spanish, and Brazilian Portuguese.

### A Local Data Model, Not a Pile of Sidecar Files

Meta Sonata separates data by lifecycle instead of forcing everything into the
audio file or one opaque database:

| Layer | What it owns | Lifecycle |
| --- | --- | --- |
| Audio file | Portable tags, MusicBrainz IDs, artwork, and lyrics | Travels with the music |
| Local catalog | Library roots, relative file paths, entities, external IDs, aliases, and decisions | Durable per-user data; rebuildable from files |
| Provider cache | Responses from MusicBrainz and other services | Disposable; safe to delete |

This gives the app a durable foundation for larger libraries and future
confirmation workflows without making the database the only copy of your music
identity. If the catalog or a third-party service fails, local browsing and file
processing continue.

## Get the macOS App

[Download the latest Apple-silicon DMG](https://github.com/sendingE/meta-sonata/releases/latest).

The current DMG is ad-hoc signed and not Apple-notarized, so macOS may require
Control-click → **Open** on first launch. The app follows the copy-only rule:
enrichment output is a separate file and the original remains untouched.

Build the `.app` and `.dmg` locally with:

```bash
./scripts/build_macos_release.sh
```

For notarized distribution, set `MACOS_SIGN_IDENTITY` to a Developer ID identity
and complete Apple's notarization flow.

## CLI Quick Start

```bash
pipx install meta-sonata
```

Or install it with `uv`:

```bash
uv tool install meta-sonata
```

Preview the metadata Meta Sonata finds. Nothing is written:

```bash
meta-sonata enrich "/music/album"
```

Fetch and write metadata, cover art, and lyrics in one step:

```bash
meta-sonata enrich "/music/album" --write
```

Both commands accept an album folder or a larger music directory. Existing tags,
filenames, and folder structure are trusted first; online sources fill the gaps.

![meta-sonata CLI preview and write workflow](https://raw.githubusercontent.com/sendingE/meta-sonata/main/docs/assets/cli-demo.gif)

## Why Meta Sonata?

- **Local first:** existing tags, folder names, and track structure anchor the match.
- **Source-safe:** the macOS app enriches a copy; CLI writes require an explicit flag.
- **Conservative:** track count, duration, live/studio, and ambiguity checks prevent risky writes.
- **Complete:** metadata, cover art, and synced lyrics in one command.
- **Resilient:** provider failures become warnings while local work and other sources continue.
- **Automation-ready:** dry runs, external incremental state, recursive discovery, and JSON audit plans.

Typical output:

```text
scan: root=/music/album files=12 album_groups=1 loose_tracks=0 max_depth=3
resolve: 1/1 /music/album
lyrics: 1/1 /music/album
dry run: 1 plan(s)
- album: Artist / Album: artist=Artist  album=Album  year=2006  tracks=12  confidence=0.96  lyrics=11/12
nothing written; pass --write to apply
```

`enrich` enables metadata lookup, cover lookup, and lyrics by default. It scans
up to three directory levels; use `--max-depth N` or `--recursive` when needed.

## What It Can Fill

| Area | Fields |
| --- | --- |
| Identity | title, artist, album artist, album, track/disc number |
| Release | date, label, catalog number, barcode, release type |
| Sources | MusicBrainz artist, recording, release, release-group, and release-track IDs; provenance tags |
| Media | embedded cover art, synced LRC, plain lyrics |

Album metadata sources: **MusicBrainz**, **iTunes**, and **NetEase**.

Lyric sources: **QQ Music**, **NetEase**, **KuGou**, **KuWo**, and **Migu**.

```bash
meta-sonata sources
```

## Put It in a Pipeline

Run it after download/extraction/CUE splitting and before the final library sync:

```bash
meta-sonata enrich "/staging/new-music" \
  --changed-only \
  --state-dir "/var/lib/meta-sonata" \
  --write
```

Incremental state stays outside music folders. No marker files are added to albums.

## Optional Metadata Browser

```bash
meta-sonata web "/music" --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/` to browse audio files, core tags, source IDs,
technical details, covers, and embedded lyrics. The web UI has no write endpoints.

![meta-sonata read-only metadata browser](https://raw.githubusercontent.com/sendingE/meta-sonata/main/docs/assets/web-ui.png)

_Shown with CC-licensed audio and artwork from Nine Inch Nails' The Slip. See the [asset attribution](https://github.com/sendingE/meta-sonata/blob/main/docs/assets/ATTRIBUTION.md)._

## Storage and Failure Behavior

Embedded file tags remain the portable source of truth. The macOS app builds a
rebuildable local catalog in the background for cross-folder lookup, match
history, and future confirmation workflows. Third-party responses live in a
separate disposable cache:

- Durable catalog: `~/Library/Application Support/com.sendinge.meta-sonata/catalog.sqlite3`
- API cache: `~/Library/Caches/com.sendinge.meta-sonata/provider-cache.sqlite3`

Deleting the API cache does not affect music or catalog data. Catalog failures
also never block browsing or enrichment. Real MusicBrainz network requests are
limited to one per second across CLI, macOS, and test code paths. Every
third-party failure degrades to a warning while local processing and other
providers continue.

## Safety

- Every write command is a dry run unless `--write` is present.
- Low-confidence lyrics and ambiguous release identities are skipped.
- Mixed loose tracks are not forced into a fake album.
- Real libraries can be protected with `META_SONATA_PROTECTED_PATHS`.
- Tests generate silent FLAC files; no copyrighted media is committed.

## More

- [Detailed guide](https://github.com/sendingE/meta-sonata/blob/main/docs/guide.md)
- [Changelog](https://github.com/sendingE/meta-sonata/blob/main/CHANGELOG.md)
- [Public test-fixture policy](https://github.com/sendingE/meta-sonata/blob/main/tests/README.md)
- [MIT License](https://github.com/sendingE/meta-sonata/blob/main/LICENSE)

Python 3.9+ is supported. The project is currently an early `0.2.x` release;
unofficial provider endpoints may change or be rate-limited.
