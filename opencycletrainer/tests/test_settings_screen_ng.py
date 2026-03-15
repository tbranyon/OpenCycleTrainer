"""Tests for NiceGUI settings screen logic (Phase 7)."""
from __future__ import annotations

import pytest

from opencycletrainer.storage.settings import AppSettings
from opencycletrainer.ui.settings_screen_ng import (
    SettingsController,
    DISPLAY_UNITS_OPTIONS,
    DEFAULT_BEHAVIOR_OPTIONS,
)
from opencycletrainer.ui.tile_config import MAX_CONFIGURABLE_TILES, TILE_OPTIONS


# ---------------------------------------------------------------------------
# SettingsController
# ---------------------------------------------------------------------------


class TestSettingsController:
    """Tests for SettingsController — logic layer without NiceGUI."""

    def _make_controller(self, **kwargs) -> SettingsController:
        saved: list[AppSettings] = []
        settings = AppSettings(**kwargs)
        return SettingsController(settings, on_save=saved.append), saved

    def test_initial_ftp(self) -> None:
        ctrl, _ = self._make_controller(ftp=300)
        assert ctrl.ftp == 300

    def test_initial_lead_time(self) -> None:
        ctrl, _ = self._make_controller(lead_time=5)
        assert ctrl.lead_time == 5

    def test_initial_power_window(self) -> None:
        ctrl, _ = self._make_controller(windowed_power_window_seconds=5)
        assert ctrl.windowed_power_window_seconds == 5

    def test_initial_opentrueup(self) -> None:
        ctrl, _ = self._make_controller(opentrueup_enabled=True)
        assert ctrl.opentrueup_enabled is True

    def test_initial_tile_selections(self) -> None:
        ctrl, _ = self._make_controller(tile_selections=["cadence_rpm", "heart_rate"])
        assert ctrl.selected_tiles == ["cadence_rpm", "heart_rate"]

    def test_toggle_tile_on(self) -> None:
        ctrl, _ = self._make_controller(tile_selections=[])
        ctrl.toggle_tile("cadence_rpm", True)
        assert "cadence_rpm" in ctrl.selected_tiles

    def test_toggle_tile_off(self) -> None:
        ctrl, _ = self._make_controller(tile_selections=["cadence_rpm"])
        ctrl.toggle_tile("cadence_rpm", False)
        assert "cadence_rpm" not in ctrl.selected_tiles

    def test_toggle_tile_enforces_max_8(self) -> None:
        # Fill up to max
        all_keys = [k for k, _ in TILE_OPTIONS]
        initial = all_keys[:MAX_CONFIGURABLE_TILES]
        ctrl, _ = self._make_controller(tile_selections=initial)
        extra_key = all_keys[MAX_CONFIGURABLE_TILES]
        # Attempt to add one more
        result = ctrl.toggle_tile(extra_key, True)
        assert result is False  # rejected
        assert extra_key not in ctrl.selected_tiles
        assert len(ctrl.selected_tiles) == MAX_CONFIGURABLE_TILES

    def test_toggle_tile_within_max_returns_true(self) -> None:
        ctrl, _ = self._make_controller(tile_selections=[])
        result = ctrl.toggle_tile("cadence_rpm", True)
        assert result is True

    def test_toggle_same_tile_twice_noop(self) -> None:
        ctrl, _ = self._make_controller(tile_selections=["cadence_rpm"])
        ctrl.toggle_tile("cadence_rpm", True)  # already on
        assert ctrl.selected_tiles.count("cadence_rpm") == 1

    def test_save_calls_on_save(self) -> None:
        ctrl, saved = self._make_controller(ftp=250)
        ctrl.ftp = 300
        ctrl.save()
        assert len(saved) == 1
        assert saved[0].ftp == 300

    def test_save_persists_tile_selections(self) -> None:
        ctrl, saved = self._make_controller(tile_selections=[])
        ctrl.toggle_tile("cadence_rpm", True)
        ctrl.save()
        assert "cadence_rpm" in saved[0].tile_selections

    def test_save_persists_all_general_fields(self) -> None:
        ctrl, saved = self._make_controller()
        ctrl.ftp = 280
        ctrl.lead_time = 3
        ctrl.windowed_power_window_seconds = 5
        ctrl.opentrueup_enabled = True
        ctrl.display_units = "imperial"
        ctrl.default_workout_behavior = "free_ride_mode"
        ctrl.strava_auto_sync_enabled = True
        ctrl.save()
        s = saved[0]
        assert s.ftp == 280
        assert s.lead_time == 3
        assert s.windowed_power_window_seconds == 5
        assert s.opentrueup_enabled is True
        assert s.display_units == "imperial"
        assert s.default_workout_behavior == "free_ride_mode"
        assert s.strava_auto_sync_enabled is True

    def test_tile_count(self) -> None:
        ctrl, _ = self._make_controller(tile_selections=["cadence_rpm", "heart_rate"])
        assert ctrl.tile_count == 2

    def test_tile_count_label(self) -> None:
        ctrl, _ = self._make_controller(tile_selections=["cadence_rpm"])
        assert "1" in ctrl.tile_count_label
        assert "8" in ctrl.tile_count_label

    def test_is_tile_selected(self) -> None:
        ctrl, _ = self._make_controller(tile_selections=["cadence_rpm"])
        assert ctrl.is_tile_selected("cadence_rpm") is True
        assert ctrl.is_tile_selected("heart_rate") is False


# ---------------------------------------------------------------------------
# DISPLAY_UNITS_OPTIONS / DEFAULT_BEHAVIOR_OPTIONS
# ---------------------------------------------------------------------------


def test_display_units_options_contain_metric_and_imperial() -> None:
    keys = [k for k, _ in DISPLAY_UNITS_OPTIONS]
    assert "metric" in keys
    assert "imperial" in keys


def test_default_behavior_options_contain_all_modes() -> None:
    keys = [k for k, _ in DEFAULT_BEHAVIOR_OPTIONS]
    assert "workout_mode" in keys
    assert "free_ride_mode" in keys
    assert "kj_mode" in keys
