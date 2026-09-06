"""
Self-healing yt-dlp updater.

Why this exists
---------------
yt-dlp breaks whenever YouTube changes its backend, and old builds silently
stop working (extraction fails with "Requested format is not available" /
"Sign in to confirm your age" / generic Extractor errors).  There is no
useful "known-good floor" to pin against: a release that works today is
stale within weeks, so this module always installs the *latest* release
instead of comparing against a constant somebody has to remember to bump.

Integration points (both idempotent and safe):
  * ``auto_deploy.sh``      -> upgrades the venv at deploy time, before the
    bot service is (re)started, so a fresh process loads the newest build.
  * a weekly systemd timer  -> keeps the venv current while the bot stays up
    for months between restarts, and restarts the bot afterwards so the
    running process actually picks the new build up.  Upgrading on disk does
    nothing for an already-imported module, so the restart is the point.

Safety model: if pip fails (no network, locked package, ...) we KEEP the
currently working version and exit NON-ZERO, so the failure is visible in
the deploy log and in ``systemctl list-units --failed`` instead of rotting
silently.  We never downgrade and we never install anything else.
"""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
import sys
from typing import NamedTuple

PACKAGE = "yt-dlp"
BOT_SERVICE = "tg-media-bot.service"

PIP_TIMEOUT = 300
RESTART_TIMEOUT = 60


class UpdateResult(NamedTuple):
    """Outcome of one upgrade attempt.

    ``ok`` and ``changed`` are deliberately separate: "already on the latest
    release" is a success with no change, while "pip failed" is a failure
    that also produces no change.  Collapsing them into one bool is what
    made the previous version unable to report failures at all.
    """

    ok: bool
    changed: bool
    before: str | None
    after: str | None


def get_installed_version() -> str | None:
    """Return the installed yt-dlp version, or None if it is missing."""
    try:
        return importlib.metadata.version(PACKAGE)
    except Exception:
        return None


def _run_pip_upgrade(timeout: int = PIP_TIMEOUT) -> bool:
    """Upgrade yt-dlp to the latest release in the interpreter running this.

    Returns True on success.  On failure the reason is printed to stderr --
    a silent False here is exactly the bit-rot this module exists to stop.
    """
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - keep the working version on any failure
        print(f"yt-dlp upgrade failed: {exc}", file=sys.stderr)
        return False
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        print(f"yt-dlp upgrade failed (pip exit {proc.returncode}): {detail}", file=sys.stderr)
        return False
    return True


def ensure_yt_dlp() -> UpdateResult:
    """Install the latest yt-dlp, keeping the working build if pip fails."""
    before = get_installed_version()
    ok = _run_pip_upgrade()
    after = get_installed_version()
    changed = after != before

    if not ok:
        print(f"Keeping working yt-dlp {before!r} (upgrade failed).", file=sys.stderr)
    elif changed:
        print(f"yt-dlp upgraded: {before} -> {after}")
    else:
        print(f"yt-dlp already latest: {after}")

    return UpdateResult(ok=ok, changed=changed, before=before, after=after)


def _restart_bot(service: str = BOT_SERVICE) -> bool:
    """Restart the bot so the freshly installed build is loaded.

    The weekly timer runs as the bot's own unprivileged user, which cannot
    restart a system unit on its own: a bare ``systemctl restart`` there
    blocks on a polkit prompt (interactively) or is denied (under systemd).
    ``sudo -n`` fails fast and loudly instead of hanging; auto_deploy.sh
    installs the matching /etc/sudoers.d drop-in.
    """
    systemctl = shutil.which("systemctl") or "/usr/bin/systemctl"
    cmd = [systemctl, "restart", service]
    if os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=RESTART_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not restart {service}: {exc}", file=sys.stderr)
        return False
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        print(f"Could not restart {service}: {detail}", file=sys.stderr)
        return False
    print(f"Restarted {service} to load the new build.")
    return True


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Install the latest yt-dlp.")
    parser.add_argument(
        "--restart",
        action="store_true",
        help=f"Restart {BOT_SERVICE} after the installed version changes.",
    )
    args = parser.parse_args(argv)

    result = ensure_yt_dlp()
    if not result.ok:
        return 1
    if result.changed and args.restart and not _restart_bot():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
