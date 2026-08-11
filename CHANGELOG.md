# Changelog

All notable changes to meta-sonata are documented here.

## 0.2.1 - 2026-08-11

- Sign the macOS app and disk image with a pinned Developer ID certificate.
- Notarize and staple both the app and disk image for trusted direct distribution.

## 0.2.0 - 2026-08-05

- Add a native copy-only macOS app for single-track enrichment and read-only
  library browsing in nine languages.
- Add a durable per-user SQLite catalog while keeping embedded file tags as the
  portable source of truth.
- Add a separate disposable SQLite cache for third-party responses, stale-cache
  fallback, and process-wide MusicBrainz rate limiting at one request per second.
- Isolate metadata, lyrics, and cover provider failures so local processing and
  remaining providers continue.
- Preserve distinct MusicBrainz artist, recording, release, release-group, and
  release-track identities across matching, writing, and browsing.
- Add MP3 and M4A tag writing, reversible field edits, localized UI resources,
  and expanded regression coverage.

## 0.1.2 - 2026-07-21

- Fix images and documentation links in the PyPI project description.
- Make the CLI demonstration independent of a specific patch version.

## 0.1.1 - 2026-07-21

- Redesign the read-only metadata browser for desktop and mobile.
- Add the structured-S project mark and a neutral missing-artwork treatment.
- Lead the English and Chinese READMEs with the two core CLI commands.
- Fix the platform state-directory test on Windows.
- Add automated PyPI publishing for tagged releases.

## 0.1.0 - 2026-07-20

- Initial public release.
- Add local-first album discovery, online metadata matching, cover lookup, and
  embedded lyric enrichment.
- Add conservative release matching, dry runs, recursive scans, external
  incremental state, protected paths, and a read-only metadata browser.
