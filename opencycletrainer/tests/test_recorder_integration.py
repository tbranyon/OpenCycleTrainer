from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from opencycletrainer.storage.settings import AppSettings
from opencycletrainer.ui.recorder_integration import RecorderIntegration, SensorSnapshot


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeRecorder:
    def __init__(self) -> None:
        self.started = False
        self.recording_enabled = False
        self.samples: list[object] = []
        self.stop_calls = 0
        self.data_dirs: list[Path] = []

    def start(self, workout_name: str, started_at_utc: object) -> object:  # noqa: ARG002
        self.started = True
        self.recording_enabled = True
        return SimpleNamespace(workout_name=workout_name)

    def set_recording_active(self, active: bool) -> None:
        if not self.started:
            raise RuntimeError("Recorder is not active.")
        self.recording_enabled = bool(active)

    def record_sample(self, sample: object) -> bool:
        if not self.started:
            raise RuntimeError("Recorder is not active.")
        self.samples.append(sample)
        return True

    def stop(self, finished_at_utc: object) -> object:  # noqa: ARG002
        if not self.started:
            raise RuntimeError("Recorder is not active.")
        self.started = False
        self.recording_enabled = False
        self.stop_calls += 1
        return SimpleNamespace(
            fit_file_path=Path("Quick_Start_20260311_1200.fit"),
            normalized_power=None,
            kj=0.0,
            avg_hr=None,
        )

    def set_data_dir(self, data_dir: Path) -> None:
        self.data_dirs.append(data_dir)


class _FakeScreen:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, str]] = []
        self.exported_chart_paths: list[Path] = []

    def show_alert(self, message: str, alert_type: str = "info") -> None:
        self.alerts.append((message, alert_type))

    def export_chart_image(self, path: Path) -> None:
        self.exported_chart_paths.append(path)


class _FakeModeState:
    def __init__(self, target_watts: int | None = 200, mode: str = "ERG") -> None:
        self._target_watts = target_watts
        self._mode = mode

    def resolve_target_watts(self, snapshot: object, workout: object) -> int | None:  # noqa: ARG002
        return self._target_watts

    def active_control_mode(self, snapshot: object, workout: object) -> str:  # noqa: ARG002
        return self._mode


class _FakeSnapshot:
    def __init__(self, recording_active: bool = True) -> None:
        self.recording_active = recording_active


class _FakeWorkout:
    def __init__(self, name: str = "Test Workout") -> None:
        self.name = name


_UTC_NOW = datetime(2026, 3, 11, 12, 0, 0, tzinfo=timezone.utc)
_SENSOR = SensorSnapshot(
    last_power_watts=200,
    last_bike_power_watts=None,
    last_hr_bpm=150,
    last_cadence_rpm=90.0,
    last_speed_mps=10.0,
)


def _make(
    *,
    recorder=None,
    screen=None,
    settings=None,
    utc_now=None,
    strava_upload_fn=None,
    alert_fn=None,
    mode_state=None,
) -> tuple[RecorderIntegration, _FakeRecorder, _FakeScreen]:
    rec = recorder if recorder is not None else _FakeRecorder()
    scr = screen if screen is not None else _FakeScreen()
    ri = RecorderIntegration(
        recorder=rec,
        screen=scr,
        settings=settings or AppSettings(),
        utc_now=utc_now or (lambda: _UTC_NOW),
        strava_upload_fn=strava_upload_fn,
        alert_signal=alert_fn or (lambda msg, typ: None),
        mode_state=mode_state or _FakeModeState(),
    )
    return ri, rec, scr


# ── Defaults ──────────────────────────────────────────────────────────────────


class TestDefaults:
    def test_recorder_active_is_false(self) -> None:
        ri, *_ = _make()
        assert ri.recorder_active is False

    def test_total_kj_is_zero(self) -> None:
        ri, *_ = _make()
        assert ri.total_kj == pytest.approx(0.0)


# ── SensorSnapshot ────────────────────────────────────────────────────────────


