# Spotify to MP3 Car Sync System

## Implementation Plan

**Version 1.0 — January 2026**

## Executive Summary

This document outlines the implementation plan for an automated system that monitors a Spotify liked songs playlist, records approved tracks via loopback audio capture, and syncs them to a portable MP3 player. The system runs on a low-power car computer that connects to a mobile hotspot for internet access.

## System Overview

### Core Workflow

- System detects phone hotspot and connects automatically
- Spotify API is polled for new liked songs (added after November 2025)
- Discord notification sent: "Hey Kevin, found 'Song X' by Artist Y. Download it?"
- User responds "yes" via Discord
- System plays track via Spotify, captures audio via loopback recording
- Audio encoded to 192kbps MP3 with metadata and cover art
- MP3 saved to local storage
- When MP3 player is connected via USB, new tracks are synced automatically
- Discord confirmation: "Done! 'Song X' is on your player."

### Key Constraints

- No screen or keyboard on the device
- Internet only available when phone hotspot is in range
- Recording is real-time (3-minute song = 3 minutes to record)
- MP3 player not always connected; local storage is primary

## Hardware Requirements

### Recommended: Raspberry Pi Zero 2 W

| Component | Specification |
|-----------|---------------|
| Processor | Quad-core ARM Cortex-A53 @ 1GHz |
| RAM | 512MB |
| WiFi | 2.4GHz 802.11 b/g/n (built-in) |
| Storage | MicroSD card (32GB+ recommended) |
| Power | 5V via micro-USB (cigarette lighter adapter) |
| Price | ~$15 USD |

Alternative: Raspberry Pi 4 if more processing power is needed for Claude Code debugging sessions. Draws more power but significantly faster.

### Additional Hardware

| Item | Notes |
|------|-------|
| USB Audio Adapter | Required for loopback recording (Pi has no audio input) |
| MicroSD Card | 32GB minimum; 64GB+ for larger music library |
| Cigarette Lighter USB Adapter | 5V 2A+ output |
| Rugged Case | Protect from heat, vibration, dust |
| USB Hub (optional) | If MP3 player needs dedicated port |

## Software Components

### Operating System

Raspberry Pi OS Lite (64-bit) — headless, no desktop environment needed.

### Component Architecture

| Component | Technology | Purpose |
|-----------|------------|---------|
| WiFi Manager | NetworkManager / wpa_supplicant | Auto-connect to phone hotspot |
| Spotify Monitor | Python + spotipy library | Poll liked songs via Spotify Web API |
| Discord Bot | Python + discord.py | Notifications and approval workflow |
| Spotify Player | spotifyd (headless daemon) | Play tracks for recording |
| Audio Recorder | PulseAudio + FFmpeg | Loopback capture, encode to MP3 |
| Metadata Tagger | Python + mutagen | Embed artist, album, cover art |
| USB Sync | Python + pyudev | Detect MP3 player, copy new files |
| Remote Debug | Claude Code + SSH tunnel | Remote debugging access |
| Main Orchestrator | Python (async) | Coordinate all components |

### Key Dependencies

- **spotifyd** — Lightweight Spotify Connect client (requires Premium)
- **spotipy** — Python wrapper for Spotify Web API
- **discord.py** — Discord bot framework
- **PulseAudio** — Audio routing and loopback
- **FFmpeg** — Audio encoding (WAV to MP3)
- **mutagen** — MP3 ID3 tag editing
- **pyudev** — USB device detection

## Implementation Phases

### Phase 1: Hardware Setup and Base OS

- Flash Raspberry Pi OS Lite to SD card
- Configure headless setup (SSH enabled, WiFi credentials)
- Install USB audio adapter, verify detection with `aplay -l`
- Configure auto-connect to phone hotspot SSID
- Test power from cigarette lighter adapter

### Phase 2: Spotify Integration

- Create Spotify Developer application, obtain client credentials
- Install and configure spotifyd daemon
- Implement liked songs monitor with spotipy
- Add date filter (only songs added after November 2025)
- Implement track database to avoid re-processing

### Phase 3: Discord Bot

- Create Discord bot application, obtain token
- Implement notification messages for new songs
- Implement approval listener ("yes" / "no" responses)
- Add completion notifications
- Handle pending approvals (persist across restarts)

### Phase 4: Audio Recording Pipeline

- Configure PulseAudio loopback module
- Implement recording controller: start spotifyd playback, capture audio
- Detect track end (silence detection or Spotify API polling)
- Encode captured WAV to 192kbps MP3 via FFmpeg
- Fetch metadata and cover art from Spotify API
- Embed ID3 tags using mutagen

### Phase 5: USB Sync

- Implement USB device detection with pyudev
- Auto-mount mass storage devices
- Compare local library with MP3 player contents
- Copy new tracks, handle interruptions gracefully
- Send Discord notification on sync complete

### Phase 6: Remote Debugging

- Set up persistent SSH reverse tunnel (autossh)
- Install Claude Code CLI
- Document access procedure for debugging sessions

### Phase 7: Integration and Testing

- Create systemd service for main orchestrator (auto-start on boot)
- End-to-end testing: add song → approve → record → sync
- Test hotspot reconnection behavior
- Test power interruption recovery
- Install in car for real-world testing

## Technical Specifications

### Audio Pipeline

| Parameter | Value |
|-----------|-------|
| Source Quality | 320kbps (Spotify Premium) |
| Recording Format | WAV (44.1kHz, 16-bit, stereo) |
| Output Format | MP3 192kbps CBR |
| Metadata | ID3v2.4 (artist, album, title, track#, cover art) |
| Cover Art | 640x640 JPEG (from Spotify API) |

### File Organization

- Local storage path: `/home/pi/music/`
- Naming convention: `Artist - Title.mp3`
- Database: SQLite file tracking processed songs, approval status, sync status

### API Rate Limits

| API | Consideration |
|-----|---------------|
| Spotify Web API | Poll every 5-10 minutes when connected |
| Discord API | No concerns at this message volume |

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Spotify API changes | System stops detecting new songs | Monitor spotipy releases; API is stable |
| spotifyd authentication expires | Cannot play tracks for recording | Use refresh tokens; alert via Discord |
| SD card corruption | Data loss, system failure | Use quality SD card; periodic backups |
| Car heat damage | Hardware failure | Rugged case; mount away from direct sun |
| Phone hotspot not available | No internet, queue builds up | Graceful offline mode; retry on connect |
| Recording quality issues | Poor audio quality | Test audio chain; use quality USB adapter |

## Appendix: Quick Reference Commands

### SSH Access

```bash
ssh pi@<car-pi-hostname>.local
```

### Service Management

```bash
sudo systemctl status spotify-sync
sudo systemctl restart spotify-sync
sudo journalctl -u spotify-sync -f
```

### Audio Troubleshooting

```bash
aplay -l                    # List audio devices
pactl list short sinks      # List PulseAudio sinks
pactl list short sources    # List PulseAudio sources
```

### Manual Sync Trigger

```bash
python3 /home/pi/spotify-sync/sync_now.py
```
