import json
import os
import socket
import subprocess
import tempfile
import threading
import time

from rich.table import Table


# Helper function to get components from the context
def _get_components(context):
    return (
        context["console"],
        context["cfg"],
        context["fetcher"],
        context["db"],
        context["downloader"],
        context["qdb"],
        context["pldb"],
    )


def handle_init(args, context):
    console, _, _, _, _, _, _ = _get_components(context)
    data_dir = os.path.expanduser("~/apps/podx-app/data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "PodFile"), "w") as f:
        f.write(
            "[podcasts]\n\n[directories]\n\n[other_settings]\ndefault_dir = ~/Podcasts/Default\n"
        )
    console.print("[green]Initialized configuration.[/]")


def handle_add(args, context):
    console, cfg, _, _, _, _, _ = _get_components(context)
    cfg.podcasts[args.name] = args.rss
    if args.directory:
        cfg.directories[args.name] = args.directory
    cfg.save()
    console.print(f"[cyan]Added podcast[/] '{args.name}'.")


def handle_remove(args, context):
    console, cfg, _, _, _, _, _ = _get_components(context)
    if args.name not in cfg.podcasts:
        console.print(f"[red]Podcast not found:[/] {args.name}")
        return
    cfg.podcasts.pop(args.name)
    cfg.directories.pop(args.name, None)
    cfg.save()
    console.print(f"[red]Removed podcast:[/] {args.name}")


def handle_list(args, context):
    console, cfg, _, _, _, _, _ = _get_components(context)
    table = Table(title="Your Podcasts")
    table.add_column("Name", no_wrap=True)
    table.add_column("RSS URL", overflow="fold")
    table.add_column("Directory", overflow="fold")
    for name, rss in cfg.podcasts.items():
        directory = cfg.get_directory(name)
        table.add_row(name, rss, directory)
    console.print(table)


def handle_download(args, context):
    console, cfg, fetcher, _, downloader, _, _ = _get_components(context)
    name = args.name
    if name not in cfg.podcasts:
        console.print(f"[red]No such podcast:[/] {name}")
        return
    podcast = fetcher.fetch(cfg.podcasts[name])
    episodes = podcast.episodes
    if not args.all:
        episodes = episodes[: args.count]
    for ep in episodes:
        ok, msg = downloader.download(name, cfg.get_directory(name), ep)
        mark = "[green]✓[/]" if ok else "[red]✗[/]"
        console.print(f"{mark} {ep.title[:50]} — {msg}")


def handle_download_title(args, context):
    console, cfg, fetcher, _, downloader, _, _ = _get_components(context)
    if args.pod not in cfg.podcasts:
        console.print(f"[red]No such podcast:[/] {args.pod}")
        return
    podcast = fetcher.fetch(cfg.podcasts[args.pod])
    match = next((ep for ep in podcast.episodes if ep.title == args.title), None)
    if match:
        ok, msg = downloader.download(args.pod, cfg.get_directory(args.pod), match)
        mark = "[green]✓[/]" if ok else "[red]✗[/]"
        console.print(f"{mark} {match.title[:50]} — {msg}")
    else:
        console.print("[yellow]Episode not found.[/]")


def handle_rename(args, context):
    console, cfg, _, _, _, _, _ = _get_components(context)
    old, new = args.oldname, args.newname
    if old not in cfg.podcasts:
        console.print(f"[red]Podcast '{old}' not found.[/]")
        return
    cfg.podcasts[new] = cfg.podcasts.pop(old)
    if old in cfg.directories:
        cfg.directories[new] = cfg.directories.pop(old)
    cfg.save()
    console.print(f"[yellow]Renamed[/] '{old}' → '{new}'")


def handle_refresh(args, context):
    console, cfg, fetcher, _, _, _, _ = _get_components(context)
    names = [args.name] if args.name else list(cfg.podcasts)
    for name in names:
        console.print(f"[bold cyan]Fetching:[/] {name}")
        try:
            podcast = fetcher.fetch(cfg.podcasts[name])
            console.print(f"[green]✔[/] {len(podcast.episodes)} episodes")
        except Exception as e:
            console.print(f"[red]✘[/] {name}: {e}")


def handle_search(args, context):
    console, cfg, fetcher, _, _, _, _ = _get_components(context)
    targets = [args.podcast] if args.podcast else list(cfg.podcasts)
    for name in targets:
        try:
            podcast = fetcher.fetch(cfg.podcasts[name])
            for ep in podcast.episodes:
                text = getattr(ep, args.field, "")
                if args.query.lower() in text.lower():
                    console.print(f"[blue]{name}[/] — {ep.title[:60]}")
        except Exception as e:
            console.print(f"[red]{name}[/] error: {e}")


def handle_search_all(args, context):
    """Searches title and description of all episodes in all podcasts."""
    console, cfg, fetcher, _, _, _, _ = _get_components(context)
    query = args.query.lower()
    found_episodes = []

    console.print(
        f"🔍 Searching all podcasts for '[bold yellow]{args.query}[/bold yellow]'..."
    )

    for name, rss_url in cfg.podcasts.items():
        console.print(f"  -> Checking [cyan]{name}[/cyan]...")
        try:
            podcast = fetcher.fetch(rss_url)
            for ep in podcast.episodes:
                # Check both title and description for the query
                if query in ep.title.lower() or query in ep.description.lower():
                    found_episodes.append(
                        {
                            "podcast": name,
                            "title": ep.title,
                            "date": ep.pub_date,
                        }
                    )
        except Exception as e:
            console.print(f"     [red]Could not fetch or parse '{name}': {e}[/red]")

    console.print("-" * 20)

    if not found_episodes:
        console.print("No matching episodes found.")
        return

    table = Table(title=f"Search Results for '{args.query}'")
    table.add_column("Podcast", style="cyan", no_wrap=True)
    table.add_column("Episode Title", style="white")
    table.add_column("Date", style="magenta", justify="right")

    for match in found_episodes:
        table.add_row(match["podcast"], match["title"], match["date"])

    console.print(table)


def handle_info(args, context):
    console, cfg, fetcher, db, _, _, _ = _get_components(context)
    name = args.name
    if name not in cfg.podcasts:
        console.print(f"[red]No such podcast:[/] {name}")
        return
    try:
        podcast, fetched_summary = fetcher.fetch_with_description(cfg.podcasts[name])
        summary = (
            cfg.get_summary(name) or fetched_summary or "[dim]No summary available.[/]"
        )
        latest = max(
            (ep.pub_date for ep in podcast.episodes if ep.pub_date), default="Unknown"
        )
        count = len(podcast.episodes)
        cursor = db.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM manifest WHERE podcast=?", (name,))
        downloaded = cursor.fetchone()[0]

        console.rule(f"[bold cyan]{name}[/]")
        console.print(f"[italic]{summary.strip()}[/]\n")
        console.print(f"📦 Episodes: {count}")
        console.print(f"📅 Latest: {latest}")
        console.print(f"⬇️ Downloaded: {downloaded}")
    except Exception as e:
        console.print(f"[red]Failed to fetch info:[/] {e}")


def handle_clean(args, context):
    console, cfg, _, db, _, _, _ = _get_components(context)
    if args.name not in cfg.podcasts:
        console.print(f"[red]No such podcast:[/] {args.name}")
        return
    cursor = db.conn.cursor()
    cursor.execute("DELETE FROM manifest WHERE podcast=?", (args.name,))
    db.conn.commit()
    console.print(f"[yellow]Cleared manifest entries for:[/] {args.name}")


def handle_set_summary(args, context):
    console, cfg, _, _, _, _, _ = _get_components(context)
    name = args.name
    if name not in cfg.podcasts:
        console.print(f"[red]Podcast not found:[/] {name}")
        return
    summary_text = " ".join(args.summary).strip()
    cfg.set_summary(name, summary_text)
    console.print(f"[green]Set custom summary for:[/] {name}")


# --- Queue Commands ---
def handle_queue_add(args, context):
    console, _, _, _, _, qdb, _ = _get_components(context)
    qdb.add(args.pod, args.title)
    console.print(f"[cyan]Queued:[/] {args.title}")


def handle_queue_list(args, context):
    console, _, _, _, _, qdb, _ = _get_components(context)
    queue = qdb.list()
    if not queue:
        console.print("[dim]Queue is empty.[/]")
    else:
        for pod, title in queue:
            console.print(f"[blue]{pod}[/] — {title}")


def handle_queue_download(args, context):
    console, cfg, fetcher, _, downloader, qdb, _ = _get_components(context)
    entries = qdb.list()
    for pod, title in entries:
        if pod not in cfg.podcasts:
            console.print(f"[red]Podcast not found:[/] {pod}")
            continue
        podcast = fetcher.fetch(cfg.podcasts[pod])
        match = next((ep for ep in podcast.episodes if ep.title == title), None)
        if match:
            ok, msg = downloader.download(pod, cfg.get_directory(pod), match)
            mark = "[green]✓[/]" if ok else "[red]✗[/]"
            console.print(f"{mark} {title[:50]} — {msg}")
        else:
            console.print(f"[yellow]Not found:[/] {title}")
    qdb.reset()


def handle_queue_remove(args, context):
    console, _, _, _, _, qdb, _ = _get_components(context)
    qdb.remove(args.title)
    console.print(f"[yellow]Removed from queue:[/] {args.title}")


def handle_queue_reset(args, context):
    console, _, _, _, _, qdb, _ = _get_components(context)
    qdb.reset()
    console.print("[dim]Queue cleared.[/]")


# --- Playlist Commands ---
def handle_playlist(args, context):
    playlist_handlers = {
        "list": _playlist_list,
        "create": _playlist_create,
        "delete": _playlist_delete,
        "rename": _playlist_rename,
        "add": _playlist_add,
        "show": _playlist_show,
        "play": _playlist_play,
    }
    handler = playlist_handlers.get(args.pl_cmd)
    if handler:
        handler(args, context)


def _playlist_list(args, context):
    console, _, _, _, _, _, pldb = _get_components(context)
    names = pldb.list_playlists()
    if not names:
        console.print("[dim]No playlists found.[/]")
    else:
        console.print("[bold underline]Playlists[/]")
        for name in names:
            console.print(f"• {name}")


def _playlist_create(args, context):
    console, _, _, _, _, _, pldb = _get_components(context)
    pldb.create(args.name)
    console.print(f"[green]Created playlist:[/] {args.name}")


def _playlist_delete(args, context):
    console, _, _, _, _, _, pldb = _get_components(context)
    pldb.delete(args.name)
    console.print(f"[red]Deleted playlist:[/] {args.name}")


def _playlist_rename(args, context):
    console, _, _, _, _, _, pldb = _get_components(context)
    pldb.rename(args.old, args.new)
    console.print(f"[yellow]Renamed playlist:[/] {args.old} → {args.new}")


def _playlist_add(args, context):
    console, _, _, _, _, _, pldb = _get_components(context)
    if args.playlist not in pldb.list_playlists():
        console.print(f"[red]Playlist does not exist:[/] {args.playlist}")
        return
    pldb.add_episode(args.playlist, args.pod, args.title)
    console.print(f"[green]Added to '{args.playlist}':[/] {args.title}")


def _playlist_show(args, context):
    console, _, _, _, _, _, pldb = _get_components(context)
    entries = pldb.get_entries(args.name)
    if not entries:
        console.print(f"[dim]Playlist is empty:[/] {args.name}")
    else:
        table = Table(title=f"Playlist: {args.name}")
        table.add_column("Podcast", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Played", justify="center")
        for pod, title, played, _ in entries:
            mark = "✓" if played else ""
            table.add_row(pod, title[:80], mark)
        console.print(table)


def _playlist_play(args, context):
    console, _, _, db, _, _, pldb = _get_components(context)
    entries = pldb.get_entries(args.name)
    if not entries:
        console.print(f"[dim]Playlist is empty:[/] {args.name}")
        return

    for pod, title, played, pos in entries:
        if played:
            continue

        cursor = db.conn.execute(
            "SELECT path FROM manifest WHERE podcast=? AND title=?", (pod, title)
        )
        row = cursor.fetchone()
        if not row or not os.path.exists(row[0]):
            console.print(f"[yellow]File missing for:[/] {title}")
            continue

        path = row[0]
        console.rule(f"[bold green]Now playing:[/] {title}")
        sock_path = tempfile.NamedTemporaryFile(delete=True).name
        mpv_cmd = [
            "mpv",
            f"--input-ipc-server={sock_path}",
            "--term-playing-msg=EOF",
            "--force-window=no",
            "--quiet",
            "--no-video",
            f"--start={pos}" if pos else "",
            path,
        ]
        mpv_proc = subprocess.Popen(
            [arg for arg in mpv_cmd if arg],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        position, finished = 0, False

        def monitor():
            nonlocal position, finished
            try:
                while not finished:
                    if not os.path.exists(sock_path):
                        time.sleep(0.5)
                        continue
                    with socket.socket(socket.AF_UNIX) as client:
                        client.connect(sock_path)
                        while not finished:
                            msg = {"command": ["get_property", "time-pos"]}
                            client.send((json.dumps(msg) + "\n").encode())
                            data = client.recv(1024)
                            try:
                                response = json.loads(data.decode())
                                if "data" in response and isinstance(
                                    response["data"], (float, int)
                                ):
                                    position = int(response["data"])
                            except (json.JSONDecodeError, KeyError):
                                pass
                            time.sleep(2)
            except Exception:
                pass

        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        mpv_proc.wait()
        finished = True
        thread.join(timeout=1)

        if mpv_proc.returncode == 0:
            pldb.mark_played(args.name, title)
            console.print(f"[green]✓ Marked as played:[/] {title}")
        elif position > 0:
            pldb.update_position(args.name, title, position)
            console.print(f"[yellow]⏸ Saved position at {position}s for:[/] {title}")
        else:
            console.print(f"[red]✗ Playback failed or interrupted:[/] {title}")
