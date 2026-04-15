from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from opencycletrainer.core.fit_exporter import FitExporter, JsonFitWriterBackend
from opencycletrainer.core.recorder import RecorderSample, WorkoutRecorder
from opencycletrainer.core.workout_metrics import WorkoutMetrics, compute_workout_metrics

_BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _s(
    idx: int,
    *,
    trainer: int | None = None,
    bike: int | None = None,
    hr: int | None = None,
) -> RecorderSample:
    """Minimal 1Hz RecorderSample at *idx* seconds from _BASE."""
    return RecorderSample(
        timestamp_utc=_BASE + timedelta(seconds=idx),
        trainer_power_watts=trainer,
        bike_power_watts=bike,
        heart_rate_bpm=hr,
    )


def _steady(n: int, watts: int, hr: int | None = None) -> list[RecorderSample]:
    """*n* 1Hz samples all at *watts* trainer power with optional constant HR."""
    return [_s(i, trainer=watts, hr=hr) for i in range(n)]


# ---------------------------------------------------------------------------
# avg_power_watts
# ---------------------------------------------------------------------------


class TestAvgPower:
    def test_steady_state_equals_sample_power(self) -> None:
        metrics = compute_workout_metrics(_steady(60, 200), ftp_watts=250)
        assert metrics.avg_power_watts == pytest.approx(200.0)

    def test_variable_power_is_simple_mean(self) -> None:
        # Alternating 100 W / 300 W → mean = 200 W
        samples = [_s(i, trainer=100 if i % 2 == 0 else 300) for i in range(60)]
        metrics = compute_workout_metrics(samples, ftp_watts=250)
        assert metrics.avg_power_watts == pytest.approx(200.0)

    def test_uses_bike_power_over_trainer(self) -> None:
        samples = [_s(i, trainer=200, bike=300) for i in range(60)]
        metrics = compute_workout_metrics(samples, ftp_watts=250)
        assert metrics.avg_power_watts == pytest.approx(300.0)

    def test_falls_back_to_trainer_when_bike_absent(self) -> None:
        # First 30 samples: bike=300; last 30: bike absent, trainer=200
        samples = [
            _s(i, trainer=200, bike=300 if i < 30 else None) for i in range(60)
        ]
        metrics = compute_workout_metrics(samples, ftp_watts=250)
        # 30 × 300 + 30 × 200 = 15 000; / 60 = 250
        assert metrics.avg_power_watts == pytest.approx(250.0)

    def test_none_when_all_power_absent(self) -> None:
        metrics = compute_workout_metrics([_s(i) for i in range(60)], ftp_watts=250)
        assert metrics.avg_power_watts is None

    def test_single_sample(self) -> None:
        metrics = compute_workout_metrics([_s(0, trainer=180)], ftp_watts=250)
        assert metrics.avg_power_watts == pytest.approx(180.0)

    def test_empty_samples(self) -> None:
        metrics = compute_workout_metrics([], ftp_watts=250)
        assert metrics.avg_power_watts is None


# ---------------------------------------------------------------------------
# kj
# ---------------------------------------------------------------------------


class TestKilojoules:
    def test_one_minute_at_200w(self) -> None:
        # 60 samples × 200 W × 1 s / 1000 = 12 kJ
        metrics = compute_workout_metrics(_steady(60, 200), ftp_watts=250)
        assert metrics.kj == pytest.approx(12.0)

    def test_zero_when_no_power_data(self) -> None:
        metrics = compute_workout_metrics([_s(i) for i in range(60)], ftp_watts=250)
        assert metrics.kj == pytest.approx(0.0)

    def test_uses_bike_power_for_kj(self) -> None:
        # bike=300 W for 60 s → 18 kJ  (trainer=200 ignored)
        samples = [_s(i, trainer=200, bike=300) for i in range(60)]
        metrics = compute_workout_metrics(samples, ftp_watts=250)
        assert metrics.kj == pytest.approx(18.0)

    def test_accumulation_per_sample_second(self) -> None:
        # 10 samples × 500 W × 1 s / 1000 = 5 kJ
        metrics = compute_workout_metrics(_steady(10, 500), ftp_watts=250)
        assert metrics.kj == pytest.approx(5.0)

    def test_empty_samples_returns_zero(self) -> None:
        metrics = compute_workout_metrics([], ftp_watts=250)
        assert metrics.kj == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# normalized_power
