"""Set these values before building and publishing a numbered GitHub release."""

VERSION = "0.1.12A"
# Increase for every Android release, even when changing the visible numbering.
ANDROID_VERSION_CODE = 1026411
REPOSITORY = "miguel-pino20/NetPlayNaruto_KOTH"
INCLUDE_PRERELEASES = True

ASSET_NAMES = {
    "android": "UN5-Netplay-Android-arm64-debug.apk",
    "linux": "UN5-Netplay-x86_64.AppImage",
    "windows": "UN5-Netplay-Windows-x64.exe",
}
