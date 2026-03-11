# Task 13 Manual Hotkey Checklist

Run on Workout tab with focus in the main workout area:

1. Press `T` repeatedly:
- Expected: mode cycles `ERG -> Resistance -> Hybrid -> ERG`.

2. Press `1`:
- Expected: interval extend request emits `+60s` in workout/free-ride mode.
- Expected: interval extend request emits `+10kJ` in kJ mode.

3. Press `5`:
- Expected: interval extend request emits `+300s` in workout/free-ride mode.
- Expected: interval extend request emits `+50kJ` in kJ mode.

4. Press `Tab`:
- Expected: skip-interval request is emitted once per key press.

5. Press arrow keys:
- `Up`: jog request `+1`
- `Down`: jog request `-1`
- `Right`: jog request `+5`
- `Left`: jog request `-5`

6. Press `Space` twice:
- Expected: first press triggers pause action.
- Expected: second press triggers resume action.

7. Focus a text input (for example a `QLineEdit`) and type `T`, `1`, `5`, `Space`, `Tab`, arrow keys:
- Expected: text input receives typing/navigation.
- Expected: workout hotkey actions are not triggered while text input has focus.
