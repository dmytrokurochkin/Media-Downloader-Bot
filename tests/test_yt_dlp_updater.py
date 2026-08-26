"""
Tests for the yt-dlp self-healing updater (core.yt_dlp_updater).

These tests never touch the real pip / network: they stub ``_run_pip_upgrade``
and the version lookup to verify the decision logic (below floor, already
current, keep-on-failure) and that ``main`` restarts the bot only on change.
"""

import sys

import pytest

from core import yt_dlp_updater


# --- version comparison ---

def test_version_tuple_parses_date_versions():
    assert yt_dlp_updater._version_tuple("2026.8.19") == (2026, 8, 19)
    assert yt_dlp_updater._version_tuple("2024.11.18") == (2024, 11, 18)


def test_version_tuple_handles_garbage_as_zero():
    assert yt_dlp_updater._version_tuple("not-a-version") == (0,)
    assert yt_dlp_updater._version_tuple("") == (0,)


def test_is_below_minimum_true_when_under_floor():
    assert yt_dlp_updater.is_below_minimum("2024.11.18", "2026.8.19") is True


def test_is_below_minimum_false_when_equal_or_above():
    assert yt_dlp_updater.is_below_minimum("2026.8.19", "2026.8.19") is False
    assert yt_dlp_updater.is_below_minimum("2026.9.1", "2026.8.19") is False


def test_is_below_minimum_true_when_missing():
    assert yt_dlp_updater.is_below_minimum(None) is True


# --- ensure_yt_dlp behaviour ---

def test_ensure_runs_upgrade_and_reports_no_change(monkeypatch):
    # Simulate: we're already at the latest, so the post-upgrade version is
    # the same as the pre one -> "changed" must be False.
    monkeypatch.setattr(yt_dlp_updater, "get_installed_version", lambda: "2026.8.19")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: True)
    changed = yt_dlp_updater.ensure_yt_dlp("2026.8.19")
    assert changed is False


def test_ensure_reports_change_when_version_bumps(monkeypatch):
    # First read (before) returns the old version; after the upgrade we
    # report the new one.
    calls = {"n": 0}

    def fake_version():
        calls["n"] += 1
        return "2024.11.18" if calls["n"] == 1 else "2026.8.19"

    monkeypatch.setattr(yt_dlp_updater, "get_installed_version", fake_version)
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: True)
    changed = yt_dlp_updater.ensure_yt_dlp("2026.8.19")
    assert changed is True


def test_ensure_keeps_working_version_when_pip_fails(monkeypatch):
    # Below floor, pip fails -> must NOT raise and must NOT claim a change.
    monkeypatch.setattr(yt_dlp_updater, "get_installed_version", lambda: "2024.11.18")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: False)
    changed = yt_dlp_updater.ensure_yt_dlp("2026.8.19")
    assert changed is False


def test_ensure_below_floor_triggers_upgrade(monkeypatch):
    # Below floor and pip succeeds -> the post version differs -> change.
    calls = {"n": 0}

    def fake_version():
        calls["n"] += 1
        return "2024.11.18" if calls["n"] == 1 else "2026.8.19"

    monkeypatch.setattr(yt_dlp_updater, "get_installed_version", fake_version)
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: True)
    changed = yt_dlp_updater.ensure_yt_dlp("2026.8.19")
    assert changed is True


# --- main() wiring ---

def test_main_restarts_bot_only_on_change(monkeypatch, capsys):
    calls = {"n": 0}

    def fake_version():
        calls["n"] += 1
        return "2024.11.18" if calls["n"] == 1 else "2026.8.19"

    monkeypatch.setattr(yt_dlp_updater, "get_installed_version", fake_version)
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: True)
    restarted = []
    monkeypatch.setattr(yt_dlp_updater, "_restart_bot", lambda: restarted.append(True))

    rc = yt_dlp_updater.main(["--restart"])
    assert rc == 0
    assert restarted == [True]


def test_main_no_restart_when_already_current(monkeypatch, capsys):
    # Already at the latest: before == after -> no change -> no restart.
    monkeypatch.setattr(yt_dlp_updater, "get_installed_version", lambda: "2026.8.19")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: True)
    restarted = []
    monkeypatch.setattr(yt_dlp_updater, "_restart_bot", lambda: restarted.append(True))

    rc = yt_dlp_updater.main(["--restart"])
    assert rc == 0
    assert restarted == []


def test_main_no_restart_when_pip_fails(monkeypatch, capsys):
    # Below floor but pip fails -> keep working version, do NOT restart.
    monkeypatch.setattr(yt_dlp_updater, "get_installed_version", lambda: "2024.11.18")
    monkeypatch.setattr(yt_dlp_updater, "_run_pip_upgrade", lambda **k: False)
    restarted = []
    monkeypatch.setattr(yt_dlp_updater, "_restart_bot", lambda: restarted.append(True))

    rc = yt_dlp_updater.main(["--restart"])
    assert rc == 0
    assert restarted == []


def test_module_is_importable_and_has_floor():
    # Sanity: the floor is a valid date version and the module exposes the
    # expected API surface.
    assert hasattr(yt_dlp_updater, "MIN_YT_DLP")
    assert yt_dlp_updater._version_tuple(yt_dlp_updater.MIN_YT_DLP) != (0,)
    assert callable(yt_dlp_updater.ensure_yt_dlp)
