import os
os.add_dll_directory(r"C:\Program Files\VideoLAN\VLC")
import sys
import threading
import time

import msvcrt
from ytmusicapi import YTMusic
from yt_dlp import YoutubeDL
import vlc
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
import keyboard
import random

# ------------ Config ------------
SEARCH_QUERIES = [
    "lofi hip hop",
    "chillhop",
    "jazzhop",
    "sleep lofi",
    "study lofi",
    "coding lofi",
    "programming music"
]
MAX_RESULTS = 10
INITIAL_VOLUME = 70    
AUDIO_FORMAT_SELECTOR = "bestaudio[acodec^=opus]/bestaudio/best"  # yt-dlp format string
# -------------------------------

console = Console()


def get_ytmusic_client():
    
    # ytmusic class
    return YTMusic()


def search_lofi_tracks(ytm, query, limit=MAX_RESULTS):
    query = random.choice(SEARCH_QUERIES)
    results = ytm.search(query, filter="songs", limit=limit)
    tracks = []
    for item in results:
        video_id = item.get("videoId")
        title = item.get("title", "Unknown title")
        artists = ", ".join(a.get("name", "") for a in item.get("artists", [])) or "Unknown artist"
        if video_id:
            tracks.append(
                {
                    "video_id": video_id,
                    "title": title,
                    "artists": artists,
                    "duration": item.get("duration_seconds", 0),
                }
            )
    return tracks


def resolve_audio_url(video_id):
    """
    Use yt-dlp to extract an audio-only URL without downloading.
    Returns a direct media URL suitable for VLC.
    """
    ydl_opts = {
        "format": AUDIO_FORMAT_SELECTOR,
        "quiet": True,
        "skip_download": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        # url may be at top-level or in "url" of selected format
        if "url" in info:
            return info["url"]
        fmt = info.get("requested_formats") or info.get("formats") or []
        if fmt:
            return fmt[0]["url"]
    raise RuntimeError("Could not resolve audio URL")


def format_time(seconds):
    # Convert seconds to MM:SS format
    if seconds is None or seconds < 0:
        return "0:00"
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins}:{secs:02d}"


