# DFA α1 — Implementation Brief (Clean-Room Spec)

> Implemented in `opencycletrainer/core/dfa/`. This document is the algorithm reference
> (sources, parameters, quality gate). How α1 is wired into the app (tile, chart,
> recording, FIT export) is described in [ArchitectureDiagram.md](ArchitectureDiagram.md).

**Target:** Real-time short-term scaling exponent (DFA α1) for a desktop ERG-trainer
control app, computed from a BLE chest-strap RR-interval stream.

**Provenance / licensing note for the implementer:** Implement every stage below
**from the equations and the cited papers only**. Do **not** copy, port, or translate
source from RHRV (GPL), FatMaxxer, Kubios, or any DDFA/ZoneSense implementation. The
classic DFA α1 method (Peng 1995), smoothness-priors detrending (Tarvainen 2002), and
adaptive artifact correction (Lipponen & Tarvainen 2019) are all published, non-patent-
encumbered algorithms. **Do not implement DDFA threshold pipelines** — that flavour is
patented (MoniCardi/Suunto). This spec is classic DFA α1 only.

References to implement from:
- Peng et al. 1995, *Chaos* 5(1):82–87 — DFA.
- Tarvainen, Ranta-aho & Karjalainen 2002, *IEEE TBME* 49(2):172–175 — smoothness-priors detrending.
- Lipponen & Tarvainen 2019, *J. Med. Eng. Technol.* 43(3):173–181 — artifact correction.
- Gronwald/Rogers protocol parameters: 120 s window, 4 ≤ n ≤ 16, λ = 500.

---

## Design parameters (defaults)

| Parameter | Value | Notes |
|---|---|---|
| Analysis window | 120 s | Standard. RR buffer ≥ 120 000 ms of corrected beats. |
| Recompute cadence | every 5 s (wall clock) | Output grid. |
| DFA scales (box sizes) `n` | integers 4…16 inclusive | 13 scales. This *defines* α1. |
| Within-box detrend order | 1 (linear) | DFA1 → α1. |
| Smoothness-priors λ | 500 | Matches Kubios/Gronwald default. |
| RR plausibility bounds | 300–2000 ms | Hard gate (≈30–200 bpm). Tunable. |
| Artifact-fraction suppression | > 5 % corrected in window → flag/suppress | Rogers' trustworthiness rule. |
| Float precision | float64 everywhere | Desktop — no reason to economize. |

Because this is a desktop app with compute to spare, every window is recomputed **from
scratch** on the exact corrected RR series. No incremental/approximated detrending.

---

## Data flow

```
BLE RR stream (ms)
      │
      ▼
[1] Artifact correction  ──►  corrected RR series + per-beat corrected flag
      │
      ▼
[2] Window selection      ──►  last 120 s of corrected RR  (beat-indexed, no time resample)
      │
      ▼
[3] Smoothness-priors detrend (λ=500)  ──►  stationary RR series
      │
      ▼
[4] DFA over scales 4..16  ──►  α1 (slope of log F(n) vs log n)
      │
      ▼
[5] Quality gate + pair with mean window power  ──►  emit {t, α1, mean_power, quality}
```

Keep DFA and detrending on the **beat-indexed** RR series. Do **not** resample to an even
time grid — the exercise DFA α1 literature operates on the beat series, and resampling
changes the exponent.

---

## [1] Artifact correction (adaptive — recommended)

Indoors on a trainer, gross motion is minimal, but electrode/contact noise (dry skin
early, strap shift, sweat onset) still produces missed/extra/ectopic beats. Use a robust
adaptive detector rather than a fixed percentage threshold.

### 1a. Gross physiological gate
```
for each rr in stream:
    if rr < RR_MIN (300) or rr > RR_MAX (2000):
        mark rr as artifact (impossible); correct via 1c
```

### 1b. Adaptive local classifier (Lipponen & Tarvainen 2019)
Implement the published decision tree. Summary of the logic to realize from the paper:

```
dRR[i]  = RR[i] - RR[i-1]                      # successive differences
# Time-varying threshold from local dispersion (quartile deviation):
Th1[i]  = C1 * QD( dRR over centered window of 91 beats )     # C1 ≈ 5.2  (see paper)
drr[i]  = dRR[i] / Th1[i]                        # normalized

medRR[i]   = median( RR over centered window of 11 beats )
mRR[i]     = RR[i] - medRR[i]
Th2[i]     = C2 * QD( mRR over centered window of 91 beats )  # C2 ≈ 3.0  (see paper)
mrr[i]     = mRR[i] / Th2[i]

classify beat i ∈ {normal, ectopic, long, short, missed, extra}
   using the signed relationships between drr[i], drr[i+1], mrr[i]
   and unit thresholds, per the paper's decision tree.
```
> Pull the exact constants (C1, C2, window lengths, the branch comparisons) from the 2019
> paper and reproduce the decision tree in your own code. Do not copy any implementation.

### 1c. Correction actions
```
missed beat   (RR ≈ 2 × local median)   → split interval into two equal halves
extra  beat   (RR ≈ 0.5 × local median) → merge with adjacent interval
ectopic/long/short                      → replace by cubic-spline interpolation
                                          using nearest NORMAL beats on each side
```
Maintain `corrected_count` per analysis window.

### 1d. Relaxation for clean indoor data (optional)
Because trainer data is cleaner, you may widen Th1/Th2 scaling slightly to avoid
over-correcting genuine HRV. Expose the scaling as a config knob; default to paper values.

---

## [2] Window selection

```
maintain ring buffer of (timestamp, rr_ms, corrected_flag)
on each 5 s tick:
    accumulate most-recent beats until Σ rr_ms ≥ 120 000
    -> window W (beat-indexed array of corrected RR values, length N)
    artifact_fraction = corrected_count_in_W / N
```
Typical N at 120 s: ~150 (slow) to ~400 (hard). Trivial sizes for exact linear algebra.

---

## [3] Smoothness-priors detrending (Tarvainen 2002)

Removes the slow HR drift across the window before DFA. This is the step web/embedded
implementations approximate; **on desktop, do it exactly.**

Let `z` be the length-N windowed RR vector. Let `D2` be the (N-2)×N second-order
difference operator (each row `[1, -2, 1]` sliding along the diagonal). Then:

```
A = I + (λ^2) * (D2ᵀ · D2)          # N×N, symmetric positive-definite, PENTADIAGONAL
z_trend = solve(A, z)                # i.e. A · z_trend = z
z_stat  = z - z_trend                # detrended (stationary) RR series  ← feed to DFA
```

Implementation notes:
- **Solve the system; do not invert** `A` explicitly (more stable, faster).
- `A` is symmetric positive-definite → use **Cholesky** (`LLT`). Exact and fast.
- `A` is **banded (pentadiagonal)** → a banded Cholesky is O(N). Prefer it to a dense solve,
  whose cost depends on the BLAS threading configuration (see Dependencies above).
- λ = 500. (λ tunes the cutoff; 500 is the protocol default — keep configurable.)
- Build `D2` as a sparse/banded matrix; never materialize dense `D2ᵀD2` if using a banded path.

Python/NumPy sketch:
```python
import numpy as np
from scipy.linalg import solveh_banded   # or scipy.sparse + splu

def detrend_smoothness_priors(z, lam=500.0):
    N = len(z)
    # Second-difference operator D2: (N-2) x N
    e = np.ones(N)
    from scipy.sparse import spdiags, identity
    D2 = spdiags([e, -2*e, e], [0, 1, 2], N-2, N)
    A = identity(N) + (lam**2) * (D2.T @ D2)        # sparse, banded, SPD
    from scipy.sparse.linalg import spsolve
    z_trend = spsolve(A.tocsc(), z)
    return z - z_trend                               # z_stat
```
C++/Eigen alternative: `Eigen::SimplicialLLT` on a `SparseMatrix<double>`, or
`Eigen::LDLT` on the dense `A`.

---

## [4] DFA computation → α1 (Peng 1995)

Operate on `y = z_stat` (length N).

```
# 4.1 Profile (integrated, mean-removed series)
mu = mean(y)
Y[k] = Σ_{i=1..k} (y[i] - mu)          for k = 1..N      # cumulative sum

# 4.2 Fluctuation at each scale
for n in 4..16:                         # integer box sizes
    num_boxes = floor(N / n)
    if num_boxes < 1: skip scale (insufficient data)
    sum_sq = 0
    for b in 0 .. num_boxes-1:
        seg = Y[b*n : b*n + n]                  # one box of length n
        fit = least_squares_line(x = 1..n, seg) # local LINEAR detrend
        resid = seg - fit
        sum_sq += mean(resid^2)                 # mean-squared residual of this box
    F[n] = sqrt( sum_sq / num_boxes )

# 4.3 Scaling exponent
# Linear regression of log F(n) on log n, over n = 4..16:
alpha1 = slope( log(n_used), log(F[n_used]) )
```