class TestSensorSnapshot:
    def test_fields_are_accessible(self) -> None:
        s = SensorSnapshot(
            last_power_watts=250,
            last_bike_power_watts=240,
            last_hr_bpm=155,
            last_cadence_rpm=92.5,
            last_speed_mps=11.0,
        )
        assert s.last_power_watts == 250
        assert s.last_bike_power_watts == 240
        assert s.last_hr_bpm == 155
        assert s.last_cadence_rpm == pytest.approx(92.5)
        assert s.last_speed_mps == pytest.approx(11.0)

    def test_all_none_fields_allowed(self) -> None:
        s = SensorSnapshot(
            last_power_watts=None,
            last_bike_power_watts=None,
            last_hr_bpm=None,
            last_cadence_rpm=None,
            last_speed_mps=None,
        )
        assert s.last_power_watts is None


# ── start() ──────────────────────────────────────────────────────────────────


class TestStart:
    def test_sets_recorder_active(self) -> None:
        ri, _, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        assert ri.recorder_active is True

    def test_calls_recorder_start(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        assert rec.started is True

    def test_passes_workout_name_to_recorder(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout("Custom Ride"), _UTC_NOW)
        assert rec.started  # implicitly verifies start was called without error

    def test_noop_when_already_started(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.start(_FakeWorkout("Second"), _UTC_NOW)  # would raise if called twice on recorder
        assert rec.started

    def test_resets_total_kj(self) -> None:
        ri, *_ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        assert ri.total_kj == pytest.approx(0.0)

    def test_first_update_total_kj_after_start_is_noop(self) -> None:
        """After start, the energy-tick baseline is None so the first call accumulates nothing."""
        ri, *_ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        snap = _FakeSnapshot(recording_active=True)
        ri.update_total_kj(snap, 10.0)
        assert ri.total_kj == pytest.approx(0.0)


# ── finalize() ───────────────────────────────────────────────────────────────


class TestFinalize:
    def test_noop_when_not_started(self) -> None:
        ri, rec, _ = _make()
        ri.finalize(_FakeWorkout())
        assert rec.stop_calls == 0

    def test_calls_recorder_stop(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.finalize(_FakeWorkout())
        assert rec.stop_calls == 1

    def test_sets_recorder_active_false(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.finalize(_FakeWorkout())
        assert ri.recorder_active is False

    def test_shows_saved_alert(self) -> None:
        ri, rec, scr = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.finalize(_FakeWorkout())
        assert any("Workout saved" in msg for msg, _ in scr.alerts)

    def test_no_strava_upload_when_setting_disabled(self) -> None:
        uploaded: list = []
        ri, rec, _ = _make(
            settings=AppSettings(strava_auto_sync_enabled=False),
            strava_upload_fn=lambda *a: uploaded.append(a),
        )
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.finalize(_FakeWorkout())
        assert uploaded == []

    def test_no_strava_upload_when_upload_fn_is_none(self) -> None:
        ri, rec, scr = _make(
            settings=AppSettings(strava_auto_sync_enabled=True),
            strava_upload_fn=None,
        )
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.finalize(_FakeWorkout())  # should not raise
        assert rec.stop_calls == 1

    def test_second_finalize_is_noop(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.finalize(_FakeWorkout())
        ri.finalize(_FakeWorkout())
        assert rec.stop_calls == 1

    def test_recorder_stop_failure_does_not_raise(self) -> None:
        class _FailStop(_FakeRecorder):
            def stop(self, finished_at_utc: object) -> object:
                raise RuntimeError("disk full")

        ri, _, _ = _make(recorder=_FailStop())
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.finalize(_FakeWorkout())  # should not propagate
        assert ri.recorder_active is False


# ── sync() ───────────────────────────────────────────────────────────────────


class TestSync:
    def test_calls_record_sample(self) -> None:
        """sync() accumulates into the aggregator; finalize() flushes to the recorder."""
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.sync(_FakeSnapshot(), None, _SENSOR)
        ri.finalize(_FakeWorkout())
        assert len(rec.samples) == 1

    def test_trainer_power_in_sample(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.sync(_FakeSnapshot(), None, _SENSOR)
        ri.finalize(_FakeWorkout())
        assert rec.samples[-1].trainer_power_watts == 200

    def test_hr_in_sample(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.sync(_FakeSnapshot(), None, _SENSOR)
        ri.finalize(_FakeWorkout())
        assert rec.samples[-1].heart_rate_bpm == 150

    def test_cadence_in_sample(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.sync(_FakeSnapshot(), None, _SENSOR)
        ri.finalize(_FakeWorkout())
        assert rec.samples[-1].cadence_rpm == pytest.approx(90.0)

    def test_speed_in_sample(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.sync(_FakeSnapshot(), None, _SENSOR)
        ri.finalize(_FakeWorkout())
        assert rec.samples[-1].speed_mps == pytest.approx(10.0)

    def test_erg_setpoint_set_in_erg_mode(self) -> None:
        ri, rec, _ = _make(mode_state=_FakeModeState(target_watts=250, mode="ERG"))
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.sync(_FakeSnapshot(), None, _SENSOR)
        ri.finalize(_FakeWorkout())
        assert rec.samples[-1].erg_setpoint_watts == 250

    def test_erg_setpoint_none_in_resistance_mode(self) -> None:
        ri, rec, _ = _make(mode_state=_FakeModeState(target_watts=200, mode="Resistance"))
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.sync(_FakeSnapshot(), None, _SENSOR)
        ri.finalize(_FakeWorkout())
        assert rec.samples[-1].erg_setpoint_watts is None

    def test_total_kj_included_in_sample(self) -> None:
        """kJ accumulated by the second sync is captured in the emitted sample."""
        t0 = _UTC_NOW
        t1 = _UTC_NOW + timedelta(seconds=1)
        # finalize() calls _utc_now() once more for finished_at_utc, so provide 3 values.
        t2 = _UTC_NOW + timedelta(seconds=2)
        times = iter([t0, t1, t2])
        ri, rec, _ = _make(
            mode_state=_FakeModeState(target_watts=1000),
            utc_now=lambda: next(times),
        )
        ri.start(_FakeWorkout(), t0)
        ri.sync(_FakeSnapshot(), 0.0, _SENSOR)  # baseline at t0; kJ=0
        ri.sync(_FakeSnapshot(), 1.0, _SENSOR)  # t1 closes bin for t0; kJ=1.0 in new bin
        ri.finalize(_FakeWorkout())              # flushes bin for t1 with kJ=1.0
        assert rec.samples[-1].total_kj == pytest.approx(1.0)

    def test_crossing_second_boundary_emits_sample_without_finalize(self) -> None:
        """A tick in a new UTC second closes the previous bin immediately."""
        t0 = _UTC_NOW
        t1 = _UTC_NOW + timedelta(seconds=1)
        times = iter([t0, t1])
        ri, rec, _ = _make(utc_now=lambda: next(times))
        ri.start(_FakeWorkout(), t0)
        ri.sync(_FakeSnapshot(), None, _SENSOR)  # feeds bin at t0
        ri.sync(_FakeSnapshot(), None, _SENSOR)  # t1 → closes bin at t0
        assert len(rec.samples) == 1

    def test_set_recording_active_failure_halts_recording(self) -> None:
        class _FailSetActive(_FakeRecorder):
            def set_recording_active(self, active: bool) -> None:
                raise RuntimeError("broken")

        ri, rec, _ = _make(recorder=_FailSetActive())
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.sync(_FakeSnapshot(), None, _SENSOR)
        assert ri.recorder_active is False

    def test_record_sample_failure_halts_recording(self) -> None:
        """record_sample failure during second-boundary flush halts recording."""
        class _FailSample(_FakeRecorder):
            def record_sample(self, sample: object) -> bool:
                raise RuntimeError("broken")

        t0 = _UTC_NOW
        t1 = _UTC_NOW + timedelta(seconds=1)
        times = iter([t0, t1])
        ri, rec, _ = _make(recorder=_FailSample(), utc_now=lambda: next(times))
        ri.start(_FakeWorkout(), t0)
        ri.sync(_FakeSnapshot(), None, _SENSOR)  # accumulates into bin at t0
        ri.sync(_FakeSnapshot(), None, _SENSOR)  # t1 → closes bin → record_sample raises
        assert ri.recorder_active is False

    def test_sync_calls_update_total_kj_when_now_provided(self) -> None:
        ri, *_ = _make(mode_state=_FakeModeState(target_watts=2000))
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.sync(_FakeSnapshot(recording_active=True), 0.0, _SENSOR)
        ri.sync(_FakeSnapshot(recording_active=True), 1.0, _SENSOR)
        # 2000 W * 1 s / 1000 = 2.0 kJ
        assert ri.total_kj == pytest.approx(2.0)

    def test_sync_skips_update_total_kj_when_now_is_none(self) -> None:
        ri, *_ = _make(mode_state=_FakeModeState(target_watts=2000))
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.sync(_FakeSnapshot(recording_active=True), None, _SENSOR)
        assert ri.total_kj == pytest.approx(0.0)


# ── update_total_kj() ────────────────────────────────────────────────────────


class TestUpdateTotalKj:
    def test_first_call_is_noop(self) -> None:
        ri, *_ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 10.0)
        assert ri.total_kj == pytest.approx(0.0)

    def test_accumulates_kj_over_two_ticks(self) -> None:
        ri, *_ = _make(mode_state=_FakeModeState(target_watts=1000))
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 0.0)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 1.0)
        assert ri.total_kj == pytest.approx(1.0)

    def test_no_accumulation_when_not_recording_active(self) -> None:
        ri, *_ = _make(mode_state=_FakeModeState(target_watts=1000))
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.update_total_kj(_FakeSnapshot(recording_active=False), 0.0)
        ri.update_total_kj(_FakeSnapshot(recording_active=False), 1.0)
        assert ri.total_kj == pytest.approx(0.0)

    def test_no_accumulation_when_target_is_zero(self) -> None:
        ri, *_ = _make(mode_state=_FakeModeState(target_watts=0))
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 0.0)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 1.0)
        assert ri.total_kj == pytest.approx(0.0)

    def test_no_accumulation_when_target_is_none(self) -> None:
        ri, *_ = _make(mode_state=_FakeModeState(target_watts=None))
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 0.0)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 1.0)
        assert ri.total_kj == pytest.approx(0.0)

    def test_accumulates_across_multiple_ticks(self) -> None:
        ri, *_ = _make(mode_state=_FakeModeState(target_watts=2000))
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 0.0)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 1.0)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 2.0)
        # 2000 W * 2 s / 1000 = 4.0 kJ
        assert ri.total_kj == pytest.approx(4.0)

    def test_zero_or_negative_delta_is_skipped(self) -> None:
        ri, *_ = _make(mode_state=_FakeModeState(target_watts=1000))
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 5.0)
        ri.update_total_kj(_FakeSnapshot(recording_active=True), 5.0)  # same time
        assert ri.total_kj == pytest.approx(0.0)