# ---------------------------------------------------------------------------


class TestNormalizedPower:
    def test_steady_state_np_equals_sample_power(self) -> None:
        metrics = compute_workout_metrics(_steady(60, 200), ftp_watts=250)
        assert metrics.normalized_power == 200

    def test_none_for_fewer_than_30_samples(self) -> None:
        metrics = compute_workout_metrics(_steady(29, 200), ftp_watts=250)
        assert metrics.normalized_power is None

    def test_none_for_empty_samples(self) -> None:
        metrics = compute_workout_metrics([], ftp_watts=250)
        assert metrics.normalized_power is None

    def test_exactly_30_samples_produces_result(self) -> None:
        metrics = compute_workout_metrics(_steady(30, 200), ftp_watts=250)
        assert metrics.normalized_power is not None

    def test_variable_power_np_exceeds_avg(self) -> None:
        """NP amplifies variability: first-half/second-half split forces rolling mean
        to pass through a wide range, lifting the 4th-power average above 200 W."""
        # First 30 at 100 W, last 30 at 300 W → avg = 200 W, NP > 200 W
        samples = [_s(i, trainer=100 if i < 30 else 300) for i in range(60)]
        metrics = compute_workout_metrics(samples, ftp_watts=250)
        assert metrics.normalized_power is not None
        assert metrics.avg_power_watts is not None
        assert metrics.normalized_power > int(metrics.avg_power_watts)

    def test_np_computed_from_effective_power_not_trainer_only(self) -> None:
        # bike=300 W steady → NP should equal 300 (not trainer 200)
        samples = [_s(i, trainer=200, bike=300) for i in range(60)]
        metrics = compute_workout_metrics(samples, ftp_watts=250)
        assert metrics.normalized_power == 300


# ---------------------------------------------------------------------------
# avg_hr
# ---------------------------------------------------------------------------


class TestAvgHr:
    def test_computed_from_sample_hr_values(self) -> None:
        metrics = compute_workout_metrics(_steady(60, 200, hr=150), ftp_watts=250)
        assert metrics.avg_hr == 150

    def test_none_when_all_hr_missing(self) -> None:
        metrics = compute_workout_metrics(_steady(60, 200, hr=None), ftp_watts=250)
        assert metrics.avg_hr is None

    def test_ignores_none_hr_values(self) -> None:
        # First 30 samples have HR=140; last 30 have no HR → avg from non-None only
        samples = [_s(i, trainer=200, hr=140 if i < 30 else None) for i in range(60)]
        metrics = compute_workout_metrics(samples, ftp_watts=250)
        assert metrics.avg_hr == 140

    def test_avg_hr_is_int(self) -> None:
        # 30 samples at 140 bpm + 30 samples at 141 bpm → avg 140.5 → int
        samples = (
            [_s(i, trainer=200, hr=140) for i in range(30)]
            + [_s(i + 30, trainer=200, hr=141) for i in range(30)]
        )
        metrics = compute_workout_metrics(samples, ftp_watts=250)
        assert isinstance(metrics.avg_hr, int)

    def test_empty_samples_returns_none_hr(self) -> None:
        metrics = compute_workout_metrics([], ftp_watts=250)
        assert metrics.avg_hr is None


# ---------------------------------------------------------------------------
# tss
# ---------------------------------------------------------------------------


