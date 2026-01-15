"""Main orchestrator coordinating all components."""

import asyncio
import os
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import discord
from discord.ext import tasks
import spotipy

from database import TrackDatabase, TrackStatus
from spotify_monitor import create_spotify_client, get_new_liked_songs
from recording_pipeline import process_approved_track
from usb_sync import run_sync, get_usb_volumes
from wifi_detector import get_current_ssid, is_connected


SPOTIFY_POLL_INTERVAL = 60  # seconds
RECORDING_CHECK_INTERVAL = 30  # seconds
USB_POLL_INTERVAL = 5  # seconds


class Orchestrator:
    """Coordinates Discord bot, recording pipeline, and USB sync."""

    def __init__(
        self,
        db_path: str = "tracks.db",
        output_dir: str = "recordings",
        discord_token: str | None = None,
        discord_channel_id: int | None = None,
        target_wifi_ssid: str | None = None,
    ) -> None:
        self.db = TrackDatabase(db_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.discord_token = discord_token or os.environ.get("DISCORD_TOKEN")
        self.discord_channel_id = discord_channel_id or int(os.environ.get("DISCORD_CHANNEL_ID", 0))
        self.target_wifi_ssid = target_wifi_ssid

        self.bot: discord.Client | None = None
        self.spotify: spotipy.Spotify | None = None
        self.pending_messages: dict[int, str] = {}
        self.running = False
        self.recording_in_progress = False
        self.executor = ThreadPoolExecutor(max_workers=2)

    def _check_wifi(self) -> bool:
        """Check WiFi connection if target SSID is configured."""
        if not self.target_wifi_ssid:
            return True  # No WiFi check configured
        return is_connected() and get_current_ssid() == self.target_wifi_ssid

    async def start(self) -> None:
        """Start all orchestrated services."""
        print("Starting orchestrator...")
        self.running = True

        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Create and configure Discord bot
        self._setup_discord_bot()

        # Start all tasks
        tasks_to_run = [
            self._run_discord_bot(),
            self._recording_loop(),
            self._usb_sync_loop(),
        ]

        if self.target_wifi_ssid:
            print(f"WiFi check enabled - waiting for SSID: {self.target_wifi_ssid}")

        await asyncio.gather(*tasks_to_run)

    async def stop(self) -> None:
        """Gracefully stop all services."""
        print("\nShutting down orchestrator...")
        self.running = False

        if self.bot:
            await self.bot.close()

        self.executor.shutdown(wait=False)
        print("Shutdown complete")

    def _setup_discord_bot(self) -> None:
        """Setup the Discord bot for approval workflow."""
        intents = discord.Intents.default()
        intents.message_content = True

        self.bot = discord.Client(intents=intents)
        self.spotify = create_spotify_client()

        @self.bot.event
        async def on_ready():
            print(f"Discord bot logged in as {self.bot.user}")
            await self._notify_pending_tracks()
            self._spotify_poll_task.start()

        @self.bot.event
        async def on_message(message: discord.Message):
            if message.author.bot or message.channel.id != self.discord_channel_id:
                return

            if message.reference and message.reference.message_id:
                ref_id = message.reference.message_id
                if ref_id in self.pending_messages:
                    spotify_id = self.pending_messages[ref_id]
                    response = message.content.lower().strip()

                    if response in ("yes", "y", "approve"):
                        await self._approve_track(spotify_id)
                    elif response in ("no", "n", "reject", "skip"):
                        await self._reject_track(spotify_id)

        @self.bot.event
        async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
            if user.bot:
                return

            msg_id = reaction.message.id
            if msg_id not in self.pending_messages:
                return

            spotify_id = self.pending_messages[msg_id]

            if str(reaction.emoji) == "\u2705":  # checkmark
                await self._approve_track(spotify_id)
            elif str(reaction.emoji) == "\u274c":  # X
                await self._reject_track(spotify_id)

        @tasks.loop(seconds=SPOTIFY_POLL_INTERVAL)
        async def spotify_poll():
            if not self._check_wifi():
                return
            await self._poll_spotify()

        @spotify_poll.before_loop
        async def before_poll():
            await self.bot.wait_until_ready()

        self._spotify_poll_task = spotify_poll

    async def _run_discord_bot(self) -> None:
        """Run the Discord bot."""
        if not self.discord_token:
            print("No Discord token - running without approval bot")
            while self.running:
                await asyncio.sleep(1)
            return

        await self.bot.start(self.discord_token)

    async def _notify_pending_tracks(self) -> None:
        """Send notifications for tracks pending approval."""
        channel = self.bot.get_channel(self.discord_channel_id)
        if not channel:
            print(f"Could not find channel {self.discord_channel_id}")
            return

        pending = self.db.get_by_status(TrackStatus.PENDING)
        for track_row in pending:
            await self._send_approval_request(channel, track_row)

    async def _send_approval_request(self, channel: discord.abc.Messageable, track: dict) -> None:
        """Send approval request message."""
        embed = discord.Embed(
            title=track["name"],
            description=f"by **{track['artist']}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Album", value=track["album"], inline=True)
        embed.set_footer(text=f"Spotify ID: {track['spotify_id']}")

        msg = await channel.send(
            content="Found new song! Reply **yes** or **no** to this message:",
            embed=embed
        )

        self.pending_messages[msg.id] = track["spotify_id"]
        await msg.add_reaction("\u2705")
        await msg.add_reaction("\u274c")

    async def _poll_spotify(self) -> None:
        """Poll Spotify for new liked songs."""
        if not self.spotify:
            return

        channel = self.bot.get_channel(self.discord_channel_id)
        if not channel:
            return

        new_tracks = get_new_liked_songs(self.spotify)

        for track in new_tracks:
            added = self.db.add_track(
                spotify_id=track.id,
                name=track.name,
                artist=track.artist,
                album=track.album,
                added_at=track.added_at,
                album_art_url=track.album_art_url,
                track_number=track.track_number
            )

            if added:
                print(f"New track: {track.name} by {track.artist}")
                track_row = self.db.get_track(track.id)
                await self._send_approval_request(channel, track_row)

    async def _approve_track(self, spotify_id: str) -> None:
        """Mark track as approved and notify."""
        track = self.db.get_track(spotify_id)
        if not track:
            return

        self.db.update_status(spotify_id, TrackStatus.APPROVED)

        msg_id = next((k for k, v in self.pending_messages.items() if v == spotify_id), None)
        if msg_id:
            del self.pending_messages[msg_id]

        channel = self.bot.get_channel(self.discord_channel_id)
        await channel.send(f"Approved **{track['name']}** by {track['artist']}. Will record soon.")
        print(f"Approved: {track['name']}")

    async def _reject_track(self, spotify_id: str) -> None:
        """Mark track as rejected."""
        track = self.db.get_track(spotify_id)
        if not track:
            return

        self.db.update_status(spotify_id, TrackStatus.REJECTED)

        msg_id = next((k for k, v in self.pending_messages.items() if v == spotify_id), None)
        if msg_id:
            del self.pending_messages[msg_id]

        channel = self.bot.get_channel(self.discord_channel_id)
        await channel.send(f"Skipped **{track['name']}** by {track['artist']}.")
        print(f"Rejected: {track['name']}")

    async def _recording_loop(self) -> None:
        """Periodically check for approved tracks and record them."""
        print("Recording loop started")

        while self.running:
            await asyncio.sleep(RECORDING_CHECK_INTERVAL)

            if not self._check_wifi():
                continue

            if self.recording_in_progress:
                continue

            approved = self.db.get_by_status(TrackStatus.APPROVED)
            if not approved:
                continue

            self.recording_in_progress = True

            for track_row in approved:
                if not self.running:
                    break

                spotify_id = track_row["spotify_id"]
                print(f"Recording: {track_row['name']} by {track_row['artist']}")

                path = await process_approved_track(
                    db=self.db,
                    spotify_id=spotify_id,
                    output_dir=self.output_dir
                )

                if path:
                    await self._notify_recording_complete(track_row)

                await asyncio.sleep(2)

            self.recording_in_progress = False

    async def _notify_recording_complete(self, track: dict) -> None:
        """Send notification that recording is complete."""
        if not self.bot or not self.discord_channel_id:
            return

        channel = self.bot.get_channel(self.discord_channel_id)
        if channel:
            await channel.send(f"Recorded **{track['name']}** by {track['artist']}. Ready for sync.")

    async def _usb_sync_loop(self) -> None:
        """Monitor for USB devices and sync when detected."""
        print("USB sync loop started")

        synced_volumes = set()

        while self.running:
            await asyncio.sleep(USB_POLL_INTERVAL)

            # Run USB detection in thread pool (it's blocking)
            current_volumes = await asyncio.get_event_loop().run_in_executor(
                self.executor,
                lambda: set(get_usb_volumes())
            )

            # Skip sync if recording is in progress to avoid race condition
            if self.recording_in_progress:
                continue

            pending_volumes = current_volumes - synced_volumes

            for volume in pending_volumes:
                print(f"USB device detected: {volume.name}")

                cancel_event = threading.Event()
                try:
                    result = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            self.executor,
                            lambda: run_sync(self.output_dir, self.db.db_path, cancel_event)
                        ),
                        timeout=300.0  # 5 minute timeout for sync
                    )
                except TimeoutError:
                    cancel_event.set()
                    print(f"USB sync timed out for {volume.name}")
                    continue

                synced_volumes.add(volume)

                if result["synced"]:
                    print(f"Synced {len(result['synced'])} tracks")
                    await self._notify_sync_complete(result["synced"])

            removed = synced_volumes - current_volumes
            for volume in removed:
                print(f"USB device removed: {volume.name}")
                synced_volumes.discard(volume)

    async def _notify_sync_complete(self, synced_tracks: list[dict]) -> None:
        """Send notification that sync is complete."""
        if not self.bot or not self.discord_channel_id:
            return

        channel = self.bot.get_channel(self.discord_channel_id)
        if channel:
            count = len(synced_tracks)
            await channel.send(f"Synced {count} track(s) to your MP3 player.")


def main() -> None:
    """Entry point for the orchestrator."""
    import argparse

    parser = argparse.ArgumentParser(description="Media server orchestrator")
    parser.add_argument("--db", default="tracks.db", help="Database path")
    parser.add_argument("--output", default="recordings", help="Output directory")
    parser.add_argument("--wifi-ssid", help="Only run when connected to this WiFi")

    args = parser.parse_args()

    orchestrator = Orchestrator(
        db_path=args.db,
        output_dir=args.output,
        target_wifi_ssid=args.wifi_ssid,
    )

    asyncio.run(orchestrator.start())


if __name__ == "__main__":
    main()
