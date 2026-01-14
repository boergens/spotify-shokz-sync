"""Discord bot for song approval notifications."""

import os
import asyncio
from datetime import datetime

import discord
from discord.ext import tasks

from spotify_monitor import create_spotify_client, get_new_liked_songs, Track
from database import TrackDatabase, TrackStatus


POLL_INTERVAL_SECONDS = 60


class SongApprovalBot(discord.Client):
    def __init__(self, db: TrackDatabase, channel_id: int):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        self.db = db
        self.channel_id = channel_id
        self.spotify = None
        self.pending_messages = {}  # message_id -> spotify_id

    async def setup_hook(self):
        self.poll_spotify.start()

    async def on_ready(self):
        print(f"Bot logged in as {self.user}")
        self.spotify = create_spotify_client()

        # Notify about any pending tracks from previous session
        await self.notify_pending_tracks()

    async def notify_pending_tracks(self):
        """Send notifications for tracks that are pending approval."""
        channel = self.get_channel(self.channel_id)
        if not channel:
            print(f"Could not find channel {self.channel_id}")
            return

        pending = self.db.get_by_status(TrackStatus.PENDING)
        for track_row in pending:
            await self.send_approval_request(channel, track_row)

    async def send_approval_request(self, channel, track: dict):
        """Send a message asking for approval of a track."""
        embed = discord.Embed(
            title=track["name"],
            description=f"by **{track['artist']}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Album", value=track["album"], inline=True)
        embed.set_footer(text=f"Spotify ID: {track['spotify_id']}")

        msg = await channel.send(
            content=f"Found new song! Reply **yes** or **no** to this message:",
            embed=embed
        )

        self.pending_messages[msg.id] = track["spotify_id"]
        # Add reactions for easy response
        await msg.add_reaction("\u2705")  # checkmark
        await msg.add_reaction("\u274c")  # X

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.channel.id != self.channel_id:
            return

        # Check if this is a reply to a pending message
        if message.reference and message.reference.message_id:
            ref_id = message.reference.message_id
            if ref_id in self.pending_messages:
                spotify_id = self.pending_messages[ref_id]
                response = message.content.lower().strip()

                if response in ("yes", "y", "approve"):
                    await self.approve_track(spotify_id, message)
                elif response in ("no", "n", "reject", "skip"):
                    await self.reject_track(spotify_id, message)

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return

        msg_id = reaction.message.id
        if msg_id not in self.pending_messages:
            return

        spotify_id = self.pending_messages[msg_id]

        if str(reaction.emoji) == "\u2705":  # checkmark
            await self.approve_track(spotify_id, reaction.message)
        elif str(reaction.emoji) == "\u274c":  # X
            await self.reject_track(spotify_id, reaction.message)

    async def approve_track(self, spotify_id: str, context):
        """Mark track as approved."""
        track = self.db.get_track(spotify_id)
        if not track:
            return

        self.db.update_status(spotify_id, TrackStatus.APPROVED)

        # Clean up pending tracking
        msg_id = next((k for k, v in self.pending_messages.items() if v == spotify_id), None)
        if msg_id:
            del self.pending_messages[msg_id]

        channel = self.get_channel(self.channel_id)
        await channel.send(f"Approved **{track['name']}** by {track['artist']}. Will record it soon.")

    async def reject_track(self, spotify_id: str, context):
        """Mark track as rejected."""
        track = self.db.get_track(spotify_id)
        if not track:
            return

        self.db.update_status(spotify_id, TrackStatus.REJECTED)

        # Clean up pending tracking
        msg_id = next((k for k, v in self.pending_messages.items() if v == spotify_id), None)
        if msg_id:
            del self.pending_messages[msg_id]

        channel = self.get_channel(self.channel_id)
        await channel.send(f"Skipped **{track['name']}** by {track['artist']}.")

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_spotify(self):
        """Poll Spotify for new liked songs."""
        if not self.spotify:
            return

        channel = self.get_channel(self.channel_id)
        if not channel:
            return

        new_tracks = get_new_liked_songs(self.spotify)

        for track in new_tracks:
            # Only add if not already in database
            added = self.db.add_track(
                spotify_id=track.id,
                name=track.name,
                artist=track.artist,
                album=track.album,
                added_at=track.added_at
            )

            if added:
                print(f"New track found: {track.name} by {track.artist}")
                track_row = self.db.get_track(track.id)
                await self.send_approval_request(channel, track_row)

    @poll_spotify.before_loop
    async def before_poll(self):
        await self.wait_until_ready()


async def send_completion_notification(channel_id: int, track_name: str, artist: str):
    """Send a completion notification (called from recording pipeline)."""
    # This is a standalone function for other modules to use
    # It creates a temporary client just to send the message
    token = os.environ["DISCORD_TOKEN"]

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        channel = client.get_channel(channel_id)
        if channel:
            await channel.send(f"Done! **{track_name}** by {artist} is ready for your player.")
        await client.close()

    await client.start(token)


def run_bot():
    """Run the Discord bot."""
    token = os.environ["DISCORD_TOKEN"]
    channel_id = int(os.environ["DISCORD_CHANNEL_ID"])
    db_path = os.environ.get("DB_PATH", "tracks.db")

    db = TrackDatabase(db_path)
    bot = SongApprovalBot(db, channel_id)
    bot.run(token)


if __name__ == "__main__":
    run_bot()
