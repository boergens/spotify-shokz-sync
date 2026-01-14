"""Audio recording pipeline using FFmpeg with BlackHole loopback."""

import subprocess
import os
from pathlib import Path
from dataclasses import dataclass


@dataclass
class RecordingConfig:
    audio_device: str = "BlackHole 2ch"  # AVFoundation device name
    sample_rate: int = 44100
    channels: int = 2
    mp3_bitrate: str = "192k"
    output_dir: Path = Path("recordings")


def list_audio_devices() -> list[str]:
    """List available audio input devices on Mac."""
    result = subprocess.run(
        ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True
    )
    # Parse device list from stderr (ffmpeg outputs to stderr)
    # Format: [AVFoundation indev @ 0x...] [N] Device Name
    lines = result.stderr.split("\n")
    devices = []
    in_audio_section = False
    for line in lines:
        if "AVFoundation audio devices:" in line:
            in_audio_section = True
            continue
        if in_audio_section and line.startswith("[AVFoundation"):
            # Find the second ] which ends the device index
            first_bracket = line.find("]")
            if first_bracket == -1:
                continue
            second_bracket = line.find("]", first_bracket + 1)
            if second_bracket == -1:
                continue
            device_name = line[second_bracket + 2:].strip()
            if device_name:
                devices.append(device_name)
    return devices


def find_device_index(device_name: str) -> int | None:
    """Find the index of an audio device by name."""
    result = subprocess.run(
        ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True
    )
    # Format: [AVFoundation indev @ 0x...] [N] Device Name
    lines = result.stderr.split("\n")
    in_audio_section = False
    for line in lines:
        if "AVFoundation audio devices:" in line:
            in_audio_section = True
            continue
        if in_audio_section and line.startswith("[AVFoundation") and device_name in line:
            # Find the device index between second [ and ]
            first_bracket = line.find("]")
            if first_bracket == -1:
                continue
            idx_start = line.find("[", first_bracket + 1)
            idx_end = line.find("]", first_bracket + 1)
            if idx_start != -1 and idx_end != -1:
                return int(line[idx_start + 1:idx_end])
    return None


def record_audio(
    output_path: Path,
    duration_seconds: float,
    config: RecordingConfig | None = None
) -> Path:
    """
    Record audio from the configured device for the specified duration.

    Args:
        output_path: Where to save the MP3 file (without extension)
        duration_seconds: How long to record
        config: Recording configuration (uses defaults if not provided)

    Returns:
        Path to the final MP3 file
    """
    config = config or RecordingConfig()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    device_index = find_device_index(config.audio_device)
    if device_index is None:
        available = list_audio_devices()
        raise RuntimeError(
            f"Audio device '{config.audio_device}' not found. "
            f"Available devices: {available}"
        )

    # Output paths
    mp3_path = output_path.with_suffix(".mp3")

    # Record directly to MP3 using ffmpeg
    # -f avfoundation: use macOS AVFoundation
    # -i ":N": audio device only (no video), where N is device index
    # -t: duration in seconds
    # -ar: sample rate
    # -ac: audio channels
    # -b:a: audio bitrate
    cmd = [
        "ffmpeg",
        "-f", "avfoundation",
        "-i", f":{device_index}",
        "-t", str(duration_seconds),
        "-ar", str(config.sample_rate),
        "-ac", str(config.channels),
        "-b:a", config.mp3_bitrate,
        "-y",  # overwrite output
        str(mp3_path)
    ]

    print(f"Recording from '{config.audio_device}' for {duration_seconds}s...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg recording failed: {result.stderr}")

    print(f"Saved: {mp3_path}")
    return mp3_path


def record_until_silence(
    output_path: Path,
    max_duration_seconds: float,
    silence_threshold_db: float = -50,
    silence_duration_seconds: float = 3.0,
    config: RecordingConfig | None = None
) -> Path:
    """
    Record audio until silence is detected or max duration reached.

    Uses a two-pass approach:
    1. Record raw audio for max duration
    2. Detect where silence starts and trim

    Args:
        output_path: Where to save the MP3 file (without extension)
        max_duration_seconds: Maximum recording time
        silence_threshold_db: dB level below which is considered silence
        silence_duration_seconds: How long silence must last to stop
        config: Recording configuration

    Returns:
        Path to the final trimmed MP3 file
    """
    config = config or RecordingConfig()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    device_index = find_device_index(config.audio_device)
    if device_index is None:
        available = list_audio_devices()
        raise RuntimeError(
            f"Audio device '{config.audio_device}' not found. "
            f"Available devices: {available}"
        )

    # Temp file for raw recording
    temp_wav = config.output_dir / f"_temp_{output_path.stem}.wav"
    mp3_path = output_path.with_suffix(".mp3")

    # Step 1: Record to WAV
    record_cmd = [
        "ffmpeg",
        "-f", "avfoundation",
        "-i", f":{device_index}",
        "-t", str(max_duration_seconds),
        "-ar", str(config.sample_rate),
        "-ac", str(config.channels),
        "-y",
        str(temp_wav)
    ]

    print(f"Recording from '{config.audio_device}' (max {max_duration_seconds}s)...")
    result = subprocess.run(record_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg recording failed: {result.stderr}")

    # Step 2: Detect silence and get duration to keep
    # Use silencedetect filter to find where silence starts
    detect_cmd = [
        "ffmpeg",
        "-i", str(temp_wav),
        "-af", f"silencedetect=noise={silence_threshold_db}dB:d={silence_duration_seconds}",
        "-f", "null",
        "-"
    ]

    result = subprocess.run(detect_cmd, capture_output=True, text=True)

    # Parse silence detection output
    # Look for "silence_start: X.XXX" in stderr
    trim_duration = max_duration_seconds
    for line in result.stderr.split("\n"):
        if "silence_start:" in line:
            # Found silence - trim to this point
            parts = line.split("silence_start:")
            if len(parts) > 1:
                try:
                    silence_start = float(parts[1].strip().split()[0])
                    trim_duration = silence_start
                    print(f"Detected silence at {silence_start:.1f}s")
                    break
                except ValueError:
                    pass

    # Step 3: Encode trimmed audio to MP3
    encode_cmd = [
        "ffmpeg",
        "-i", str(temp_wav),
        "-t", str(trim_duration),
        "-ar", str(config.sample_rate),
        "-ac", str(config.channels),
        "-b:a", config.mp3_bitrate,
        "-y",
        str(mp3_path)
    ]

    result = subprocess.run(encode_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg encoding failed: {result.stderr}")

    # Cleanup temp file
    temp_wav.unlink(missing_ok=True)

    print(f"Saved: {mp3_path} ({trim_duration:.1f}s)")
    return mp3_path


if __name__ == "__main__":
    # Quick test
    print("Available audio devices:")
    for device in list_audio_devices():
        print(f"  - {device}")

    print("\nTo test recording, ensure BlackHole is installed and run:")
    print("  python -c \"from audio_recorder import *; record_audio(Path('test'), 5)\"")
