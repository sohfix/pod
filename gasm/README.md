# podcast — unified CLI

Single entry point: `podcast`

## Commands
- `podcast set` — initialize/configure (maps to feeds `init`).
- `podcast feed add <rss-url>` — add a feed.
- `podcast feed list` — list feeds.
- `podcast feed search <query>` — search.
- `podcast feed refresh` — refresh all feeds.
- `podcast download [opts]` — download episodes (pass-through to original).
- `podcast clip [opts]` — audio clipping/mixing (pass-through to original).

Shortcuts:
- `podcast help`, `podcast help clip`, `podcast help download`
- You can also run feeds verbs at top-level: `podcast add <url>`, `podcast download --latest 5`.

## Package layout for reuse
- `podcastpkg/feeds.py` — vendored original feeds/downloader module unchanged.
- `podcastpkg/clips.py` — vendored original clipper/mixer module unchanged.
