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
                    album_art_url TEXT,
                    track_number INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    added_at TEXT,
                    processed_at TEXT,
                    file_path TEXT
                )
            """)
            # Add new columns if they don't exist (for existing databases)
            new_columns = [
                ("album_art_url", "TEXT"),
                ("track_number", "INTEGER"),
                ("retry_count", "INTEGER DEFAULT 0"),
                ("last_error", "TEXT"),
                ("last_retry_at", "TEXT"),
            ]
            for col, col_type in new_columns:
                try:
                    conn.execute(f"ALTER TABLE tracks ADD COLUMN {col} {col_type}")
                except sqlite3.OperationalError:
                    pass  # Column already exists

            conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status)")
            conn.commit()

    def add_track(
        self,
        spotify_id: str,
        name: str,
        artist: str,
        album: str,
        added_at: datetime,
        album_art_url: str | None = None,
        track_number: int | None = None
    ) -> bool:
        """Add a new track. Returns False if already exists."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM tracks WHERE spotify_id = ?", (spotify_id,))
            if cursor.fetchone():
                return False

            cursor.execute(
                """INSERT INTO tracks
                   (spotify_id, name, artist, album, added_at, album_art_url, track_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (spotify_id, name, artist, album, added_at.isoformat(), album_art_url, track_number)
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

    def record_failure(self, spotify_id: str, error: str):
        """Record a failed processing attempt."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE tracks
                   SET retry_count = COALESCE(retry_count, 0) + 1,
                       last_error = ?,
                       last_retry_at = ?
                   WHERE spotify_id = ?""",
                (error, datetime.now().isoformat(), spotify_id)
            )
            conn.commit()

    def reset_retry(self, spotify_id: str):
        """Reset retry count after successful processing."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE tracks
                   SET retry_count = 0, last_error = NULL, last_retry_at = NULL
                   WHERE spotify_id = ?""",
                (spotify_id,)
            )
            conn.commit()

    def get_retry_eligible(
        self,
        status: TrackStatus,
        max_retries: int = 5,
        min_backoff_minutes: int = 5
    ) -> list[dict]:
        """Get tracks eligible for retry based on exponential backoff.

        Backoff schedule: 5min, 10min, 20min, 40min, 80min (then gives up)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM tracks
                   WHERE status = ?
                   AND (retry_count IS NULL OR retry_count < ?)
                   AND (
                       last_retry_at IS NULL
                       OR datetime(last_retry_at, '+' || (? * (1 << COALESCE(retry_count, 0))) || ' minutes') < datetime('now', 'localtime')
                   )""",
                (status.value, max_retries, min_backoff_minutes)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_stuck_tracks(self, max_retries: int = 5) -> list[dict]:
        """Get tracks that have exceeded max retries."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """SELECT * FROM tracks
                   WHERE retry_count >= ?
                   AND status IN (?, ?)""",
                (max_retries, TrackStatus.APPROVED.value, TrackStatus.RECORDED.value)
            )
            return [dict(row) for row in cursor.fetchall()]

    def force_retry(self, spotify_id: str):
        """Force a track to be retried by resetting its retry state."""
        self.reset_retry(spotify_id)
