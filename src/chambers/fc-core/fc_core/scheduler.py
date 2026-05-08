"""Phase 30 — pure-Python scheduler helpers.

Used by `fc_controller` to evaluate a JSON-encoded `schedule_windows` list and
decide which mode should be active right now. Kept pure (no `rclpy` import) so
unit tests run with bare pytest and so the helpers can be exercised in a REPL
without bringing up a node.

See:
- .planning/phases/30-time-of-day-mode-scheduling/30-CONTEXT.md
  (D-01 schema, D-02 wraparound + half-open, D-03 validation rules,
   D-08 evaluation algorithm, D-19 transition log format).
- .planning/phases/30-time-of-day-mode-scheduling/30-01-PLAN.md (Task 1).

Schema (D-01/D-02):

    schedule_windows = '[{"start":"HH:MM","end":"HH:MM","mode":"<name>"}, ...]'

* Times are local (fc1 system TZ); half-open `[start, end)`.
* Wraparound supported: when `end < start` the window straddles midnight.
* Empty array = scheduling disabled (SCHED-03 backward compat).
* Validation rejects malformed JSON, missing keys, bad HH:MM, unknown modes;
  the controller's `on_set_parameters_callback` retains the old value on reject.
* Evaluation: gap → keep current mode; overlap → last-defined wins.
"""
import json
import re

_HHMM_RE = re.compile(r'^([01][0-9]|2[0-3]):[0-5][0-9]$')


def parse_schedule(json_str):
    """Parse a JSON-encoded schedule string into a list of dicts.

    Raises:
        ValueError: malformed JSON or non-array top-level value.
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(
            f'schedule_windows: invalid JSON: {e.msg}'
        ) from e
    if not isinstance(data, list):
        raise ValueError('schedule_windows: must be a JSON array')
    return data


def validate_window(window, declared_modes):
    """Validate a single window dict against declared mode names.

    Raises:
        ValueError: missing keys, bad HH:MM, unknown mode.
    """
    if not isinstance(window, dict):
        raise ValueError(f'schedule window must be an object (got {window!r})')
    required = {'start', 'end', 'mode'}
    missing = sorted(required - set(window.keys()))
    if missing:
        raise ValueError(
            f'schedule window missing key(s) {missing} '
            f'(need start, end, mode)'
        )
    for key in ('start', 'end'):
        val = window[key]
        if not (isinstance(val, str) and _HHMM_RE.fullmatch(val)):
            raise ValueError(
                f'schedule window {key} must be HH:MM '
                f'(got {val!r})'
            )
    if window['mode'] not in declared_modes:
        raise ValueError(
            f'schedule window mode {window["mode"]!r} not in declared modes '
            f'{sorted(declared_modes)}'
        )


def _hhmm_to_min(hhmm):
    """Convert 'HH:MM' to minutes-since-midnight (int).

    Special-case: '24:00' → 1440 so an "end of day" window can be expressed as
    `{"start":"00:00","end":"24:00",...}` (full-day coverage).
    """
    if hhmm == '24:00':
        return 24 * 60
    if not _HHMM_RE.fullmatch(hhmm):
        raise ValueError(f'invalid HH:MM: {hhmm!r}')
    h, m = hhmm.split(':')
    return int(h) * 60 + int(m)


def compute_desired_mode(now_hhmm, windows, current_mode):
    """Resolve the active window for the given local time.

    Returns:
        (desired_mode, matched_window) where matched_window is the dict that
        matched, or None on a gap (in which case desired_mode == current_mode).

    Behavior (D-08):
      * Empty list → (current_mode, None).
      * Half-open [start, end). Wraparound: if end<start, active when
        now>=start OR now<end.
      * Degenerate start==end window: never active (zero-length).
      * Overlap: last-defined window wins (iterate, keep last match).
      * Gap (no window matches): keep current mode unchanged.
    """
    if not windows:
        return (current_mode, None)
    # Treat '24:00' end as 1440 so a full-day window {00:00, 24:00} matches.
    now_min = _hhmm_to_min(now_hhmm)
    last_match = None
    for w in windows:
        start_min = _hhmm_to_min(w['start'])
        end_min = _hhmm_to_min(w['end'])
        if start_min == end_min:
            active = False
        elif start_min < end_min:
            active = (start_min <= now_min < end_min)
        else:
            # wraparound — window straddles midnight
            active = (now_min >= start_min) or (now_min < end_min)
        if active:
            last_match = w
    if last_match is None:
        return (current_mode, None)
    return (last_match['mode'], last_match)
