# Phase 51 Wave 0 — Dev farmOS notes round-trip probe

**Date:** 2026-05-24
**Target:** dev farmOS at `http://10.68.155.50:18080` (per
[[reference_farmos_dev_vs_prod_on_elder_plops]])
**Probe asset:** `09987253-bfec-4be5-8b43-4e731b1e1070` (name `SHI-260425-1`,
non-load-bearing test asset on dev)
**Verdict:** PASS — `notes.value` PATCH→GET round-trip is byte-identical for
the `\n---\n` separator. Plan 02 may safely encode `\n---\n` as the dedup
separator in the merge logic.

## What was probed

The locked dedup rule for the `notes` field (CONTEXT.md §"Notes-field
representation") splits the existing value on the literal `\n---\n`
three-byte separator (newline / triple-hyphen / newline), normalizes each
entry by trim, dedups by exact-string equality, and rejoins with the same
separator. The correctness of this rule depends on Drupal's text-field
storage layer not normalizing line endings, trimming whitespace, or
otherwise mutating the raw bytes on PATCH→storage→GET.

This probe writes a known three-entry payload separated by `\n---\n`,
re-fetches the asset, and byte-compares the round-tripped value to the input.

## Method

1. Auth as `mushy-bot` against dev (`mushy-bot` exists on both dev and prod;
   the prod password in `.env` works against the dev endpoint).
2. GET the probe asset to capture the pre-state (notes was `test fungi
   asset`, revision_id 32).
3. PATCH `attributes.notes` to literal bytes
   `entry_A\n---\nentry_B\n---\nentry_C`
   (31 bytes total: 7 + 1 + 3 + 1 + 7 + 1 + 3 + 1 + 7).
4. GET back, hexdump compare.
5. Restore the asset's notes to its original value (`test fungi asset`,
   leaves revision_id incremented by 2 — pre-existing test asset, not
   load-bearing for farmer workflows).

## Commands

```bash
DEV_URL="http://10.68.155.50:18080"
AUTH=$(curl -sS -i -X POST "$DEV_URL/user/login?_format=json" \
  -H 'Content-Type: application/json' \
  -d '{"name":"mushy-bot","pass":"<from .env>"}')
COOKIE=$(echo "$AUTH" | grep -i '^Set-Cookie:' | head -1 | sed 's/^Set-Cookie: //I' | cut -d';' -f1)
CSRF=$(echo "$AUTH" | tail -1 | python3 -c "import json,sys; print(json.load(sys.stdin)['csrf_token'])")

UUID="09987253-bfec-4be5-8b43-4e731b1e1070"

# PATCH — JSON body built via python to preserve real \n bytes in notes.value
PAYLOAD=$(python3 -c "
import json
payload = {'data': {'type':'asset--fungi', 'id':'$UUID', 'attributes': {'notes': {'value':'entry_A\n---\nentry_B\n---\nentry_C', 'format':'plain_text'}}}}
print(json.dumps(payload))
")
curl -sS -X PATCH "$DEV_URL/api/asset/fungi/$UUID" \
  -H "Cookie: $COOKIE" -H "X-CSRF-Token: $CSRF" \
  -H "Content-Type: application/vnd.api+json" \
  -H "Accept: application/vnd.api+json" \
  --data-raw "$PAYLOAD"

# GET back
curl -sS "$DEV_URL/api/asset/fungi/$UUID" \
  -H "Cookie: $COOKIE" -H "Accept: application/vnd.api+json"
```

## Raw results

**Input hexdump (31 bytes):**

```
00000000: 656e 7472 795f 410a 2d2d 2d0a 656e 7472  entry_A.---.entr
00000010: 795f 420a 2d2d 2d0a 656e 7472 795f 43    y_B.---.entry_C
```

**PATCH 200 response notes.value (from response body):**

```
hex: 656e7472795f410a2d2d2d0a656e7472795f420a2d2d2d0a656e7472795f43
str: 'entry_A\n---\nentry_B\n---\nentry_C'
```

**GET-after notes.value:**

```
hex: 656e7472795f410a2d2d2d0a656e7472795f420a2d2d2d0a656e7472795f43
str: 'entry_A\n---\nentry_B\n---\nentry_C'
```

**Python byte-equality check:**
`v == 'entry_A\n---\nentry_B\n---\nentry_C'  ⇒  True`

## Conclusion

The literal three-byte sequence `\n---\n` (newline / triple-hyphen /
newline) survives a PATCH→storage→GET cycle on farmOS Drupal 10 with
`format: 'plain_text'` byte-identical. No normalization (no CRLF
conversion, no trim, no double-newline collapse) was observed.

**Plan 02 can encode the dedup separator as the string literal**
`\n---\n` **with no fallback or normalization-on-read.** The locked
dedup rule in CONTEXT.md §"Notes-field representation" is correct as
written.

## Caveats / follow-ups

- This probe used a single asset on a single Drupal/farmOS version. If the
  farmOS team ever migrates to a different text format (e.g. `restricted_html`,
  `basic_html`) the round-trip fidelity guarantee no longer holds — Drupal's
  filter chain may strip or escape. The dedup rule must remain coupled to the
  `format: 'plain_text'` assumption.
- The probe asset's revision_id incremented by 2 (one for the probe PATCH,
  one for the restore). Acceptable on `SHI-260425-1` which is a known
  test asset; would not run this against farmer-tracked stubs.
