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


def build_multi_strain_reask(codes: list[str]) -> str:
    """Tell the farmer a correction could not be attributed (MUSHY-108).

    The reply parser understands YES or a bare code -- it has no way to say
    "change POY, leave KOY" -- so a session carrying more than one strain
    cannot route a single-code correction. Say that plainly instead of picking
    one and acking a change that did not happen.

    ASCII-only, no em-dashes (use --), no emoji. Only offers YES, because YES
    is the only other thing the parser actually accepts here.
    """
    listed = ", ".join(str(c).upper().strip() for c in (codes or []))
    return "\n".join([
        f"This session has more than one strain: {listed}.",
        "One code cannot tell me which to change, so I changed nothing.",
        "Reply YES to keep them as read.",
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


# ---------------------------------------------------------------------------
# Curated-set resolution + draft code collection (MUSHY-109)
# ---------------------------------------------------------------------------


def get_curated_set(config: object) -> list[str]:
    """Return the curated strain code list from config, falling back to CURATED_14.

    `strains` is the attribute the tenant loader actually populates
    (tenancy/tenant.py:240, fed from strains.yaml STRAIN_CODES); the two
    upper/lower spellings are kept for configs that pass the raw key through.
    """
    raw = (
        getattr(config, "strains", None)
        or getattr(config, "STRAIN_CODES", None)
        or getattr(config, "strain_codes", None)
    )
    if raw and isinstance(raw, (list, tuple)):
        return list(raw)
    return CURATED_14


def collect_strain_codes(draft: object) -> list[str]:
    """Collect distinct strain codes from any draft shape.

    Port of pipeline.js collectStrainCodes(draft).

    Flat shapes (SeedingLog / observation / harvest): top-level
    species_code / species / strain / fungi_type.
    seeding_session: per-group groups[].species.value -- the ONLY place codes
    live on that shape.

    Mirrors the commit-side read precedence, so the gate sees exactly the codes
    a commit would send to farmOS.
    """
    codes: list[str] = []
    if not isinstance(draft, dict):
        return codes
    flat = (
        draft.get("species_code")
        or draft.get("species")
        or draft.get("strain")
        or draft.get("fungi_type")
    )
    if isinstance(flat, str) and flat.strip():
        codes.append(flat.upper().strip())
    groups = draft.get("groups")
    if isinstance(groups, list):
        for g in groups:
            v = (g or {}).get("species", {}) if isinstance(g, dict) else None
            v = v.get("value") if isinstance(v, dict) else None
            if isinstance(v, str) and v.strip():
                codes.append(v.upper().strip())
    return list(dict.fromkeys(codes))  # DISTINCT, insertion-ordered: one batched ask


def apply_strain_correction(draft: object, new_code: str) -> dict:
    """Rewrite every place a strain code lives on the draft (MUSHY-108).

    Flat shapes carry the code at the top level; a seeding_session carries it
    ONLY at groups[].species.value, and the commit path reads it from there --
    so writing species_code on a grouped draft is structurally inert, and the
    stale per-group code is what reaches farmOS.

    A correction reply names one code but not which of several it replaces, so
    a grouped draft carrying more than one distinct strain is genuinely
    ambiguous. Rather than guess, say so and let the caller keep the draft
    held: acking a correction that did not take effect is the silent
    misattribution this whole loop exists to prevent.

    Returns:
      {"ok": True, "draft": dict, "groups_changed": int}
      {"ok": False, "reason": "multi_strain_session", "codes": [str, ...]}
    """
    out = dict(draft or {}) if isinstance(draft, dict) else {}
    groups = out.get("groups")
    has_groups = isinstance(groups, list) and any(isinstance(g, dict) for g in groups)

    if has_groups:
        codes = collect_strain_codes(out)
        if len(codes) > 1:
            return {"ok": False, "reason": "multi_strain_session", "codes": codes}
        new_groups = []
        changed = 0
        for g in groups:
            if not isinstance(g, dict):
                new_groups.append(g)
                continue
            species = g.get("species")
            if isinstance(species, dict) and isinstance(species.get("value"), str):
                g = {**g, "species": {**species, "value": new_code}}
                changed += 1
            new_groups.append(g)
        out["groups"] = new_groups
    else:
        changed = 0

    # Top level too. species_code wins the read precedence in both
    # collect_strain_codes and the commit path, so it is what must be right;
    # the other spellings are rewritten only so no stale code is left behind
    # to contradict it on a receipt.
    for key in ("species", "strain", "fungi_type"):
        if isinstance(out.get(key), str):
            out[key] = new_code
    if not has_groups or isinstance(out.get("species_code"), str):
        out["species_code"] = new_code

    return {"ok": True, "draft": out, "groups_changed": changed}
