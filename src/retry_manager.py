"""CLI tool for managing stuck tracks and manual retries."""

import argparse
from pathlib import Path

from database import TrackDatabase, TrackStatus


def list_stuck(db: TrackDatabase, max_retries: int = 5):
    """List all tracks that have exceeded max retries."""
    stuck = db.get_stuck_tracks(max_retries)
    if not stuck:
        print("No stuck tracks.")
        return

    print(f"Found {len(stuck)} stuck track(s):\n")
    for track in stuck:
        print(f"  {track['name']} - {track['artist']}")
        print(f"    ID: {track['spotify_id']}")
        print(f"    Status: {track['status']}")
        print(f"    Retries: {track.get('retry_count', 0)}")
        print(f"    Last error: {track.get('last_error', 'N/A')}")
        print()


def retry_track(db: TrackDatabase, spotify_id: str):
    """Force retry a specific track."""
    track = db.get_track(spotify_id)
    if not track:
        print(f"Track not found: {spotify_id}")
        return

    db.force_retry(spotify_id)
    print(f"Reset retry state for: {track['name']} - {track['artist']}")
    print("Track will be processed on next cycle.")


def retry_all_stuck(db: TrackDatabase, max_retries: int = 5):
    """Force retry all stuck tracks."""
    stuck = db.get_stuck_tracks(max_retries)
    if not stuck:
        print("No stuck tracks to retry.")
        return

    for track in stuck:
        db.force_retry(track["spotify_id"])
        print(f"Reset: {track['name']}")

    print(f"\nReset {len(stuck)} track(s). They will be processed on next cycle.")


def show_status(db: TrackDatabase):
    """Show counts by status."""
    for status in TrackStatus:
        tracks = db.get_by_status(status)
        print(f"{status.value}: {len(tracks)}")


def main():
    parser = argparse.ArgumentParser(description="Manage stuck tracks and retries")
    parser.add_argument("--db", type=Path, default=Path("tracks.db"))

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show track counts by status")
    subparsers.add_parser("stuck", help="List stuck tracks")

    retry_parser = subparsers.add_parser("retry", help="Force retry a track")
    retry_parser.add_argument("track_id", help="Spotify track ID to retry")

    subparsers.add_parser("retry-all", help="Force retry all stuck tracks")

    args = parser.parse_args()
    db = TrackDatabase(args.db)

    if args.command == "status":
        show_status(db)
    elif args.command == "stuck":
        list_stuck(db)
    elif args.command == "retry":
        retry_track(db, args.track_id)
    elif args.command == "retry-all":
        retry_all_stuck(db)


if __name__ == "__main__":
    main()
