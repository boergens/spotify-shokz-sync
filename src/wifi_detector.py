"""WiFi network detection for triggering sync operations."""

import subprocess
import platform


def get_current_ssid() -> str | None:
    """Get the currently connected WiFi network SSID.

    Returns:
        SSID string if connected, None if not connected or error.
    """
    system = platform.system()

    if system == "Darwin":  # macOS
        return _get_ssid_macos()
    elif system == "Linux":
        return _get_ssid_linux()
    else:
        return None


def _get_ssid_macos() -> str | None:
    """Get SSID on macOS using airport command."""
    result = subprocess.run(
        ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("SSID:"):
            return line.split(":", 1)[1].strip()

    return None


def _get_ssid_linux() -> str | None:
    """Get SSID on Linux using nmcli or iwgetid."""
    # Try nmcli first (NetworkManager)
    result = subprocess.run(
        ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1]

    # Fallback to iwgetid
    result = subprocess.run(
        ["iwgetid", "-r"],
        capture_output=True,
        text=True
    )

    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()

    return None


def is_connected_to(target_ssid: str) -> bool:
    """Check if currently connected to a specific WiFi network.

    Args:
        target_ssid: The SSID to check for.

    Returns:
        True if connected to the target network.
    """
    current = get_current_ssid()
    return current is not None and current == target_ssid


def is_connected() -> bool:
    """Check if connected to any WiFi network.

    Returns:
        True if connected to WiFi.
    """
    return get_current_ssid() is not None


if __name__ == "__main__":
    ssid = get_current_ssid()
    if ssid:
        print(f"Connected to: {ssid}")
    else:
        print("Not connected to WiFi")
