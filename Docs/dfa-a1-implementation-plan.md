# DFA α1 — Phased Implementation Plan

Companion to [`dfa-a1-implementation.md`](dfa-a1-implementation.md) (the "spec"). This file
sequences the work into reasonably-scoped, mostly-independent phases and recommends a model
for each. Technical detail is **not** repeated here — each phase points at the relevant spec
section(s).

**Workflow reminder (per `CLAUDE.md`):** TDD throughout — write the failing tests first, get
them failing for the right reason, then implement. Run the suite with the `test-runner`
agent. Bump the version to **0.3.0** (MINOR) at the end (Phase 7), not before.

## Model-choice rationale (summary)

- **Opus** for anything where correctness is subtle and a plausible-but-wrong
  implementation would pass naive tests — i.e. the numerical core and the artifact
  classifier reproduced from papers.
- **Sonnet Medium** for the mechanical, well-bounded work (decoding, plumbing, UI, recorder)
  now that the spec names exact files, fields, and gotchas.
- **Sonnet Low** is fine for isolated tweaks within an already-built phase.

The TDD guardrails are what make the Sonnet phases safe: write (and ideally have Opus review)
the reference tests first.

---

## ~~Phase 0 — RR-interval acquisition ~~ Done

**Goal:** surface the RR stream OCT currently discards, end to end, with no DFA math yet.
**Spec:** [0a] (decoder, metrics, sensor sample, fan-out, source selection).
**Touches:** `devices/decoders/hrs.py`, `devices/decoders/base.py`, `core/sensors.py`,
`ui/main_window.py`.
**Tests first:** `tests/test_sensor_decoders.py` — HR-only (no RR), single RR, multi-RR,
RR-after-energy-expended offset; 1/1024 s → ms conversion.
**Exit criteria:** a connected strap's RR values reach a consumer (log/stub) in ms; HR
behaviour unchanged; non-RR straps degrade silently.
**Model:** **Sonnet Medium.** Mechanical bit-twiddling fully specified; main risk (the
energy-expended offset) is called out and covered by a test.
**Depends on:** nothing. Can start immediately.

---

## ~~Phase 1 — DFA numerical core~~ Done

**Goal:** the pure estimator — smoothness-priors detrend + DFA over scales 4–16 → α1 + R².
**Spec:** [3] (detrending), [4] (DFA), [0c] (numpy-only, no scipy).
**Touches:** `core/dfa/dfa.py` (new).
**Tests first:** `tests/test_dfa.py` — white-noise → α≈0.5, Brownian → α≈1.5; banded solve
matches a dense `numpy.linalg.solve` reference; log-log slope/R² against a hand-computed case.
**Exit criteria:** estimator passes synthetic-exponent tests; detrend solve verified against
dense reference; no scipy import.
**Model:** **Opus.** Numerical subtlety; the synthetic-exponent and dense-solve reference
tests are the contract — worth Opus to get the math and the banded solve exactly right.
**Depends on:** nothing (pure math). Can run in parallel with Phase 0.

---

## ~~Phase 2 — Artifact correction~~ Done

**Goal:** the adaptive Lipponen–Tarvainen classifier + correction actions.
**Spec:** [1] (gross gate, adaptive classifier, correction actions, breakdown counts).
**Touches:** `core/dfa/artifact.py` (new).
**Tests first:** `tests/test_dfa_artifact.py` — gross gate (300/2000 ms), missed / extra /
ectopic classification, resulting `artifact_breakdown` and `max_correction_run`.
**Exit criteria:** classifier reproduces the paper's decision tree; correction actions
(split / merge / spline) behave on crafted sequences; counts are accurate.
**Model:** **Opus.** Highest-risk part — "reproduce the decision tree from the paper" is real
reasoning from branch logic, and a subtle error is hard to catch in review.
**Depends on:** nothing. Parallelizable with Phases 0–1.

---

## Phase 3 — Pipeline assembly

**Goal:** tie Phases 0–2 together: RR ring buffer, 120 s windowing, 5 s recompute tick,
quality gate, `DfaRecord` (incl. `mean_power_w`), `latest_record`.
**Spec:** [2] (window selection), [5] (quality metrics + gate + record), [0d] (GUI-thread
QTimer pull model), [0e] (enable = tile selected).
**Touches:** `core/dfa/pipeline.py` (new); wire RR feed from `ui/main_window.py`; inject a
power source for `mean_power_w` (`power_history.windowed_avg`).
**Tests first:** `tests/test_dfa_pipeline.py` — buffer fills to ≥120 000 ms; 5 s cadence;
quality transitions INSUFFICIENT→GOOD→POOR; "no RR" → correct `quality_reason`;
`mean_power_w` populated from the power source.
**Exit criteria:** feeding a recorded RR+power stream yields a sane α1 trace with quality
flags; pipeline is Qt-free and unit-tested.
**Model:** **Sonnet Medium** (consider High for the quality-gate edge cases). Orchestration
over finished, tested parts; logic is enumerated in [5d]/[5e].
**Depends on:** Phases 0, 1, 2.

