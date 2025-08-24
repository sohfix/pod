# pox --- CLI Podcast Manager (RSS-only)

*A single-file tool to manage, search, download, queue, and playlist
podcast episodes --- with per-feed directory overrides and yt-dlp
helpers.*

------------------------------------------------------------------------

## TL;DR Quick Start

``` bash
# 1) Initialize config/db
pox init

# 2) Add an RSS feed (RSS only; Atom feeds are rejected on refresh)
pox add-feed bastards https://example.com/bastards.xml

# 3) Refresh (fetch episodes into the manifest)
pox refresh --feed bastards

# 4) Search and download
pox search --feed bastards --query "pilot"
pox download --feed bastards --latest 2
pox download-title --feed bastards --title "pilot"

# 5) Queue, then bulk-download
pox queue-add --feed bastards --title "season finale"
pox queue-list
pox queue-download

# 6) Playlists
pox playlist create favorites
pox playlist add favorites --episode-id 123
pox playlist export favorites --out ~/favorites.m3u

# 7) Configure download directories (global & per-feed)
pox set --download-dir ~/media/audio/podcasts
pox set --change-feed-dir bastards --dir ~/special/bastards
pox set --show
```

------------------------------------------------------------------------

## Concepts & Guarantees

-   **RSS-only:** The parser enforces
    `<rss><channel><item>…</item></channel></rss>`. Atom (`<feed>`) is
    refused with a clear error during `refresh`.
-   **SQLite manifest:** Episodes are stored in `pox.db`. Downloads are
    tracked separately. Already-downloaded episodes are skipped by
    default.
-   **Idempotent by design:** Re-running `refresh` dedupes by
    `(feed, guid)`. Re-downloading skips already-completed items.
-   **Directories:**
    -   **Global base audio dir:** defaults to
        `~/media/audio/default/pox`, configurable via
        `pox set --download-dir PATH`.\
    -   **Per-feed override:**
        `pox set --change-feed-dir FEED --dir PATH`.\
    -   **yt-dlp dir:** defaults to `~/media/video/default/pox-yt`,
        configurable via `pox set --download-yt-dir PATH`.
-   **Rename safety:** Renaming a feed *migrates* its settings key. If a
    feed has a custom dir override, files are **not moved**; otherwise
    `base/<old>` → `base/<new>` is moved.
-   **Queue fix:** `queue-download` clears items by queue ID (not
    episode ID), so the queue empties reliably.

------------------------------------------------------------------------

## Installation

1.  Put `pox` on your `PATH` and make it executable:

    ``` bash
    chmod +x pox
    mv pox ~/bin/  # or wherever you keep CLI tools
    ```

2.  Optional (for yt-dlp helpers):

    ``` bash
    pipx install yt-dlp  # or your package manager
    ```

------------------------------------------------------------------------

## Directory Layout

-   **Config & DB:**\
    `~/apps/.app-data/.config-files/pox/`
    -   `PodFile.ini` --- feeds, summaries, settings\
    -   `pox.db` --- SQLite database
-   **Audio downloads:**
    -   Default base: `~/media/audio/default/pox`\
    -   If you set `pox set --download-dir ~/media/audio/podcasts`, the
        *effective* base becomes that path.\
    -   Each feed downloads to:
        -   `base/<feed>` when there is **no** per-feed override; or
        -   the explicit path from
            `pox set --change-feed-dir <feed> --dir <path>`.
-   **yt-dlp downloads:**
    -   Default: `~/media/video/default/pox-yt`\
    -   Configurable via `pox set --download-yt-dir PATH`.

------------------------------------------------------------------------

## `PodFile.ini` Format (auto-managed)

``` ini
[feeds]
bastards = https://example.com/bastards.xml
myshow = https://example.com/myshow.rss

[summaries]
bastards = A breezy description you set with `pox set-summary`.
myshow = Another description.

[settings]
# base directory for audio downloads
download_dir = /home/you/media/audio/podcasts

# per-feed overrides
feed_dir.bastards = /home/you/special/bastards

# yt-dlp target
download_yt_dir = /home/you/media/video/yt
```

**Tip:** Manage this through `pox set` rather than editing by hand.

------------------------------------------------------------------------

## Command Reference

(see full breakdown in usage manual above)
