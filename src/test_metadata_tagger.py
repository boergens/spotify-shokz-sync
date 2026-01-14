"""Test script for metadata_tagger.py"""

import tempfile
import struct
from pathlib import Path

from mutagen.mp3 import MP3
from mutagen.id3 import ID3

from metadata_tagger import tag_mp3, sanitize_filename, generate_filename


def create_minimal_mp3(path: Path):
    """Create a minimal valid MP3 file for testing."""
    # MP3 frame header for a silent frame (MPEG-1 Layer 3, 128kbps, 44100Hz, stereo)
    # Frame sync (11 bits) + version (2) + layer (2) + protection (1) + bitrate (4) + sample rate (2) + padding (1) + private (1) + channel (2) + mode ext (2) + copyright (1) + original (1) + emphasis (2)
    frame_header = bytes([0xFF, 0xFB, 0x90, 0x00])
    # Frame size for 128kbps at 44100Hz = 417 bytes (including header)
    frame_data = frame_header + bytes(413)
    # Write a few frames
    with open(path, "wb") as f:
        for _ in range(10):
            f.write(frame_data)


def test_tag_mp3():
    """Test basic tagging functionality."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mp3_path = Path(tmpdir) / "test.mp3"
        create_minimal_mp3(mp3_path)

        # Tag the file
        tag_mp3(
            mp3_path=mp3_path,
            title="Test Song",
            artist="Test Artist",
            album="Test Album",
            track_number=5,
            album_art_url=None  # Skip album art for basic test
        )

        # Read back and verify
        audio = MP3(mp3_path, ID3=ID3)
        assert audio.tags is not None, "Tags should exist"
        assert str(audio.tags.get("TIT2")) == "Test Song", f"Title mismatch: {audio.tags.get('TIT2')}"
        assert str(audio.tags.get("TPE1")) == "Test Artist", f"Artist mismatch: {audio.tags.get('TPE1')}"
        assert str(audio.tags.get("TALB")) == "Test Album", f"Album mismatch: {audio.tags.get('TALB')}"
        assert str(audio.tags.get("TRCK")) == "5", f"Track number mismatch: {audio.tags.get('TRCK')}"

        print("✓ Basic tagging test passed")


def test_tag_with_album_art():
    """Test tagging with album art from a real URL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mp3_path = Path(tmpdir) / "test_with_art.mp3"
        create_minimal_mp3(mp3_path)

        # Use a small test image URL (Spotify's smallest album art)
        test_art_url = "https://i.scdn.co/image/ab67616d00004851e8b066f70c206551210d902b"

        tag_mp3(
            mp3_path=mp3_path,
            title="Song With Art",
            artist="Artist Name",
            album="Album Name",
            track_number=1,
            album_art_url=test_art_url
        )

        audio = MP3(mp3_path, ID3=ID3)
        apic = audio.tags.get("APIC:Cover")
        if apic:
            print(f"✓ Album art embedded: {len(apic.data)} bytes")
        else:
            print("⚠ Album art not embedded (network issue?)")


def test_sanitize_filename():
    """Test filename sanitization."""
    assert sanitize_filename("Hello/World") == "Hello_World"
    assert sanitize_filename("Test:File") == "Test_File"
    assert sanitize_filename("Normal Name") == "Normal Name"
    assert sanitize_filename("<bad>name?") == "_bad_name_"
    print("✓ Filename sanitization test passed")


def test_generate_filename():
    """Test filename generation."""
    assert generate_filename("Artist", "Song") == "Artist - Song"
    assert generate_filename("Bad/Artist", "Bad:Song") == "Bad_Artist - Bad_Song"
    print("✓ Filename generation test passed")


if __name__ == "__main__":
    print("Running metadata tagger tests...\n")
    test_sanitize_filename()
    test_generate_filename()
    test_tag_mp3()
    test_tag_with_album_art()
    print("\nAll tests completed!")
