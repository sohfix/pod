# future podcore

import configparser
import hashlib
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List
from urllib.parse import urlparse

import requests
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

# ─── Data Classes ──────────────────────────────────────────────────────

@dataclass
class Episode:
    title: str
    url: str
    pub_date: str
    description: str = ""
    duration: str = ""

@dataclass
class Podcast:
    name: str
    rss_url: str
    directory: str
    episodes: List[Episode]

# ─── Configuration ─────────────────────────────────────────────────────

class PodConfig:
    def __init__(self, config_path="~/apps/podx-app/data/PodFile"):
        self.config_path = os.path.expanduser(config_path)
        self.podcasts: dict[str, str] = {}
        self.directories: dict[str, str] = {}
        self.settings: dict[str, str] = {}
        self.summaries: dict[str, str] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.config_path):
            return
        cfg = configparser.ConfigParser()
        cfg.read(self.config_path)
        self.podcasts = dict(cfg["podcasts"].items()) if "podcasts" in cfg else {}
        self.directories = (
            dict(cfg["directories"].items()) if "directories" in cfg else {}
        )
        self.settings = (
            dict(cfg["other_settings"].items()) if "other_settings" in cfg else {}
        )
        self.summaries = dict(cfg["summaries"].items()) if "summaries" in cfg else {}

    def save(self):
        cfg = configparser.ConfigParser()
        cfg["podcasts"] = self.podcasts
        cfg["directories"] = self.directories
        cfg["other_settings"] = self.settings
        if self.summaries:
            cfg["summaries"] = self.summaries
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            cfg.write(f)

    def get_directory(self, name: str) -> str:
        if name in self.directories:
            return os.path.expanduser(self.directories[name])
        default = self.settings.get("default_dir", "~/Podcasts/Default")
        return os.path.expanduser(default)

    def get_summary(self, name: str) -> str:
        return self.summaries.get(name, "")

    def set_summary(self, name: str, summary: str):
        self.summaries[name] = summary
        self.save()

# ─── Playlist Database ──────────────────────────────────────────────────

class PlaylistDB:
    def __init__(self, db_path="~/apps/podx-app/data/.pod_playlists.db"):
        self.db_path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self._init()

    def _init(self):
        with self.conn:
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS playlists (
                           name TEXT PRIMARY KEY
                       )"""
            )
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS playlist_entries (
                           id INTEGER PRIMARY KEY AUTOINCREMENT,
                           playlist TEXT,
                           podcast TEXT,
                           title TEXT,
                           position INTEGER DEFAULT 0,
                           played INTEGER DEFAULT 0,
                           FOREIGN KEY (playlist) REFERENCES playlists(name)
                       )"""
            )

    def create(self, name: str):
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO playlists (name) VALUES (?)", (name,)
            )

    def delete(self, name: str):
        with self.conn:
            self.conn.execute("DELETE FROM playlist_entries WHERE playlist=?", (name,))
            self.conn.execute("DELETE FROM playlists WHERE name=?", (name,))

    def rename(self, old: str, new: str):
        with self.conn:
            self.conn.execute("UPDATE playlists SET name=? WHERE name=?", (new, old))
            self.conn.execute(
                "UPDATE playlist_entries SET playlist=? WHERE playlist=?", (new, old)
            )

    def list_playlists(self) -> list[str]:
        cur = self.conn.execute("SELECT name FROM playlists ORDER BY name")
        return [row[0] for row in cur.fetchall()]

    def add_episode(self, playlist: str, podcast: str, title: str):
        with self.conn:
            self.conn.execute(
                """INSERT INTO playlist_entries (playlist, podcast, title)
                           VALUES (?, ?, ?)""",
                (playlist, podcast, title),
            )

    def get_entries(self, playlist: str) -> list[tuple]:
        cur = self.conn.execute(
            """SELECT podcast, title, played, position FROM playlist_entries
               WHERE playlist=? ORDER BY id""",
            (playlist,),
        )
        return cur.fetchall()

    def mark_played(self, playlist: str, title: str):
        with self.conn:
            self.conn.execute(
                """UPDATE playlist_entries SET played=1 WHERE playlist=? AND title=?""",
                (playlist, title),
            )

    def update_position(self, playlist: str, title: str, position: int):
        with self.conn:
            self.conn.execute(
                """UPDATE playlist_entries SET position=? WHERE playlist=? AND title=?""",
                (position, playlist, title),
            )

# ─── Manifest Database ─────────────────────────────────────────────────

