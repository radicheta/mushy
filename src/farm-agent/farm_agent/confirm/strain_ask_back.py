"""
confirm/strain_ask_back.py -- Strain ask-back template, reply parser, and resolver.

Port of:
  src/agents/alerter/src/confirm/strain-ask-back.js
  src/agents/alerter/src/farmos/strain-resolver.js

Provides:
  CURATED_14           -- default curated-14 strain code list constant
  resolve_strain       -- exact-match resolver; NEVER auto-remaps (T-61-09)
  nearest_known        -- Levenshtein display-only suggestion
  render_strain_ask_back  -- ASCII farmer-facing ask-back message
  parse_strain_ask_back_reply -- four-path reply router

T-61-09: nearest_known() is DISPLAY ONLY. Unknown codes always go through the farmer
ask-back loop. The POY-as-KOY silent-misattribution bug was caused by exactly this
class of silent fuzzy remapping.

ASCII-only output: no em-dashes (use --), no emoji.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Curated-14 default
# ---------------------------------------------------------------------------

CURATED_14: list[str] = [
    "SHI", "SH2", "KOY", "MAI", "MALI", "KOS", "DT",
    "CAS", "CAZ", "WIN", "ALM", "MOR", "BP", "LIMA",
]

# ---------------------------------------------------------------------------
# Reply parser constants
# ---------------------------------------------------------------------------

CONFIRM_SET: set[str] = {"yes", "y", "ok", "si", "confirm", "new"}
CODE_RE: re.Pattern[str] = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,3}$")


# ---------------------------------------------------------------------------
# Levenshtein DP (verbatim port of strain-resolver.js nearestKnown DP)
# ---------------------------------------------------------------------------


def levenshtein(a: str, b: str) -> int:
    """Standard Levenshtein edit distance (DP).

    Port of strain-resolver.js levenshtein(a, b) -- no external dependency.
    """
    m, n = len(a), len(b)
    dp: list[list[int]] = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j - 1], dp[i - 1][j], dp[i][j - 1])
    return dp[m][n]


def nearest_known(code: str, curated_set: list[str]) -> str | None:
    """Return the nearest curated code by Levenshtein distance (display-only).

    Tie-break: first element in curated_set wins (list order).
    Returns None when curated_set is empty.

    DISPLAY ONLY -- never used for auto-remap (T-61-09 / Pitfall 7).
    """
    if not curated_set:
        return None
    best: str | None = None
    best_dist: int = 99999
    for candidate in curated_set:
        d = levenshtein(code, candidate)
        if d < best_dist:
            best_dist = d
            best = candidate
    return best


def resolve_strain(code: object, curated_set: list[str]) -> dict:
    """Resolve a raw strain code against the curated set.

    Port of strain-resolver.js resolveStrain(code, curatedSet).

    Returns:
      {known: True, code: norm}                   -- exact match
      {known: False, code: norm, nearest: str|None} -- unknown (nearest for display)
      {known: False, code: None}                   -- None / non-string / empty input

    EXACT-MATCH only. nearest is DISPLAY ONLY -- never auto-remap (T-61-09).
    """
    if code is None or not isinstance(code, str):
        return {"known": False, "code": None}
    norm = code.upper().strip()
    if not norm:
        return {"known": False, "code": None}
    if curated_set and norm in curated_set:
        return {"known": True, "code": norm}
    result: dict = {"known": False, "code": norm}
    if curated_set:
        result["nearest"] = nearest_known(norm, curated_set)
    return result


# ---------------------------------------------------------------------------
# Render template
# ---------------------------------------------------------------------------


def render_strain_ask_back(seen_code: str, nearest: str | None) -> str:
    """Render the farmer-facing strain ask-back message.

    Port of strain-ask-back.js renderStrainAskBack(seenCode, nearest).

    ASCII-only, no em-dashes (use --), no emoji.

    With nearest (3 lines):
      Saw strain '{CODE}' -- not in the active list.
      New strain, or did you mean {NEAREST}?
      Reply YES to add '{CODE}' as a new strain, or reply {NEAREST} (or "no, {NEAREST}") to use the existing one.

    Without nearest (2 lines):
      Saw strain '{CODE}' -- not in the active list.
      New strain? Reply YES to add it, or reply the correct strain code to remap.
    """
    code = str(seen_code or "").upper().strip()
    if nearest:
        n = str(nearest).upper().strip()
        return "\n".join([
            f"Saw strain '{code}' -- not in the active list.",
            f"New strain, or did you mean {n}?",
            f"Reply YES to add '{code}' as a new strain, or reply {n} (or \"no, {n}\") to use the existing one.",
        ])
    return "\n".join([
        f"Saw strain '{code}' -- not in the active list.",
        "New strain? Reply YES to add it, or reply the correct strain code to remap.",
    ])


# ---------------------------------------------------------------------------
# Reply parser
# ---------------------------------------------------------------------------


def parse_strain_ask_back_reply(text: str) -> dict:
    """Parse a farmer reply to a strain ask-back message.

    Port of strain-ask-back.js parseStrainAskBackReply(text).

    Four routing paths:
      1. firstToken in CONFIRM_SET       -> {kind: 'confirm_new'}
      2. firstToken == 'no' + rest CODE  -> {kind: 'correction', code: rest.upper()}
      3. bare token matches CODE_RE      -> {kind: 'correction', code: token.upper()}
      4. anything else                   -> {kind: 'unknown'}
    """
    if not text or not text.strip():
        return {"kind": "unknown"}

    tokens = text.strip().split()
    first = tokens[0].lower().strip(",")  # strip trailing comma for "no,"

    # Path 1: CONFIRM_SET
    if first in CONFIRM_SET:
        return {"kind": "confirm_new"}

    # Path 2: "no" + rest -- matches Node: extract FULL remainder after "no" token,
    # strip leading whitespace/commas, then test CODE_RE against the ENTIRE rest.
    # "no KOY please" -> rest="KOY please" -> CODE_RE fails (space) -> unknown.
    # "no KOY" / "no, KOY" -> rest="KOY" -> CODE_RE passes -> correction:KOY.
    if first == "no":
        trimmed = text.strip()
        rest = trimmed[len(tokens[0]):].lstrip(" ,").strip()
        if rest and CODE_RE.match(rest):
            return {"kind": "correction", "code": rest.upper()}
        return {"kind": "unknown"}

    # Path 3: bare token -- match Node: test CODE_RE against the FULL trimmed string.
    # Multi-word strings (e.g. "KOY extra") fail CODE_RE because of the space + $-anchor.
    if CODE_RE.match(text.strip()):
        return {"kind": "correction", "code": text.strip().upper()}

    # Path 4: unknown
    return {"kind": "unknown"}
