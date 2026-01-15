"""ID3 metadata tagging for MP3 files."""

import urllib.request
from pathlib import Path

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, TRCK


def tag_mp3(
    mp3_path: Path,
    title: str,
    artist: str,
    album: str,
    track_number: int | None = None,
    album_art_url: str | None = None
) -> None:
    """
    Add ID3 tags to an MP3 file.

    Args:
        mp3_path: Path to the MP3 file
        title: Song title
        artist: Artist name
        album: Album name
        track_number: Track number on album (optional)
        album_art_url: URL to album art image (optional)
    """
    audio = MP3(mp3_path, ID3=ID3)

    # Create ID3 tag if it doesn't exist
    if audio.tags is None:
        audio.add_tags()

    # Clear existing tags
    audio.tags.delall("TIT2")
    audio.tags.delall("TPE1")
    audio.tags.delall("TALB")
    audio.tags.delall("TRCK")
    audio.tags.delall("APIC")

    # Add metadata
    audio.tags.add(TIT2(encoding=3, text=title))
    audio.tags.add(TPE1(encoding=3, text=artist))
    audio.tags.add(TALB(encoding=3, text=album))

    if track_number is not None:
        audio.tags.add(TRCK(encoding=3, text=str(track_number)))

    # Download and embed album art
    if album_art_url:
        image_data = fetch_album_art(album_art_url)
        if image_data:
            audio.tags.add(APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,  # Cover (front)
                desc="Cover",
                data=image_data
            ))

    audio.save()
    print(f"Tagged: {title} by {artist}")


def fetch_album_art(url: str) -> bytes | None:
    """Download album art from URL."""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.read()
    except Exception as e:
        print(f"Failed to fetch album art: {e}")
        return None


def sanitize_filename(name: str) -> str:
    """Create a safe filename from a string."""
    # Remove/replace characters that are problematic in filenames
    unsafe_chars = '<>:"/\\|?*'
    for char in unsafe_chars:
        name = name.replace(char, "_")
    return name.strip()


def generate_filename(artist: str, title: str) -> str:
    """Generate a filename in 'Artist - Title' format."""
    safe_artist = sanitize_filename(artist)
    safe_title = sanitize_filename(title)
    return f"{safe_artist} - {safe_title}"