Details:
- **Box direction:** classic Peng / Kubios convention is **forward, non-overlapping**
  (`floor(N/n)` boxes; trailing remainder unused). Use this to match Kubios when
  validating. (A both-ends variant — `2*floor(N/n)` boxes — uses all data and is slightly
  more stable, but can introduce a small offset vs Kubios. Make it a flag, default OFF.)
- **Within-box fit:** order-1 least squares. Since x = 1..n is fixed, precompute the
  regression normal-equation coefficients once per `n` for speed and exactness.
- Use all 13 integer scales 4..16 for the log-log regression (this is the *definition*
  of α1 — do not log-space or subsample).
- Guard: require every scale 4..16 to have ≥ 1 box; with N≥~150 this always holds.

---

## [5] Quality metrics

Compute all quality signals below on every window, regardless of whether α1 is
ultimately shown. They feed both the quality gate and the UI expand panel.

### 5a. Artifact metrics (from stage [1])

```python
# Counts accumulated during artifact correction of window W
artifact_fraction   = corrected_count / N          # float 0..1
artifact_breakdown  = {
    "missed":  count_missed,
    "extra":   count_extra,
    "ectopic": count_ectopic,
    "long":    count_long,
    "short":   count_short,
}
# Longest run of consecutive corrected beats in W
max_correction_run  = max run length of corrected_flag == True in W
```

Diagnostic meaning of the breakdown (surface in UI tooltip):
- Predominantly **missed/extra**: strap contact noise (dry skin, strap shift). User action: re-wet strap, tighten.
- Predominantly **ectopic**: genuine cardiac ectopy, fatigue, or caffeine. Physiologically different from contact noise; note it distinctly.
- **max_correction_run > 3**: interpolation is spanning a gap — α1 in this window is partially synthetic. Flag even if artifact_fraction is below threshold.

### 5b. RMSSD (from corrected RR window)

Compute on the corrected beat-indexed RR series before detrending. Standard
time-domain HRV measure; declines with intensity; familiar to users of resting HRV apps.

```python
successive_diffs = np.diff(RR_window)          # length N-1
RMSSD = np.sqrt(np.mean(successive_diffs ** 2))   # ms
```

No detrending needed — RMSSD is inherently short-term and not sensitive to slow drift.

### 5c. Log-log linearity R² (from stage [4])

The α1 regression is a linear fit of `log F(n)` on `log n` across 13 points. The
residual R² of that regression is an independent signal quality indicator: it tells you
whether the RR series actually exhibits clean fractal scaling, regardless of artifact
counts.

```python
# After computing log_n = log([4..16]) and log_F = log(F[4..16]):
slope, intercept, r_value, _, _ = scipy.stats.linregress(log_n, log_F)
alpha1  = slope
r2_loglog = r_value ** 2        # target > 0.97 for a trustworthy α1
```

R² can be low even when artifact_fraction is low — a genuine signal with a transient
intensity change or strap noise spike that slipped correction will scatter the log-log
plot. Treat artifact_fraction and r2_loglog as complementary, not redundant.

### 5d. Composite quality gate

```python
from enum import Enum

class SignalQuality(Enum):
    GOOD         = "good"          # green  — show α1
    DEGRADED     = "degraded"      # amber  — show α1 with warning
    POOR         = "poor"          # red    — suppress α1 value
    INSUFFICIENT = "insufficient"  # grey   — window not yet full

def compute_quality(artifact_fraction, r2_loglog, N, max_correction_run) -> SignalQuality:
    if N < N_MIN:                          return SignalQuality.INSUFFICIENT
    if artifact_fraction > 0.05 \
       or r2_loglog < 0.95 \
       or max_correction_run > 5:          return SignalQuality.POOR
    if artifact_fraction > 0.02 \
       or r2_loglog < 0.97 \
       or max_correction_run > 3:          return SignalQuality.DEGRADED
    return SignalQuality.GOOD
```

When quality is POOR: emit `alpha1 = None`. UI shows `--` with red indicator and
a specific reason string (see §6 UI spec). Never silently show a suppressed α1 as zero.