class ManifestDB:
    def __init__(self, db_path="~/apps/podx-app/data/.pod_manifest.db"):
        self.db_path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self._init_table()

    def _init_table(self):
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manifest (
                    id TEXT PRIMARY KEY,
                    podcast TEXT,
                    title TEXT,
                    url TEXT,
                    path TEXT,
                    downloaded_at TEXT
                )
                """
            )

    def is_downloaded(self, url_hash: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM manifest WHERE id=?", (url_hash,))
        return cur.fetchone() is not None

    def add(self, url_hash: str, podcast: str, title: str, url: str, path: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO manifest VALUES (?, ?, ?, ?, ?, ?)",
                (
                    url_hash,
                    podcast,
                    title,
                    url,
                    path,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

# ─── Queue Database ────────────────────────────────────────────────────

class QueueDB:
    def __init__(self, db_path="~/apps/podx-app/data.pod_queue.db"):
        self.db_path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self._init()

    def _init(self):
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    podcast TEXT,
                    title TEXT
                )
                """
            )

    def add(self, podcast: str, title: str):
        cur = self.conn.execute(
            "SELECT 1 FROM queue WHERE podcast=? AND title=?", (podcast, title)
        )
        if not cur.fetchone():
            with self.conn:
                self.conn.execute(
                    "INSERT INTO queue (podcast, title) VALUES (?, ?)", (podcast, title)
                )

    def list(self) -> List[tuple]:
        cur = self.conn.execute("SELECT podcast, title FROM queue")
        return cur.fetchall()

    def remove(self, title: str):
        with self.conn:
            self.conn.execute("DELETE FROM queue WHERE title=?", (title,))

    def reset(self):
        with self.conn:
            self.conn.execute("DELETE FROM queue")

# ─── Podcast Fetching ──────────────────────────────────────────────────

class PodcastFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "PodCLI/1.0"})

    def fetch(self, rss_url: str) -> Podcast:
        resp = self.session.get(rss_url, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        title = channel.findtext("title", "Unknown")
        episodes: List[Episode] = []
        for item in channel.findall("item"):
            enc = item.find("enclosure")
            if enc is None or "url" not in enc.attrib:
                continue
            episodes.append(
                Episode(
                    title=item.findtext("title", "No Title"),
                    url=enc.get("url"),
                    pub_date=item.findtext("pubDate", ""),
                    description=item.findtext("description", ""),
                    duration=item.findtext("duration", ""),
                )
            )
        return Podcast(name=title, rss_url=rss_url, directory="", episodes=episodes)

    def fetch_with_description(self, rss_url: str) -> tuple[Podcast, str]:
        resp = self.session.get(rss_url, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        title = channel.findtext("title", "Unknown")
        description = channel.findtext("description", "")
        episodes: List[Episode] = []
        for item in channel.findall("item"):
            enc = item.find("enclosure")
            if enc is None or "url" not in enc.attrib:
                continue
            episodes.append(
                Episode(
                    title=item.findtext("title", "No Title"),
                    url=enc.get("url"),
                    pub_date=item.findtext("pubDate", ""),
                    description=item.findtext("description", ""),
                    duration=item.findtext("duration", ""),
                )
            )
        return (
            Podcast(name=title, rss_url=rss_url, directory="", episodes=episodes),
            description,
        )

# ─── Episode Downloader ────────────────────────────────────────────────

class Downloader:
    def __init__(self, db: ManifestDB, console):
        self.session = requests.Session()
        self.db = db
        self.console = console

    def download(
        self, podcast_name: str, directory: str, ep: Episode
    ) -> tuple[bool, str]:
        h = hashlib.md5(ep.url.encode()).hexdigest()
        if self.db.is_downloaded(h):
            cursor = self.db.conn.execute("SELECT path FROM manifest WHERE id=?", (h,))
            row = cursor.fetchone()
            if row and not os.path.exists(row[0]):
                self.db.conn.execute("DELETE FROM manifest WHERE id=?", (h,))
            else:
                return False, "Already downloaded"

        os.makedirs(directory, exist_ok=True)
        ext = os.path.splitext(urlparse(ep.url).path)[-1] or ".mp3"
        safe = re.sub(r"[^\w\-_. ]", "_", ep.title)[:80] + ext
        dest = os.path.join(directory, safe)

        try:
            r = self.session.get(ep.url, stream=True, timeout=20)
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))

            with Progress(
                TextColumn("[bold blue]↓[/] {task.description}"),
                BarColumn(bar_width=32, complete_style="cyan", finished_style="green"),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                transient=True,
                console=self.console,
            ) as progress:
                task = progress.add_task(ep.title[:50], total=total)
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            progress.update(task, advance=len(chunk))

            self.db.add(h, podcast_name, ep.title, ep.url, dest)
            return True, dest

        except Exception as e:
            return False, str(e)
