# Strava Sync - Feature Spec

## Overview
Add first-party Strava sync for completed workouts. Users connect their Strava account from Settings, then optionally enable automatic upload of completed rides.

This phase targets desktop-only local sync using Strava OAuth and FIT file upload.

---

## Goals

- Add a `Connect with Strava` button in Settings that starts OAuth.
- Add an `Automatically sync rides with Strava` checkbox that is available only after successful authorization.
- Add a `Sync now` action in Settings for manual upload of an existing FIT file.
- Upload completed workout FIT files to Strava when auto-sync is enabled.
- Store OAuth tokens and secrets securely (not in plaintext settings files).
- Keep sync failures non-blocking so rides are still saved locally even if upload fails.
- In a deferred final phase, attach the full-workout power plot image to the uploaded Strava activity.

## Non-Goals (Phase 1)

- Garmin or intervals.icu sync.
- Editing Strava activity metadata after upload.
- Background retry daemon across app restarts.
- Multi-account Strava support.
- Uploading workout plot images (deferred until FIT upload is stable).

---

## User Experience

### Settings Screen

- New Strava section in `Settings`:
  - Status label: `Not connected` / `Connected as <athlete name>`.
  - Button: `Connect with Strava` (shown when disconnected).
  - Button: `Disconnect Strava` (shown when connected).
  - Checkbox: `Automatically sync rides with Strava` (disabled until connected).
  - Button: `Sync now` (enabled only when connected; opens FIT picker rooted at workout FIT directory).
- Save flow:
  - Checkbox value persists in settings.
  - Connection status reflects token validity.

### OAuth Flow (Desktop)

1. User clicks `Connect with Strava`.
2. App starts temporary loopback HTTP listener on `127.0.0.1:<ephemeral-port>`.
3. App opens browser to Strava authorize URL with `redirect_uri=http://127.0.0.1:<port>/callback` and random `state`.
4. User authorizes.
5. Strava redirects to loopback callback with `code`.
6. App validates `state`, exchanges `code` for tokens, stores tokens securely, updates UI to connected.

### Auto Sync Flow

1. Workout completes and recorder writes FIT file.
2. If connected and auto-sync is enabled, app enqueues upload job.
3. Upload runs off UI thread.
4. On success, show short success alert/log.
5. On failure, show non-blocking warning and keep local FIT file.

### Manual Sync Now Flow (Phase 1)

1. User clicks `Sync now` in Settings.
2. App opens file picker at the workout FIT directory (`get_data_dir()`).
3. User selects a `.fit` file.
4. App enqueues upload using the same pipeline used for auto-sync.
5. App shows success/failure status without blocking the UI.

### Deferred Media Sync Flow (Final Phase)

1. After FIT upload succeeds and activity ID is returned, generate a full-workout plot image.
2. Render image using feed-friendly dimensions (avoid overly wide aspect ratio).
3. Upload image to the created Strava activity.
4. If image upload fails, keep activity upload as success and log/show a non-blocking warning.

---

## Security and Secret Storage

Do not store access tokens, refresh tokens, or client secrets in:

- `settings.json`
- workout summary JSON
- logs

### Storage Rules

| Item | Storage |
|---|---|
| `strava_auto_sync_enabled` | `settings.json` (`AppSettings`) |
| `strava_connected` (optional UI hint) | derive from token presence or store in `settings.json` |
| Access token | OS keychain via `keyring` |
| Refresh token | OS keychain via `keyring` |
| Token expiry (`expires_at`) | OS keychain via `keyring` (same payload) |
| Client secret (if required) | OS keychain via `keyring` |

### Security Requirements

- Use `keyring` as the default and only token store for Phase 1.
- If no usable keyring backend is available, fail closed:
  - Do not fall back to plaintext files.
  - Show user-facing message that Strava sync requires secure credential storage.
- Redact tokens/secrets from logs and exceptions.
- Bind callback server to `127.0.0.1` only.
- Validate OAuth `state` on callback before token exchange.
- Use one global app client ID/secret for OpenCycleTrainer OAuth app registration.
- Store per-user Strava OAuth tokens (access/refresh) separately for each local user profile.
- Do not perform Strava fetch/list queries for duplicate detection; use local successful-upload records only.

---

## Proposed Architecture

### New Modules

- `opencycletrainer/integrations/strava/token_store.py`
  - Keyring-backed read/write/delete for Strava token bundle.
- `opencycletrainer/integrations/strava/oauth_flow.py`
  - Loopback server lifecycle, auth URL creation, callback parsing, code exchange.
- `opencycletrainer/integrations/strava/client.py`
  - `stravalib` wrapper for upload and token refresh integration.
- `opencycletrainer/integrations/strava/sync_service.py`
  - Async upload queue used by controller.

### Existing Modules to Update

- `opencycletrainer/storage/settings.py`
  - Add `strava_auto_sync_enabled: bool = False`.
- `opencycletrainer/ui/settings_screen.py`
  - Add Strava UI controls and connect/disconnect handlers.
