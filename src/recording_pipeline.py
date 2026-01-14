"""Recording pipeline: play track, record audio, tag MP3."""

import asyncio
import os
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from audio_recorder import RecordingConfig, record_until_silence
from metadata_tagger import tag_mp3, generate_filename
from database import TrackDatabase, TrackStatus
from spotify_monitor import Track, get_track_by_id


# Extended scope for playback control
SCOPE = "user-library-read user-modify-playback-state user-read-playback-state"


def create_spotify_client_with_playback() -> spotipy.Spotify:
    """Create Spotify client with playback control permissions."""
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=os.environ["SPOTIFY_CLIENT_ID"],
        client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
        redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback"),
        scope=SCOPE,
    ))


def get_active_device(sp: spotipy.Spotify) -> str | None:
    """Get the ID of an active Spotify playback device."""
    devices = sp.devices()
    for device in devices.get("devices", []):
        if device.get("is_active"):
            return device["id"]
    # Return first available device if none active
    if devices.get("devices"):
        return devices["devices"][0]["id"]
    return None


def play_track(sp: spotipy.Spotify, track_id: str, device_id: str | None = None):
    """Start playback of a track."""
    uri = f"spotify:track:{track_id}"
    sp.start_playback(device_id=device_id, uris=[uri])


def stop_playback(sp: spotipy.Spotify, device_id: str | None = None):
    """Stop playback."""
    sp.pause_playback(device_id=device_id)


async def record_track(
    track: Track,
    output_dir: Path,
    config: RecordingConfig | None = None
) -> Path:
    """
    Record a track from Spotify via loopback audio.

    This expects:
    - Spotify to be playing through BlackHole (or configured audio device)
    - Audio device routed so system audio goes to BlackHole

    Args:
        track: Track metadata from Spotify
        output_dir: Directory to save the MP3
        config: Recording configuration

    Returns:
        Path to the final tagged MP3 file
    """
    config = config or RecordingConfig()
    config.output_dir = output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename
    filename = generate_filename(track.artist, track.name)
    output_path = output_dir / filename

    # Calculate max duration (track duration + buffer for silence detection)
    max_duration = (track.duration_ms / 1000) + 10  # Add 10s buffer

    # Record audio (blocking, runs in thread pool)
    mp3_path = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: record_until_silence(
            output_path=output_path,
            max_duration_seconds=max_duration,
            config=config
        )
    )

    # Tag the MP3 with metadata
    tag_mp3(
        mp3_path=mp3_path,
        title=track.name,
        artist=track.artist,
        album=track.album,
        album_art_url=track.album_art_url
    )

    return mp3_path


async def process_approved_track(
    db: TrackDatabase,
    spotify_id: str,
    output_dir: Path,
    config: RecordingConfig | None = None
) -> Path | None:
    """
    Process a single approved track: play, record, tag, update DB.

    Args:
        db: Track database
        spotify_id: Spotify track ID
        output_dir: Where to save MP3s
        config: Recording configuration

    Returns:
        Path to recorded MP3, or None if failed
    """
    sp = create_spotify_client_with_playback()

    # Get track info
    track = get_track_by_id(sp, spotify_id)
    device_id = get_active_device(sp)

    if not device_id:
        print("No active Spotify device found. Please open Spotify.")
        return None

    print(f"Recording: {track.name} by {track.artist}")
    print(f"Duration: {track.duration_ms / 1000:.0f}s")

    # Start playback
    play_track(sp, spotify_id, device_id)

    # Small delay for playback to start
    await asyncio.sleep(0.5)

    # Record the track
    mp3_path = await record_track(track, output_dir, config)

    # Stop playback
    stop_playback(sp, device_id)

    # Update database
    db.update_status(spotify_id, TrackStatus.RECORDED, str(mp3_path))

    print(f"Completed: {mp3_path}")
    return mp3_path


async def process_all_approved(
    db: TrackDatabase,
    output_dir: Path,
    config: RecordingConfig | None = None
) -> list[Path]:
    """
    Process all approved tracks in the database.

    Args:
        db: Track database
        output_dir: Where to save MP3s
        config: Recording configuration

    Returns:
        List of paths to recorded MP3s
    """
    approved = db.get_by_status(TrackStatus.APPROVED)

    if not approved:
        print("No approved tracks to process")
        return []

    print(f"Found {len(approved)} approved track(s)")
    results = []

    for track_row in approved:
        path = await process_approved_track(
            db=db,
            spotify_id=track_row["spotify_id"],
            output_dir=output_dir,
            config=config
        )
        if path:
            results.append(path)

        # Small delay between tracks
        await asyncio.sleep(2)

    return results


if __name__ == "__main__":
    import sys

    db_path = os.environ.get("DB_PATH", "tracks.db")
    output_dir = Path(os.environ.get("OUTPUT_DIR", "recordings"))

    db = TrackDatabase(db_path)

    if len(sys.argv) > 1:
        # Process specific track
        track_id = sys.argv[1]
        asyncio.run(process_approved_track(db, track_id, output_dir))
    else:
        # Process all approved
        asyncio.run(process_all_approved(db, output_dir))
