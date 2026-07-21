# Detailed Guide

[Back to README](../README.md) | [简体中文](../README.zh-CN.md)

`meta-sonata` is a music metadata automation toolkit for album libraries,
staging folders, and sync pipelines. It is CLI-first, with a local read-only
web browser for reviewing files and embedded metadata.

The project is designed for a conservative automation loop:

1. infer what it can from local folder names, file names, and existing tags;
2. scrape online metadata only to confirm or fill missing fields;
3. score candidates before writing;
4. write only when `--write` is passed;
5. keep incremental state outside music folders.

## Features

- Scan album folders without writing files.
- Build JSON audit plans before tagging.
- Resolve album metadata from MusicBrainz, iTunes, and NetEase.
- Prefer local inference over scraped data.
- Penalize live/concert candidates when the local album does not look live.
- Reject concrete release identity when track counts, durations, or otherwise
  strong candidates conflict.
- Embed local covers, or fetch remote album covers when no local cover exists.
- Embed synced lyrics through music-tag-compatible sources.
- Keep pipeline state in an external state directory.
- Refuse writes inside configured protected library roots.

## Install

Install the CLI with `pipx`:

```bash
pipx install meta-sonata
```

Or use `uv`:

```bash
uv tool install meta-sonata
```

Then verify the environment:

```bash
meta-sonata doctor
```

Python 3.9+ is required. Contributors can install a repository checkout in
editable mode with `python3 -m pip install -e .`.

## CLI

Inspect the environment:

```bash
meta-sonata doctor
```

List album metadata and lyric providers:

```bash
meta-sonata sources
```

Scan albums without reading or writing tags:

```bash
meta-sonata scan /path/to/staging --json
```

Resolve online metadata candidates:

```bash
meta-sonata resolve /path/to/staging \
  --sources musicbrainz,itunes,netease
```

Create an audit plan:

```bash
meta-sonata audit /path/to/staging \
  --scrape \
  --out /tmp/meta-sonata-plan.json
```

Enrich album metadata, cover art, and lyrics with one command:

```bash
meta-sonata enrich /path/to/album --write
```

Without `--write`, `enrich` performs a dry run. It enables album scraping and
lyrics by default; use `--no-scrape` or `--no-lyrics` to disable either part.

Album discovery searches up to three directory levels below the input by
default. Recognized `CD1`/`CD2` directories are grouped into their parent.
Audio files are then classified using embedded album identity and track/disc
positions:

- consistent album identity becomes an album group;
- multiple albums in one directory become separate virtual album groups;
- missing, generic, or structurally conflicting album identity becomes loose
  tracks;
- loose tracks use per-track tags and filename inference, and never inherit a
  common album, cover, or album id from their parent directory.

Hidden directories and directory symlinks are not followed.

A dry run reports the classification before showing per-unit metadata plans:

```text
scan: root=/music files=2000 album_groups=126 loose_tracks=318 max_depth=3
resolve: 1/127 /music/mixed
loose: 127/127 /music/mixed
dry run: 127 plan(s)
```

Control album discovery depth explicitly:

```bash
# Only PATH itself
meta-sonata enrich /path/to/music --max-depth 0

# PATH plus five levels
meta-sonata enrich /path/to/music --max-depth 5

# No depth limit
meta-sonata enrich /path/to/music --recursive
```

Depth controls album discovery, not traversal inside a recognized `CD1`/`CD2`
directory. Always review the dry-run output before using `--write` on an
unstructured collection.

Dry-run tagging:

```bash
meta-sonata tag /path/to/staging \
  --scrape \
  --lyrics
```

Write tags:

```bash
meta-sonata tag /path/to/staging \
  --scrape \
  --lyrics \
  --write
```

Run the read-only metadata browser:

```bash
meta-sonata web /path/to/staging
```

## Scraping

Album metadata scraping is album-first. Local folder/file inference and existing
tags are the anchor; remote providers fill missing or richer fields such as:

- release date
- label
- catalog number
- barcode
- MusicBrainz release and track ids
- track titles that could not be parsed locally
- remote album cover when no local `Cover.jpg`, `Folder.jpg`, or `Front.jpg`
  exists

Implemented album metadata providers:

- `musicbrainz`, with Cover Art Archive release/release-group covers
- `itunes`, via the public iTunes Search API
- `netease`, via NetEase web endpoints

Planned album metadata providers aligned with music-tag (some are already
available as lyric sources):

- `qmusic`
- `kugou`
- `kuwo`
- `migu`
- `spotify`
- `acoustid`
- `ximalaya`
- `smart_tag` aggregation behavior

## Lyrics