class TestTss:
    def test_tss_formula_at_ftp_for_known_duration(self) -> None:
        """TSS = (duration_s × NP × IF) / (FTP × 3600) × 100; at FTP IF=1.0."""
        n = 30  # minimum for NP
        ftp = 250
        metrics = compute_workout_metrics(_steady(n, ftp), ftp_watts=ftp)
        assert metrics.tss is not None
        expected = (n * ftp * 1.0) / (ftp * 3600.0) * 100.0
        assert abs(metrics.tss - expected) < 0.01

    def test_none_when_np_is_none(self) -> None:
        # Fewer than 30 samples → NP is None → TSS must also be None
        metrics = compute_workout_metrics(_steady(20, 200), ftp_watts=250)
        assert metrics.tss is None

    def test_none_when_ftp_is_zero(self) -> None:
        metrics = compute_workout_metrics(_steady(60, 200), ftp_watts=0)
        assert metrics.tss is None

    def test_higher_intensity_yields_higher_tss(self) -> None:
        easy = compute_workout_metrics(_steady(60, 200), ftp_watts=250)
        hard = compute_workout_metrics(_steady(60, 250), ftp_watts=250)
        assert easy.tss is not None
        assert hard.tss is not None
        assert hard.tss > easy.tss


# ---------------------------------------------------------------------------
# WorkoutMetrics dataclass
# ---------------------------------------------------------------------------


class TestWorkoutMetricsDataclass:
    def test_is_frozen(self) -> None:
        metrics = compute_workout_metrics(_steady(60, 200), ftp_watts=250)
        with pytest.raises((AttributeError, TypeError)):
            metrics.avg_power_watts = 999  # type: ignore[misc]

    def test_has_all_required_fields(self) -> None:
        metrics = compute_workout_metrics(_steady(60, 200, hr=150), ftp_watts=250)
        assert hasattr(metrics, "avg_power_watts")
        assert hasattr(metrics, "normalized_power")
        assert hasattr(metrics, "tss")
        assert hasattr(metrics, "avg_hr")
        assert hasattr(metrics, "kj")


# ---------------------------------------------------------------------------
# End-to-end: recorder samples → metrics single source of truth
# ---------------------------------------------------------------------------


def _e2e_data_dir() -> Path:
    path = Path.cwd() / ".tmp_runtime" / "workout_metrics_tests"
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