- `opencycletrainer/ui/workout_controller.py`
  - Trigger upload enqueue after recorder finalization.
- `pyproject.toml`
  - Add dependencies: `stravalib`, `keyring`.

---

## Implementation Plan

### Phase 1: Settings and Data Model

1. Add `strava_auto_sync_enabled` to `AppSettings` serialization/deserialization.
2. Add Strava section UI in Settings screen:
   - Connection status label.
   - `Connect with Strava` button.
   - `Disconnect Strava` button.
   - Auto-sync checkbox (disabled until connected).
   - `Sync now` button:
     - opens file picker defaulting to `get_data_dir()`
     - filters to `*.fit`
     - enqueues selected file for upload.
3. Add tests in `opencycletrainer/tests/test_settings.py` and `test_settings_screen.py`.

### Phase 2: Secure Token Store

1. Implement keyring token store with one structured payload (JSON string) under a service key like `OpenCycleTrainer/Strava`.
2. Add API:
   - `get_tokens()`
   - `save_tokens(token_bundle)`
   - `clear_tokens()`
   - `is_available()`
3. Add unit tests with mocked keyring backend.

### Phase 3: OAuth Connect/Disconnect

1. Implement loopback OAuth helper:
   - ephemeral port selection
   - browser open
   - callback capture with timeout
   - state generation and validation
2. Exchange code for tokens and persist through token store.
3. Fetch athlete profile for connection confirmation text (for example athlete display name).
4. Implement disconnect action:
   - clear keyring token bundle
   - uncheck/disable auto-sync in UI
   - update status label
5. Add integration-style tests around callback parser/state validation.

### Phase 4: Upload Pipeline

1. Add sync service that uploads a FIT path to Strava asynchronously.
2. Wire upload trigger in `WorkoutSessionController._finalize_recorder()`:
   - if `summary.fit_file_path` exists
   - and Strava connected
   - and `strava_auto_sync_enabled` is true
   - enqueue upload
3. Use token refresh callback support from `stravalib` so refreshed tokens are persisted.
4. Add retry policy for transient failures (simple bounded retries in-process).
5. Add tests using a fake Strava client to validate enqueue behavior and failure handling.

### Phase 5: Logging and UX Hardening

1. Add structured logs for:
   - OAuth started/completed/failed
   - Upload started/succeeded/failed
2. Add duplicate-upload prevention:
   - pass a stable `external_id` on Strava upload (for example based on FIT filename/hash)
   - use filename + file size as the dedupe identity
   - track successful uploads locally to avoid re-enqueueing known uploaded FIT files
   - do not query Strava to check duplicate status before upload
   - treat duplicate responses as idempotent success in UI.
3. Ensure no secrets appear in logs.
4. Surface concise user alerts:
   - `Strava connected`
   - `Ride synced to Strava`
   - `Strava sync failed (ride kept locally)`
   - `Ride already synced to Strava` (duplicate case)

### Phase 6: Workout Plot Image Attachment (Deferred Final Phase)

1. Generate full-workout chart snapshot (power vs time) from recorded workout data.
2. Normalize image size for Strava feed readability:
   - prefer portrait or near-square ratio over very wide exports
   - cap width and target a feed-safe size (for example 1080 x 1350 or similar)
3. Upload image after successful FIT activity creation.
4. Keep this step best-effort and non-blocking:
   - FIT upload success remains success even if image upload fails.
5. Add tests for:
   - image render sizing policy
   - image upload call sequencing (activity first, image second)
   - failure isolation (image failure does not mark ride sync failed)

---

## Testing Strategy

- Unit tests:
  - settings serialization for new flag
  - keyring token store behavior
  - OAuth callback parsing and state validation
  - sync service decision logic
- Controller tests:
  - auto-sync enabled + connected -> upload enqueued
  - auto-sync disabled -> no upload
  - manual `Sync now` enqueues selected FIT file
  - upload failure -> local workout save still succeeds
  - duplicate upload attempt is handled as idempotent success
- Manual QA:
  - first-time connect
  - reconnect after token expiration (refresh path)
  - disconnect and reconnect
  - app restart with existing keyring tokens
  - final phase: verify feed preview readability for uploaded chart images on desktop and mobile

---

## Acceptance Criteria

- User can connect Strava from Settings without manual code copy/paste.
- Auto-sync checkbox appears and persists after authorization.
- User can manually choose a FIT file and sync it from the Settings screen.
- Completed rides upload automatically when auto-sync is enabled.
- Tokens/secrets are never written to plaintext files or logs.
- If Strava upload fails, workout is still recorded locally and user sees a non-blocking error.
- Duplicate uploads are prevented/handled idempotently and surfaced clearly to the user.
- Duplicate prevention is based on local successful-upload records (no Strava fetch-based reconciliation).
- Final phase: uploaded activities include a readable full-workout plot image that is not excessively wide in feed previews.

---

## Open Questions

- None currently.