---

## Phase 4 — Tile + detail popup (+ window power)

**Goal:** the `dfa_a1` grid tile with quality dot, click-to-open `Qt.Popup` detail modal,
and the window-average power readout.
**Spec:** [7] (tile, popup, click/drag disambiguation, window-power display).
**Touches:** `ui/workout_screen.py` (`DfaMetricTile`), `ui/tile_config.py` (register
`dfa_a1`), `ui/tile_computation.py` (`dfa_source` + `dfa_a1` branch), `ui/theme.py` (quality
colours).
**Tests first:** extend `tests/test_tile_computation.py` (`dfa_a1` value / `--` cases); a
`DfaMetricTile` test that a sub-threshold click toggles the popup while a drag still emits
`drag_requested`.
**Exit criteria:** tile shows α1 + dot, refreshes on the normal tile cadence; popup opens/
closes correctly and shows window power + detail; drag-reorder still works.
**Model:** **Sonnet Medium.** UI pattern is sketched with existing analogues
(`KJMetricTile`, `paused_overlay`).
**Depends on:** Phase 3 (needs `latest_record`).

---

## Phase 5 — Chart overlay

**Goal:** live α1 trace on both charts, secondary right-hand y-axis, gated by tile selection.
**Spec:** [8] (twin-axis, violet `#a855f7`, NaN gaps on POOR/INSUFFICIENT, teardown).
**Touches:** `ui/workout_chart.py`; α1 history buffer fed each emit (alongside power/HR
series wiring in the workout controller).
**Tests first:** chart-series construction test (e.g. extend `tests/test_chart_history.py`):
α1 pairs build correctly, NaN inserted for suppressed windows.
**Exit criteria:** α1 plots on its own axis in a distinct colour only when the tile is on;
removed cleanly when off; existing traces unaffected.
**Model:** **Sonnet Medium.** Mostly a pyqtgraph twin-axis pattern; visual, low correctness
risk.
**Depends on:** Phase 3 (record stream); independent of Phase 4.

---

## Phase 6 — Recording & FIT export

**Goal:** persist α1 (forward-filled into 1 Hz rows) to JSONL and, best-effort, to FIT.
**Spec:** [9] (forward-fill, `RecorderSample`/JSONL field, FIT developer data field,
`JsonFitWriterBackend` parity).
**Touches:** `core/recorder.py`, `core/fit_exporter.py`.
**Tests first:** extend `tests/test_recorder.py` (forward-filled `dfa_alpha1` in JSONL) and
`tests/test_fit_exporter.py` (developer-field path via `JsonFitWriterBackend`).
**Exit criteria:** saved `.samples.jsonl` carries `dfa_alpha1`; FIT writes the developer
field when present and degrades gracefully if not; FIT tests deterministic.
**Model:** **Sonnet Medium.** Well-bounded; the only nuance (FIT developer fields) is
isolated and best-effort.
**Depends on:** Phase 3.

---

## Phase 7 — Integration, validation & release

**Goal:** prove the whole thing against an oracle and ship.
**Spec:** "Validation plan" (Kubios oracle, ~0.05 agreement, reconciliation order); [0e]
(version bump); [0c] (declare numpy in `pyproject.toml`).
**Work:** capture a real Polar H10 RR+power session; compare per-window α1 to Kubios
(λ=500, DFA 4–16); reconcile offsets in the spec's order (box direction → resample →
artifact correction); end-to-end smoke test in-app (tile, popup, chart, saved files);
declare `numpy`; bump `pyproject.toml` + `opencycletrainer/__init__.py` to **0.3.0**.
**Exit criteria:** Kubios agreement within ~0.05 across a session; clean live run; version
bumped; full suite green.
**Model:** **Opus** for the numerical reconciliation (diagnosing systematic offsets is
exactly where the math judgment matters); the smoke test / version bump can be **Sonnet Low**
or done by hand. A real device capture is a **human** step.
**Depends on:** all prior phases.

---

## Suggested sequencing

```
Phase 0 ─┐
Phase 1 ─┼─►  Phase 3  ─►  Phase 4
Phase 2 ─┘              ├─►  Phase 5     ─►  Phase 7
                        └─►  Phase 6
```

Phases 0–2 are independent and can be built in parallel (0 = Sonnet, 1 & 2 = Opus). Phase 3
gates the rest; Phases 4–6 are independent of each other once 3 lands. Phase 7 is last and
needs a real device capture.