class TestEndToEnd:
    """Verify that metrics derived from recorder-bound samples agree with what
    WorkoutRecorder.stop() returns, establishing a single source of truth."""

    def test_avg_power_from_metrics_matches_recorder_summary(self) -> None:
        """compute_workout_metrics avg power must equal the recorder's running average."""
        data_dir = _e2e_data_dir()
        recorder = WorkoutRecorder(
            data_dir=data_dir,
            flush_batch_size=5,
            fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
        )
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        recorder.start("E2E Test", started_at_utc=start)
        for i in range(60):
            recorder.record_sample(
                RecorderSample(
                    timestamp_utc=start + timedelta(seconds=i),
                    trainer_power_watts=200,
                    heart_rate_bpm=150,
                )
            )
        summary = recorder.stop(finished_at_utc=start + timedelta(seconds=60))
        samples = recorder.get_recorded_samples()

        metrics = compute_workout_metrics(samples, ftp_watts=250)

        assert metrics.avg_power_watts == pytest.approx(summary.avg_power_watts)

    def test_recorder_summary_provides_np_from_metrics_calculator(self) -> None:
        """After stop(), RecorderSummary.normalized_power must equal
        compute_workout_metrics() result on the same samples."""
        data_dir = _e2e_data_dir()
        recorder = WorkoutRecorder(
            data_dir=data_dir,
            flush_batch_size=5,
            fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
        )
        start = datetime(2026, 1, 2, 8, 0, 0, tzinfo=timezone.utc)
        recorder.start("E2E NP Test", started_at_utc=start)
        for i in range(60):
            recorder.record_sample(
                RecorderSample(
                    timestamp_utc=start + timedelta(seconds=i),
                    trainer_power_watts=200,
                    heart_rate_bpm=150,
                )
            )
        summary = recorder.stop(finished_at_utc=start + timedelta(seconds=60))
        samples = recorder.get_recorded_samples()

        metrics = compute_workout_metrics(samples, ftp_watts=250)

        # RecorderSummary must expose normalized_power computed by the metrics module.
        assert summary.normalized_power == metrics.normalized_power  # type: ignore[attr-defined]

    def test_recorder_summary_provides_kj_from_metrics_calculator(self) -> None:
        """After stop(), RecorderSummary.kj must equal compute_workout_metrics() kj."""
        data_dir = _e2e_data_dir()
        recorder = WorkoutRecorder(
            data_dir=data_dir,
            flush_batch_size=5,
            fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
        )
        start = datetime(2026, 1, 3, 8, 0, 0, tzinfo=timezone.utc)
        recorder.start("E2E kJ Test", started_at_utc=start)
        for i in range(60):
            recorder.record_sample(
                RecorderSample(
                    timestamp_utc=start + timedelta(seconds=i),
                    trainer_power_watts=200,
                )
            )
        summary = recorder.stop(finished_at_utc=start + timedelta(seconds=60))
        samples = recorder.get_recorded_samples()

        metrics = compute_workout_metrics(samples, ftp_watts=250)

        # 60 samples × 200 W × 1 s / 1000 = 12 kJ
        assert metrics.kj == pytest.approx(12.0)
        assert summary.kj == pytest.approx(metrics.kj)  # type: ignore[attr-defined]

    def test_recorder_summary_provides_avg_hr_from_metrics_calculator(self) -> None:
        """After stop(), RecorderSummary.avg_hr must equal compute_workout_metrics() avg_hr."""
        data_dir = _e2e_data_dir()
        recorder = WorkoutRecorder(
            data_dir=data_dir,
            flush_batch_size=5,
            fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
        )
        start = datetime(2026, 1, 4, 8, 0, 0, tzinfo=timezone.utc)
        recorder.start("E2E HR Test", started_at_utc=start)
        for i in range(60):
            recorder.record_sample(
                RecorderSample(
                    timestamp_utc=start + timedelta(seconds=i),
                    trainer_power_watts=200,
                    heart_rate_bpm=148,
                )
            )
        summary = recorder.stop(finished_at_utc=start + timedelta(seconds=60))
        samples = recorder.get_recorded_samples()

        metrics = compute_workout_metrics(samples, ftp_watts=250)

        assert metrics.avg_hr == 148
        assert summary.avg_hr == metrics.avg_hr  # type: ignore[attr-defined]

    def test_metrics_consistent_across_variable_power_stream(self) -> None:
        """With non-uniform power, metrics derived from recorded samples remain
        internally consistent: NP >= avg and kJ matches manual sum."""
        data_dir = _e2e_data_dir()
        recorder = WorkoutRecorder(
            data_dir=data_dir,
            flush_batch_size=5,
            fit_exporter=FitExporter(writer_backend=JsonFitWriterBackend()),
        )
        start = datetime(2026, 1, 5, 8, 0, 0, tzinfo=timezone.utc)
        recorder.start("E2E Variable Power", started_at_utc=start)
        powers = [100 if i < 30 else 300 for i in range(60)]
        for i, w in enumerate(powers):
            recorder.record_sample(
                RecorderSample(
                    timestamp_utc=start + timedelta(seconds=i),
                    trainer_power_watts=w,
                )
            )
        recorder.stop(finished_at_utc=start + timedelta(seconds=60))
        samples = recorder.get_recorded_samples()

        metrics = compute_workout_metrics(samples, ftp_watts=250)

        expected_kj = sum(powers) / 1000.0  # 60 × 1 s each
        assert metrics.kj == pytest.approx(expected_kj)
        assert metrics.avg_power_watts == pytest.approx(200.0)
        assert metrics.normalized_power is not None
        assert metrics.normalized_power > int(metrics.avg_power_watts)