### 5e. Output record

In OCT this is a frozen `DfaRecord` dataclass (`core/dfa/pipeline.py`), not a loose dict,
with **snake_case** fields so the UI/recorder reference them as attributes
(`record.rmssd_ms`, `record.r2_loglog`, …):

```python
@dataclass(frozen=True)
class DfaRecord:
    t:                  datetime
    alpha1:             float | None       # None when quality == POOR or INSUFFICIENT
    mean_power_w:       float
    hr_bpm:             float              # 60000 / mean(RR_window)
    rmssd_ms:           float
    quality:            SignalQuality
    artifact_fraction:  float
    artifact_breakdown: dict
    max_correction_run: int
    r2_loglog:          float
    quality_reason:     str                # human-readable; see below
```

`DfaPipeline.latest_record` holds the most recent one; the tile, chart, and recorder all
pull from it.

**`mean_power_w` definition (OCT):** the average power over the **same ~120 s window** the
α1 reading covers, so the user can read α1 against the power that produced it. Compute it at
each 5 s recompute via OCT's existing `power_history.windowed_avg(now, DFA_WINDOW_SECONDS)`
(`DFA_WINDOW_SECONDS = 120`). The RR buffer overshoots 120 000 ms slightly to land on a beat
boundary; a clean 120 s wall-clock power window aligned to the same recompute instant is the
right approximation — do **not** try to match the beat-window's exact span. `None` until the
window is full / no power data.

**quality_reason examples** (pick the first matching condition):
- `"No RR data from strap"` (strap connected but never sets the RR-present flag, or no HR device)
- `"Insufficient data (window filling…)"`
- `"High artifact rate ({artifact_fraction:.0%} corrected beats)"`
- `"Predominantly ectopic beats — check fatigue or strap"`
- `"Strap contact: {count_missed} missed + {count_extra} extra beats"`
- `"Noisy scaling fit (R²={r2_loglog:.2f})"`
- `"Long correction run ({max_correction_run} consecutive)"`
- `""` (empty string when GOOD)

---

## [6] Threshold use (ramp / cluster) — app layer

> **DEFERRED — out of scope for the first iteration.** Product decision: no automated
> VT1/VT2 detection or zone classification. Users perform ramp tests ad hoc and read the
> threshold crossings off the live α1 tile/chart manually. The material below is retained
> as reference for a future iteration; do **not** build it now, and do **not** ship any
> "Zone 1/Zone 2/VO₂" categorical label derived from α1.

- **Ramp (ERG step test):** as ERG target steps up every 3–4 min, record (power, α1)
  using only `quality == GOOD` samples. Estimate VT1 power where α1 crosses **0.75**
  (interpolate between bracketing steps). VT2 ≈ where α1 crosses **0.50**.
- **Cluster:** average power of all GOOD samples whose α1 sits within ±0.05 of 0.75
  → robust VT1 power estimate without a formal ramp.
- Flag and discard α1 during ERG target-change transients — discard any window whose
  120 s span includes a target change, plus require 30–60 s settle before trusting
  the next window.

---

## Validation plan

1. Capture a raw RR file (`.csv` of RR-ms) from a Polar H10 during an indoor ramp.
2. Run the **same file** through Kubios HRV (Smoothn priors λ=500, DFA 4–16) as the oracle.
3. Compare per-window α1. Target agreement: within ~0.05 absolute across the session.
   Larger systematic offsets usually point to (a) box-direction convention mismatch,
   (b) detrending applied to a resampled vs beat series, or (c) artifact-correction
   differences. Reconcile in that order.
4. Unit-test DFA on a synthetic series with known exponent (e.g. white noise → α≈0.5,
   integrated white noise / Brownian → α≈1.5) to confirm the core estimator before
   worrying about the HRV-specific stages.

---

## Stage-by-stage clean-room reminder

| Stage | Source to implement from | Avoid copying |
|---|---|---|
| Artifact correction | Lipponen & Tarvainen 2019 (paper) | RHRV `FilterNIHR` (GPL), Kubios |
| Detrending | Tarvainen 2002 (paper) | any GPL HRV lib |
| DFA / α1 | Peng 1995 (paper) | — (textbook math) |

Everything here is derivable from the equations. Keep it that way and the GPL/patent
exposure discussed earlier stays at zero.