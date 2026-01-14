"""USB device detection and music sync to MP3 player."""

import os
import shutil
import time
from pathlib import Path
import platform

from database import TrackDatabase, TrackStatus


def get_usb_volumes() -> list[Path]:
    """Get list of mounted USB volumes.

    On Mac: scans /Volumes for non-system volumes.
    On Linux: scans /media and /mnt for mounted devices.
    """
    volumes = []
    system = platform.system()

    if system == "Darwin":  # macOS
        volumes_path = Path("/Volumes")
        if volumes_path.exists():
            # Exclude the main Macintosh HD
            for vol in volumes_path.iterdir():
                if vol.is_dir() and vol.name != "Macintosh HD":
                    volumes.append(vol)

    elif system == "Linux":
        # Check common mount points
        for base in ["/media", "/mnt"]:
            base_path = Path(base)
            if base_path.exists():
                # /media/<user>/<device> or /mnt/<device>
                for item in base_path.iterdir():
                    if item.is_dir():
                        if base == "/media":
                            # Check subdirectories (user folders)
                            for subitem in item.iterdir():
                                if subitem.is_dir():
                                    volumes.append(subitem)
                        else:
                            volumes.append(item)

    return volumes


def is_writable(path: Path) -> bool:
    """Check if a path is writable."""
    return os.access(path, os.W_OK)


def find_music_folder(volume: Path) -> Path | None:
    """Find or create a Music folder on the USB volume.

    Looks for existing music folders first, creates one if needed.
    Returns the path to use for syncing music, or None if not writable.
    """
    # Skip read-only volumes
    if not is_writable(volume):
        return None

    # Common music folder names to look for
    music_names = ["Music", "MUSIC", "music", "Mp3", "MP3", "Songs"]

    for name in music_names:
        folder = volume / name
        if folder.is_dir():
            return folder

    # No existing folder found - create Music folder
    music_folder = volume / "Music"
    music_folder.mkdir(exist_ok=True)
    return music_folder


def get_files_on_device(music_folder: Path) -> set[str]:
    """Get set of mp3 filenames already on the device."""
    files = set()
    for f in music_folder.glob("*.mp3"):
        files.add(f.name)
    return files


def sync_tracks_to_device(
    music_folder: Path,
    db: TrackDatabase,
    source_dir: Path
) -> list[dict]:
    """Sync recorded tracks to USB device.

    Args:
        music_folder: Destination folder on USB device
        db: Track database
        source_dir: Local music library directory

    Returns:
        List of tracks that were synced
    """
    # Get tracks that have been recorded but not synced
    recorded_tracks = db.get_by_status(TrackStatus.RECORDED)

    if not recorded_tracks:
        return []

    # Get files already on device
    existing_files = get_files_on_device(music_folder)

    synced = []
    for track in recorded_tracks:
        file_path = track.get("file_path")
        if not file_path:
            continue

        source = Path(file_path)
        if not source.exists():
            # Try relative to source_dir
            source = source_dir / source.name
            if not source.exists():
                print(f"Source file not found: {file_path}")
                continue

        filename = source.name

        # Skip if already on device
        if filename in existing_files:
            # Mark as synced since it's already there
            db.update_status(track["spotify_id"], TrackStatus.SYNCED)
            synced.append(track)
            continue

        # Copy file to device
        dest = music_folder / filename
        print(f"Copying: {filename}")
        shutil.copy2(source, dest)

        # Update database
        db.update_status(track["spotify_id"], TrackStatus.SYNCED)
        synced.append(track)

    return synced


def run_sync(source_dir: Path, db_path: Path | str = "tracks.db") -> dict:
    """Run a single sync operation.

    Detects USB volumes and syncs any recorded tracks.

    Args:
        source_dir: Local music library directory
        db_path: Path to track database

    Returns:
        Dict with sync results
    """
    db = TrackDatabase(db_path)
    volumes = get_usb_volumes()

    if not volumes:
        return {"status": "no_device", "synced": []}

    all_synced = []
    for volume in volumes:
        music_folder = find_music_folder(volume)
        if music_folder:
            print(f"Found USB volume: {volume.name}")
            synced = sync_tracks_to_device(music_folder, db, source_dir)
            all_synced.extend(synced)
            if synced:
                print(f"Synced {len(synced)} tracks to {volume.name}")

    return {"status": "ok", "synced": all_synced}


def watch_and_sync(
    source_dir: Path,
    db_path: Path | str = "tracks.db",
    poll_interval: int = 5
):
    """Continuously watch for USB devices and sync when detected.

    Args:
        source_dir: Local music library directory
        db_path: Path to track database
        poll_interval: Seconds between device checks
    """
    print(f"USB sync monitor started. Watching for devices...")
    print(f"Source directory: {source_dir}")

    known_volumes = set()

    while True:
        current_volumes = set(get_usb_volumes())

        # Detect newly connected volumes
        new_volumes = current_volumes - known_volumes

        for volume in new_volumes:
            print(f"\nNew USB device detected: {volume.name}")
            result = run_sync(source_dir, db_path)
            if result["synced"]:
                print(f"Sync complete: {len(result['synced'])} tracks copied")
            else:
                print("No new tracks to sync")

        # Detect removed volumes
        removed = known_volumes - current_volumes
        for volume in removed:
            print(f"USB device removed: {volume.name}")

        known_volumes = current_volumes
        time.sleep(poll_interval)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="USB sync for music library")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("recordings"),
        help="Source directory with recorded tracks"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("tracks.db"),
        help="Path to track database"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run sync once and exit (don't watch)"
    )

    args = parser.parse_args()

    if args.once:
        result = run_sync(args.source, args.db)
        if result["status"] == "no_device":
            print("No USB devices found")
        else:
            print(f"Synced {len(result['synced'])} tracks")
    else:
        watch_and_sync(args.source, args.db)
