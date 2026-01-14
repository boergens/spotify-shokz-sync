"""Spotify liked songs monitor using spotipy."""

import os
from datetime import datetime
from dataclasses import dataclass

import spotipy
from spotipy.oauth2 import SpotifyOAuth


CUTOFF_DATE = datetime(2025, 11, 1)
SCOPE = "user-library-read"


@dataclass
class Track:
    id: str
    name: str
    artist: str
    album: str
    album_art_url: str | None
    added_at: datetime
    duration_ms: int


def create_spotify_client() -> spotipy.Spotify:
    """Create authenticated Spotify client."""
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=os.environ["SPOTIFY_CLIENT_ID"],
        client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
        redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback"),
        scope=SCOPE,
    ))


def get_new_liked_songs(sp: spotipy.Spotify, since: datetime = CUTOFF_DATE) -> list[Track]:
    """Fetch liked songs added after the given date."""
    tracks = []
    offset = 0
    limit = 50

    while True:
        results = sp.current_user_saved_tracks(limit=limit, offset=offset)
        items = results["items"]

        if not items:
            break

        for item in items:
            added_at = datetime.fromisoformat(item["added_at"].replace("Z", "+00:00"))
            added_at = added_at.replace(tzinfo=None)  # Make naive for comparison

            if added_at < since:
                # Songs are returned newest first, so we can stop here
                return tracks

            track_data = item["track"]
            album_images = track_data["album"]["images"]

            tracks.append(Track(
                id=track_data["id"],
                name=track_data["name"],
                artist=track_data["artists"][0]["name"],
                album=track_data["album"]["name"],
                album_art_url=album_images[0]["url"] if album_images else None,
                added_at=added_at,
                duration_ms=track_data["duration_ms"],
            ))

        offset += limit

        if not results["next"]:
            break

    return tracks


def get_track_by_id(sp: spotipy.Spotify, track_id: str) -> Track:
    """Fetch a single track by ID."""
    track_data = sp.track(track_id)
    album_images = track_data["album"]["images"]

    return Track(
        id=track_data["id"],
        name=track_data["name"],
        artist=track_data["artists"][0]["name"],
        album=track_data["album"]["name"],
        album_art_url=album_images[0]["url"] if album_images else None,
        added_at=datetime.now(),  # Not available from this endpoint
        duration_ms=track_data["duration_ms"],
    )
