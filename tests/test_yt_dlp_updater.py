"""
Tests for the yt-dlp self-healing updater (core.yt_dlp_updater).

These tests never touch the real pip, systemctl or network: subprocess.run
and the version lookup are stubbed so we can assert on the decision logic
(upgraded / already latest / pip failed), on the exit codes systemd and
auto_deploy.sh rely on, and on the privilege handling in the restart path.
"""

import subprocess

import pytest

from core import yt_dlp_updater


@pytest.fixture
def fake_versions(monkeypatch):
    """Drive get_installed_version(): first call -> before, second -> after."""

    def _install(before, after):
        seq = iter([before, after])
        monkeypatch.setattr(
            yt_dlp_updater, "get_installed_version", lambda: next(seq, after)
        )

    return _install


# --- get_installed_version ---

def test_get_installed_version_returns_none_when_missing(monkeypatch):
    def boom(_name):
        raise yt_dlp_updater.importlib.metadata.PackageNotFoundError("yt-dlp")

    monkeypatch.setattr(yt_dlp_updater.importlib.metadata, "version", boom)
    assert yt_dlp_updater.get_installed_version() is None


# --- _run_pip_upgrade ---

def test_pip_upgrade_installs_latest_not_a_pinned_floor(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(yt_dlp_updater.subprocess, "run", fake_run)
    assert yt_dlp_updater._run_pip_upgrade() is True
    assert seen["cmd"][1:] == ["-m", "pip", "install", "--upgrade", "yt-dlp"]
    # No version specifier anywhere: we always track the newest release.
    assert not any("==" in part or ">=" in part for part in seen["cmd"])
    assert seen["timeout"] == yt_dlp_updater.PIP_TIMEOUT


def test_pip_upgrade_reports_failure_on_nonzero_exit(monkeypatch, capsys):
    monkeypatch.setattr(
        yt_dlp_updater.subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "network unreachable"),
    )
    assert yt_dlp_updater._run_pip_upgrade() is False
    # The reason must reach stderr, never be swallowed.
    assert "network unreachable" in capsys.readouterr().err


def test_pip_upgrade_reports_failure_on_timeout(monkeypatch, capsys):
    def timeout(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, 300)

    monkeypatch.setattr(yt_dlp_updater.subprocess, "run", timeout)
    assert yt_dlp_updater._run_pip_upgrade() is False
    assert "upgrade failed" in capsys.readouterr().err


# --- ensure_yt_dlp ---

def test_ensure_reports_change_when_version_bumps(monkeypatch, fake_versions):
    fake_versions("2024.11.18", "2026.8.19")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: True)
    result = yt_dlp_updater.ensure_yt_dlp()
    assert (result.ok, result.changed) == (True, True)
    assert (result.before, result.after) == ("2024.11.18", "2026.8.19")


def test_ensure_reports_success_without_change_when_already_latest(
    monkeypatch, fake_versions
):
    fake_versions("2026.8.19", "2026.8.19")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: True)
    result = yt_dlp_updater.ensure_yt_dlp()
    assert (result.ok, result.changed) == (True, False)


def test_ensure_keeps_working_version_when_pip_fails(
    monkeypatch, fake_versions, capsys
):
    fake_versions("2024.11.18", "2024.11.18")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: False)
    result = yt_dlp_updater.ensure_yt_dlp()
    assert (result.ok, result.changed) == (False, False)
    assert "Keeping working yt-dlp" in capsys.readouterr().err


def test_ensure_installs_even_when_a_version_is_already_present(
    monkeypatch, fake_versions
):
    # Regression guard: the old code gated pip behind a version floor, so a
    # bot sitting above the floor never picked up newer releases.
    calls = []
    fake_versions("2026.8.19", "2026.9.30")
    monkeypatch.setattr(
        yt_dlp_updater, "_run_pip_upgrade", lambda **k: calls.append(True) or True
    )
    result = yt_dlp_updater.ensure_yt_dlp()
    assert calls == [True]
    assert result.changed is True


# --- _restart_bot ---