class ConsolePlayer:
    def __init__(self, tracks):
        self.tracks = tracks
        self.index = 0
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
        self.player.audio_set_volume(INITIAL_VOLUME)
        self._running = False
        self.current_duration = 0
        self.last_error = None

    def check_auto_next(self):
        """If current track finished, start the next one."""
        state = self.player.get_state()
        # State.Ended is the usual end-of-track state
        if state == vlc.State.Ended:
            self.next_track()

    def _load_current_track(self):
        track = self.tracks[self.index]
        video_id = track["video_id"]
        self.current_duration = track.get("duration", 0)
        try:
            url = resolve_audio_url(video_id)
        except Exception as e:
            self.last_error = f"Failed to resolve stream: {e}"
            return False
        media = self.instance.media_new(url)
        self.player.set_media(media)
        self.last_error = None
        return True

    def play_current(self):
        if not self._load_current_track():
            return
        self.player.play()
        time.sleep(0.5)

    def current_label(self):
        t = self.tracks[self.index]
        return f"{t['title']} - {t['artists']}"

    def next_track(self):
        self.index = (self.index + 1) % len(self.tracks)
        self.play_current()

    def prev_track(self):
        self.index = (self.index - 1) % len(self.tracks)
        self.play_current()

    def toggle_pause(self):
        self.player.pause()

    def volume_up(self, step=5):
        vol = self.player.audio_get_volume()
        vol = min(100, vol + step)
        self.player.audio_set_volume(vol)

    def volume_down(self, step=5):
        vol = self.player.audio_get_volume()
        vol = max(0, vol - step)
        self.player.audio_set_volume(vol)

    def stop(self):
        self.player.stop()

    def get_player_state(self):
        """Return human-readable player state."""
        state = self.player.get_state()
        state_map = {
            0: "Idle",
            1: "Opening",
            2: "Buffering",
            3: "Playing",
            4: "Paused",
            5: "Stopped",
            6: "Ended",
            7: "Error",
        }
        return state_map.get(state, "Unknown")

    def get_current_time(self):
        """Get current playback position in seconds."""
        return self.player.get_time() / 1000 if self.player.get_time() >= 0 else 0

    def build_ui(self):
        """Build the player UI using Rich."""
        current_time = self.get_current_time()
        duration = self.current_duration if self.current_duration > 0 else 1
        progress = (current_time / duration) * 100 if duration > 0 else 0
        progress = min(100, max(0, progress))

        vol = self.player.audio_get_volume()
        state = self.get_player_state()

        # Now Playing Info
        now_playing = Text(self.current_label(), style="cyan bold")

        # Progress bar
        filled = int(progress / 5)
        bar = "█" * filled + "░" * (20 - filled)
        time_info = f"{format_time(current_time)} / {format_time(duration)}"
        progress_line = Text(f"[{bar}] {time_info}", style="green")

        # Volume bar
        vol_filled = int(vol / 5)
        vol_bar = "█" * vol_filled + "░" * (20 - vol_filled)
        volume_line = Text(f"Volume: [{vol_bar}] {vol}%", style="yellow")

        controls = Text(
            "[⏮  a]  [⏸  space]  [⏭  d]  [q  quit] \n[🔊  w]    [🔉  s]",
            style="dim white",
            justify="center",
        )


        # Status
        status_text = f"[{self.index + 1}/{len(self.tracks)}] {state}"
        status = Text(status_text, style="magenta")

        # Build panel content
        content = f"""
{now_playing}

{progress_line}

{volume_line}

{controls}

{status}
"""

        panel = Panel(
            content,
            title="  Lofi Player",
            border_style="cyan",
            padding=(1, 2)
        )

        return panel

    def _keyboard_loop(self):
        while self._running:
            # update UI in outer loop
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                # decode, handle special keys
                if ch in (b'a', b'A'):
                    self.prev_track()
                elif ch in (b'd', b'D'):
                    self.next_track()
                elif ch == b' ':
                    self.toggle_pause()
                elif ch in (b'w',):
                    self.volume_up()
                elif ch in (b's',):
                    self.volume_down()
                elif ch in (b'q', b'Q'):
                    self._running = False
                    break
            time.sleep(0.05)

    # def _keyboard_listener(self):
    #     """Listen for keyboard events without blocking input."""
    #     while self._running:
    #         try:
    #             if keyboard.is_pressed('space'):
    #                 self.toggle_pause()
    #                 time.sleep(0.3)  # Debounce
    #             elif keyboard.is_pressed('d'):
    #                 self.next_track()
    #                 time.sleep(0.3)
    #             elif keyboard.is_pressed('a'):
    #                 self.prev_track()
    #                 time.sleep(0.3)
    #             elif keyboard.is_pressed('w'):
    #                 self.volume_up()
    #                 time.sleep(0.2)
    #             elif keyboard.is_pressed('s'):
    #                 self.volume_down()
    #                 time.sleep(0.2)
    #             elif keyboard.is_pressed('q'):
    #                 self._running = False
    #                 break
    #             time.sleep(0.05)
    #         except Exception as e:
    #             pass

    def run(self):
        self._running = True
        self.play_current()

        kb_thread = threading.Thread(target=self._keyboard_loop, daemon=True)
        kb_thread.start()

        with Live(self.build_ui(), refresh_per_second=4, console=console) as live:
            while self._running:
                self.check_auto_next()
                live.update(self.build_ui())
                time.sleep(0.2)

        self.stop()

    # def run(self):
    #     self._running = True
    #     self.play_current()

    #     # Start keyboard listener thread
    #     listener_thread = threading.Thread(target=self._keyboard_listener, daemon=True)
    #     listener_thread.start()

    #     # Update UI loop
    #     with Live(self.build_ui(), refresh_per_second=2, console=console) as live:
    #         while self._running:
    #             live.update(self.build_ui())
    #             time.sleep(0.5)

    #     console.print("\n[yellow]Stopping playback...[/yellow]")
    #     self.stop()


def print_tracks(tracks):
    console.print(f"\n[bold cyan]Search results for '{SEARCH_QUERIES}':[/bold cyan]")
    for i, t in enumerate(tracks, start=1):
        console.print(f"[green]{i:2d}.[/green] {t['title']} - [yellow]{t['artists']}[/yellow]")




def main():
    query = random.choice(SEARCH_QUERIES)
    ytm = get_ytmusic_client()
    tracks = search_lofi_tracks(ytm, query, MAX_RESULTS)
    if not tracks:
        console.print("[red]No tracks found.[/red]")
        return
    random.shuffle(tracks) 
    print_tracks(tracks)

    # Initial track selection
    while True:
        try:
            choice = console.input(f"\n[bold]Enter track number to start (1-{len(tracks)}):[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(tracks):
                break
        console.print("[red]Invalid selection.[/red]")

    player = ConsolePlayer(tracks)
    player.index = idx
    player.run()


if __name__ == "__main__":
    main()