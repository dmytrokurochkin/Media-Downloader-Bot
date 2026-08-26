"""
Self-healing yt-dlp updater.

Why this exists
---------------
yt-dlp breaks whenever YouTube changes its backend, and old builds silently
stop working (extraction fails with "Requested format is not available" /
"Sign in to confirm your age" / generic Extractor errors).  requirements.txt
pins the *minimum known-good* version for fresh installs, but a long-running
bot still needs to keep moving.  This module keeps yt-dlp current so the bot
does not "break again" weeks after deploy.

Two integration points (both idempotent and safe):
  * ``ExecStartPre`` on the bot service  -> runs BEFORE the bot imports
    yt-dlp, so the fresh process loads the newest build.
  * a weekly systemd timer             -> keeps the venv current while the
    bot stays up for months between restarts.

Safety model: if ``pip`` fails (no network, locked package, etc.) we KEEP the
currently working version and report failure.  We never downgrade and we
never install anything else.
"""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys

# Floor for fresh installs / sanity check.  Bump this constant whenever a new
# yt-dlp release is the first that works again after a YouTube change.  The
# updater upgrades to the *latest* when the installed version is below this,
# which in practice always lands on the newest release.
MIN_YT_DLP = "2026.8.19"

BOT_SERVICE = "tg-media-bot"


def get_installed_version() -> str | None:
    """Return the installed yt-dlp version, or None if it is missing."""
    try:
        return importlib.metadata.version("yt-dlp")
    except Exception:
        return None


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse an yt-dlp date version (YYYY.MM.DD) into a comparable tuple."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


def is_below_minimum(current: str | None, minimum: str = MIN_YT_DLP) -> bool:
    """True if `current` is older than `minimum` (or unknown)."""
    if current is None:
        return True
    return _version_tuple(current) < _version_tuple(minimum)


def _run_pip_upgrade(timeout: int = 300) -> bool:
    """Upgrade yt-dlp in the interpreter this module runs under."""
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode == 0
    except Exception as exc:  # noqa: BLE001 - keep the working version on any failure
        print(f"yt-dlp upgrade failed: {exc}", file=sys.stderr)
        return False


def ensure_yt_dlp(minimum: str = MIN_YT_DLP) -> bool:
    """
    Upgrade yt-dlp if it is at/ below the minimum floor.

    Returns True when the installed version CHANGED (callers may want to
    restart the bot so the freshly installed build is loaded), False otherwise
    (already current, or upgrade failed and the working version is kept).
    """
    before = get_installed_version()
    if not is_below_minimum(before, minimum):
        # Already at or above the floor; still bump to the absolute latest so
        # we track yt-dlp's own release cadence.
        _run_pip_upgrade()
    else:
        if not _run_pip_upgrade():
            print(
                f"Keeping working yt-dlp {before!r} (upgrade failed).",
                file=sys.stderr,
            )
            return False

    after = get_installed_version()
    changed = after != before
    if changed:
        print(f"yt-dlp upgraded: {before} -> {after}")
    else:
        print(f"yt-dlp current: {after}")
    return changed


def _restart_bot() -> None:
    """Best-effort restart of the bot service so the new build is loaded."""
    try:
        subprocess.run(["systemctl", "restart", BOT_SERVICE], timeout=60)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not restart {BOT_SERVICE}: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Keep yt-dlp current.")
    parser.add_argument(
        "--restart",
        action="store_true",
        help=f"Restart {BOT_SERVICE} after a successful upgrade.",
    )
    parser.add_argument(
        "--min",
        dest="minimum",
        default=MIN_YT_DLP,
        help="Minimum known-good version (default: %s)." % MIN_YT_DLP,
    )
    args = parser.parse_args(argv)

    changed = ensure_yt_dlp(args.minimum)
    if changed and args.restart:
        _restart_bot()
    return 0


if __name__ == "__main__":
    sys.exit(main())