def test_restart_uses_sudo_when_not_root(monkeypatch):
    monkeypatch.setattr(yt_dlp_updater.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(yt_dlp_updater.shutil, "which", lambda _: "/usr/bin/systemctl")
    seen = {}

    def fake_run(cmd, **k):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(yt_dlp_updater.subprocess, "run", fake_run)
    assert yt_dlp_updater._restart_bot() is True
    # -n so a missing sudoers rule fails fast instead of hanging on polkit.
    assert seen["cmd"][:2] == ["sudo", "-n"]
    assert seen["cmd"][-2:] == ["restart", "tg-media-bot.service"]


def test_restart_skips_sudo_when_root(monkeypatch):
    monkeypatch.setattr(yt_dlp_updater.os, "geteuid", lambda: 0)
    monkeypatch.setattr(yt_dlp_updater.shutil, "which", lambda _: "/usr/bin/systemctl")
    seen = {}

    def fake_run(cmd, **k):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(yt_dlp_updater.subprocess, "run", fake_run)
    assert yt_dlp_updater._restart_bot() is True
    assert seen["cmd"][0] == "/usr/bin/systemctl"
    assert "sudo" not in seen["cmd"]


def test_restart_reports_failure_when_denied(monkeypatch, capsys):
    monkeypatch.setattr(yt_dlp_updater.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        yt_dlp_updater.subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "a password is required"),
    )
    assert yt_dlp_updater._restart_bot() is False
    assert "a password is required" in capsys.readouterr().err


def test_restart_does_not_hang_on_timeout(monkeypatch, capsys):
    def timeout(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr(yt_dlp_updater.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(yt_dlp_updater.subprocess, "run", timeout)
    assert yt_dlp_updater._restart_bot() is False
    assert "Could not restart" in capsys.readouterr().err


# --- main() exit codes (auto_deploy.sh and systemd read these) ---

def test_main_returns_zero_and_restarts_on_change(monkeypatch, fake_versions):
    fake_versions("2024.11.18", "2026.8.19")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: True)
    restarted = []
    monkeypatch.setattr(
        yt_dlp_updater, "_restart_bot", lambda: restarted.append(True) or True
    )
    assert yt_dlp_updater.main(["--restart"]) == 0
    assert restarted == [True]


def test_main_does_not_restart_when_already_latest(monkeypatch, fake_versions):
    fake_versions("2026.8.19", "2026.8.19")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: True)
    restarted = []
    monkeypatch.setattr(
        yt_dlp_updater, "_restart_bot", lambda: restarted.append(True) or True
    )
    assert yt_dlp_updater.main(["--restart"]) == 0
    assert restarted == []


def test_main_returns_nonzero_when_pip_fails(monkeypatch, fake_versions):
    # This is what makes auto_deploy.sh's `|| echo Warning` and systemd's
    # failed-unit state actually fire.
    fake_versions("2024.11.18", "2024.11.18")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: False)
    restarted = []
    monkeypatch.setattr(
        yt_dlp_updater, "_restart_bot", lambda: restarted.append(True) or True
    )
    assert yt_dlp_updater.main(["--restart"]) == 1
    assert restarted == []


def test_main_returns_nonzero_when_restart_fails(monkeypatch, fake_versions):
    # Upgraded on disk but the running bot still holds the old build: that is
    # a failure, not a success.
    fake_versions("2024.11.18", "2026.8.19")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: True)
    monkeypatch.setattr(yt_dlp_updater, "_restart_bot", lambda: False)
    assert yt_dlp_updater.main(["--restart"]) == 1


def test_main_without_restart_flag_never_touches_the_service(
    monkeypatch, fake_versions
):
    fake_versions("2024.11.18", "2026.8.19")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: True)
    restarted = []
    monkeypatch.setattr(
        yt_dlp_updater, "_restart_bot", lambda: restarted.append(True) or True
    )
    assert yt_dlp_updater.main([]) == 0
    assert restarted == []


def test_module_exposes_no_version_floor():
    # The floor was removed on purpose: it went stale faster than anyone
    # remembered to bump it.
    assert not hasattr(yt_dlp_updater, "MIN_YT_DLP")
    assert not hasattr(yt_dlp_updater, "is_below_minimum")