Lyrics are enabled by default with `enrich`; use `--no-lyrics` to disable them.
The lower-level `tag` command keeps lyrics opt-in with `--lyrics` because lyric
text has different copyright and source-license risks from factual release
metadata.

The lyric workflow follows music-tag's plugin model:

1. search a platform song candidate;
2. score it against the local track title, artist, and album;
3. fetch lyrics by the selected platform song id;
4. skip low-scoring candidates instead of writing risky matches.

Implemented lyric sources:

- `qmusic`
- `netease`
- `kugou`
- `kuwo`
- `migu`

Default lyric settings:

```bash
meta-sonata tag /path/to/staging \
  --scrape \
  --lyrics \
  --lyrics-source qmusic,netease,kugou,kuwo,migu \
  --lyrics-mode prefer-synced
```

`prefer-synced` writes synced LRC text to both `lyrics` and `syncedlyrics` for
player compatibility. `--lyrics-mode both` also writes plain text to
`unsyncedlyrics`. Existing synced LRC text found only in `lyrics` is migrated to
`syncedlyrics` without fetching it again. Other existing embedded lyrics are
skipped unless `--lyrics-overwrite` is passed.

## Safety

No personal library paths are hard-coded. To protect a real library from
accidental writes, set `META_SONATA_PROTECTED_PATHS` before running write
commands:

```bash
export META_SONATA_PROTECTED_PATHS="/path/to/real/library:/another/library"
```

Run experiments against copied fixtures or staging directories, not directly
against a real library.

## Incremental State

`meta-sonata` keeps incremental state outside music folders. By default it uses:

1. `$META_SONATA_STATE_DIR`
2. the platform's per-user state directory via `platformdirs`

Typical defaults are `$XDG_STATE_HOME/meta-sonata` (or
`~/.local/state/meta-sonata`) on Linux, `~/Library/Application Support/meta-sonata`
on macOS, and `%LOCALAPPDATA%\meta-sonata` on Windows.

Pipeline example:

```bash
meta-sonata enrich /path/to/staging \
  --changed-only \
  --state-dir /path/to/meta-sonata-state \
  --write
```

For pipelines that create a marker file after upstream processing, use:

```bash
meta-sonata enrich /path/to/staging \
  --changed-only \
  --state-dir /path/to/meta-sonata-state \
  --pipeline-marker-since 1780000000 \
  --write
```

## Automation

A typical sync pipeline should run `meta-sonata` after download/extraction/CUE
splitting and before copying files to the final library:

```bash
meta-sonata tag /path/to/staging \
  --scrape \
  --lyrics \
  --changed-only \
  --state-dir /path/to/meta-sonata-state \
  --write
```

Useful environment toggles for wrapper scripts:

- `META_SONATA_ENABLED=0` to skip metadata enrichment.
- `META_SONATA_LYRICS_ENABLED=0` to skip lyric embedding.
- `META_SONATA_SOURCES=musicbrainz,itunes,netease` to choose album metadata
  providers.
- `META_SONATA_LYRICS_SOURCES=qmusic,netease,kugou,kuwo,migu` to choose lyric
  providers.
- `META_SONATA_LYRICS_MODE=prefer-synced` to choose embedded lyric tags.
- `META_SONATA_STATE_DIR=/path/to/state` to keep incremental state outside
  music folders.

## Web UI

The first web UI is a local, read-only metadata browser. It is meant for
checking the result of automation, not replacing the CLI workflow.

```bash
meta-sonata web /path/to/staging --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/` and browse the file tree. Selecting an audio file
shows:

- file size, modified time, duration, bitrate, sample rate, and channels;
- core tags such as title, artist, album, track number, and date;
- source tags such as MusicBrainz ids, lyric source, and lyric score;
- embedded or local cover art;
- lyric presence, synced/plain status, and a preview;
- all readable tags from the audio container.

The web UI has no write endpoints in this MVP.

## Tests

GitHub Actions runs the complete suite on Linux with Python 3.9 and 3.13, plus
macOS and Windows with Python 3.13. CLI integration tests generate temporary
silent FLAC files with FFmpeg and mock remote responses, so the suite does not
depend on copyrighted fixtures or live metadata services.

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests are designed for a public repository:

- no third-party audio, cover art, cue sheets, or scans are committed;
- integration-style tests generate temporary audio only when needed;
- metadata examples use public-domain work titles and composer names.

See [tests/README.md](../tests/README.md) for the fixture policy.

## Current Limits

- Audio fingerprinting is not implemented yet.
- Some providers use unofficial web endpoints and can be rate-limited or change.
- Lyrics are written only when a candidate clears the scorer threshold.
- The web UI is read-only; enrichment and automation remain CLI workflows.
