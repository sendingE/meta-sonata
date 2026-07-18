# Test Fixture Policy

Tests must be safe for a public GitHub repository.

- Do not commit third-party audio, cover art, cue sheets, or scans.
- Use generated audio in temporary directories for integration smoke tests.
- Unit tests may use real public-domain work titles and composer names for
  realistic metadata parsing.
- Current metadata examples use Scott Joplin works such as `Maple Leaf Rag`,
  whose composition is public domain.
- If a test ever downloads or vendors a recording, the recording itself must be
  public domain or CC0/Public Domain Mark, and the source URL/license must be
  documented next to the fixture.
