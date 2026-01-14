"""SQLite database for tracking processed songs."""

import sqlite3
from pathlib import Path
from datetime import datetime
from enum import Enum


class TrackStatus(Enum):
    PENDING = "pending"      # Waiting for user approval
    APPROVED = "approved"    # User said yes, ready to record
    REJECTED = "rejected"    # User said no
    RECORDED = "recorded"    # Recording complete
    SYNCED = "synced"        # Copied to MP3 player


class TrackDatabase:
    def __init__(self, db_path: str | Path = "tracks.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    spotify_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    album TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    added_at TEXT,
                    processed_at TEXT,
                    file_path TEXT
                )
            """)
            conn.commit()

    def add_track(self, spotify_id: str, name: str, artist: str, album: str, added_at: datetime) -> bool:
        """Add a new track. Returns False if already exists."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM tracks WHERE spotify_id = ?", (spotify_id,))
            if cursor.fetchone():
                return False

            cursor.execute(
                "INSERT INTO tracks (spotify_id, name, artist, album, added_at) VALUES (?, ?, ?, ?, ?)",
                (spotify_id, name, artist, album, added_at.isoformat())
            )
            conn.commit()
            return True

    def get_track(self, spotify_id: str) -> dict | None:
        """Get track by Spotify ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tracks WHERE spotify_id = ?", (spotify_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_status(self, spotify_id: str, status: TrackStatus, file_path: str | None = None):
        """Update track status."""
        with sqlite3.connect(self.db_path) as conn:
            if file_path:
                conn.execute(
                    "UPDATE tracks SET status = ?, file_path = ?, processed_at = ? WHERE spotify_id = ?",
                    (status.value, file_path, datetime.now().isoformat(), spotify_id)
                )
            else:
                conn.execute(
                    "UPDATE tracks SET status = ? WHERE spotify_id = ?",
                    (status.value, spotify_id)
                )
            conn.commit()

    def get_by_status(self, status: TrackStatus) -> list[dict]:
        """Get all tracks with given status."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tracks WHERE status = ?", (status.value,))
            return [dict(row) for row in cursor.fetchall()]

    def exists(self, spotify_id: str) -> bool:
        """Check if track already exists in database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM tracks WHERE spotify_id = ?", (spotify_id,))
            return cursor.fetchone() is not None