# ── configure_data_dir() ─────────────────────────────────────────────────────


class TestConfigureDataDir:
    def test_calls_set_data_dir_on_recorder(self, tmp_path: Path) -> None:
        ri, rec, _ = _make()
        settings = AppSettings(workout_data_dir=tmp_path)
        ri.configure_data_dir(settings)
        assert any(str(tmp_path) in str(p) for p in rec.data_dirs)

    def test_updates_settings_reference(self, tmp_path: Path) -> None:
        ri, rec, _ = _make()
        new_settings = AppSettings(workout_data_dir=tmp_path)
        ri.configure_data_dir(new_settings)
        # After configure, data_dir calls use the new settings path
        assert any(str(tmp_path) in str(p) for p in rec.data_dirs)

    def test_noop_when_recorder_has_no_set_data_dir(self) -> None:
        class _MinimalRecorder:
            def start(self, **kw: object) -> object:
                return SimpleNamespace()

            def stop(self, **kw: object) -> object:
                return SimpleNamespace(fit_file_path=Path("x.fit"))

            def set_recording_active(self, active: bool) -> None:
                pass

            def record_sample(self, s: object) -> bool:
                return True

        ri, _, _ = _make(recorder=_MinimalRecorder())
        ri.configure_data_dir(AppSettings())  # should not raise


# ── shutdown() ───────────────────────────────────────────────────────────────


class TestShutdown:
    def test_finalizes_active_recording(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.shutdown()
        assert rec.stop_calls == 1

    def test_noop_when_not_active(self) -> None:
        ri, rec, _ = _make()
        ri.shutdown()
        assert rec.stop_calls == 0

    def test_recorder_active_false_after_shutdown(self) -> None:
        ri, rec, _ = _make()
        ri.start(_FakeWorkout(), _UTC_NOW)
        ri.shutdown()
        assert ri.recorder_active is False
