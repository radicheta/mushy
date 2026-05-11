#!/usr/bin/env bash
# Phase 36 D-10: enforce signal-cli identity-trust integrity across alerter rebuilds.
# Three operational verdicts:
#   ok          — fingerprint matches known-good + all recipients in an accepted trust state
#   recovered   — fingerprint matches but stale-UNTRUSTED rows auto-re-trusted (rebuild-corruption case)
#   hard_mismatch — bot's own fingerprint != known-good; NEVER auto-trust (D-06), exit non-zero
# Plus two error verdicts:
#   signal_cli_unreachable — REST API down or timing out (exit 2)
#   baseline_missing       — known-good-identity.json not readable (exit 3)
#
# Wired as the alerter container's healthcheck. Exit non-zero marks the container unhealthy
# (alerter `restart: unless-stopped` does NOT restart on unhealthy — operator decides).

set -euo pipefail

: "${SIGNAL_API_URL:=http://signal-cli:8080}"
: "${SIGNAL_SENDER:?SIGNAL_SENDER (bot E.164) is required}"
: "${KNOWN_GOOD_PATH:=/opt/scripts/signal/known-good-identity.json}"

ACCEPTED_TRUST_LEVELS="TRUSTED_VERIFIED TRUSTED_UNVERIFIED"

_log() {
  # Emit a single JSON line. Args: verdict + key=value pairs.
  local verdict="$1"; shift
  local ts kv
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  kv=""
  for pair in "$@"; do
    local k="${pair%%=*}" v="${pair#*=}"
    # Escape backslash + double-quote in v
    v=${v//\\/\\\\}
    v=${v//\"/\\\"}
    kv="${kv},\"${k}\":\"${v}\""
  done
  printf '{"ts":"%s","script":"post-rebuild-trust-check","verdict":"%s"%s}\n' "$ts" "$verdict" "$kv"
}

_fetch_identities() {
  # Test seam: if _TRUST_CHECK_FIXTURE is set, cat that file instead of hitting HTTP.
  if [ -n "${_TRUST_CHECK_FIXTURE:-}" ]; then
    if [ -r "$_TRUST_CHECK_FIXTURE" ]; then
      cat "$_TRUST_CHECK_FIXTURE"
      return 0
    fi
    return 1
  fi
  curl -fsS -m 5 "${SIGNAL_API_URL}/v1/identities/${SIGNAL_SENDER}"
}

_trust_recipient() {
  # Test seam: if _TRUST_CHECK_PUT_LOG is set, append PUT call there instead of hitting HTTP.
  local recipient="$1"
  if [ -n "${_TRUST_CHECK_PUT_LOG:-}" ]; then
    printf '%s\n' "$recipient" >> "$_TRUST_CHECK_PUT_LOG"
    return 0
  fi
  curl -fsS -m 5 -X PUT \
    "${SIGNAL_API_URL}/v1/identities/${SIGNAL_SENDER}/trust/${recipient}?trust_all_known_keys=true" \
    > /dev/null
}

# 1. Load baseline
if [ ! -r "$KNOWN_GOOD_PATH" ]; then
  _log "baseline_missing" "path=${KNOWN_GOOD_PATH}"
  exit 3
fi
EXPECTED_FP=$(jq -r '.bot_fingerprint // empty' "$KNOWN_GOOD_PATH" 2>/dev/null || true)
if [ -z "$EXPECTED_FP" ]; then
  _log "baseline_missing" "path=${KNOWN_GOOD_PATH}" "reason=bot_fingerprint_empty"
  exit 3
fi

# 2. Fetch live identities
if ! IDENTITIES=$(_fetch_identities); then
  _log "signal_cli_unreachable" "endpoint=${SIGNAL_API_URL}"
  exit 2
fi

# 3. Validate it's a JSON array
if ! echo "$IDENTITIES" | jq -e 'type=="array"' > /dev/null 2>&1; then
  _log "signal_cli_unreachable" "endpoint=${SIGNAL_API_URL}" "reason=non_array_response"
  exit 2
fi

# 4. Locate bot's own identity
ACTUAL_FP=$(echo "$IDENTITIES" | jq -r --arg b "$SIGNAL_SENDER" '.[] | select(.number==$b) | .fingerprint' | head -1)
if [ -z "$ACTUAL_FP" ]; then
  _log "hard_mismatch" "reason=bot_identity_absent" "expected_fp=${EXPECTED_FP:0:8}"
  exit 1
fi

# 5. Compare fingerprints
EXPECTED_NORM=$(echo "$EXPECTED_FP" | tr -d ' :')
ACTUAL_NORM=$(echo "$ACTUAL_FP" | tr -d ' :')
if [ "$EXPECTED_NORM" != "$ACTUAL_NORM" ]; then
  _log "hard_mismatch" "expected_fp=${EXPECTED_NORM:0:8}" "actual_fp=${ACTUAL_NORM:0:8}"
  exit 1
fi

# 6. Walk recipients; auto-re-trust any UNTRUSTED rows (rebuild-corruption case)
RECOVERED=0
CHECKED=0
while IFS=$'\t' read -r number trust_level; do
  [ -z "$number" ] && continue
  [ "$number" = "$SIGNAL_SENDER" ] && continue
  CHECKED=$((CHECKED + 1))
  accepted=0
  for accepted_lvl in $ACCEPTED_TRUST_LEVELS; do
    if [ "$trust_level" = "$accepted_lvl" ]; then accepted=1; break; fi
  done
  if [ $accepted -eq 0 ]; then
    if ! _trust_recipient "$number"; then
      _log "recovery_failed" "recipient_idx=${CHECKED}" "trust_level=${trust_level}"
      exit 1
    fi
    RECOVERED=$((RECOVERED + 1))
  fi
done < <(echo "$IDENTITIES" | jq -r '.[] | [.number // "", .trust_level // ""] | @tsv')

# 7. If we recovered any, re-fetch to confirm the trust table actually clean now
if [ $RECOVERED -gt 0 ]; then
  if ! IDENTITIES=$(_fetch_identities); then
    _log "recovery_failed" "reason=refetch_failed" "recovered=${RECOVERED}"
    exit 1
  fi
  STILL_UNTRUSTED=$(echo "$IDENTITIES" | jq --arg b "$SIGNAL_SENDER" \
    '[.[] | select(.number != $b) | select(.trust_level != "TRUSTED_VERIFIED" and .trust_level != "TRUSTED_UNVERIFIED")] | length')
  if [ "$STILL_UNTRUSTED" -gt 0 ]; then
    _log "recovery_failed" "still_untrusted=${STILL_UNTRUSTED}" "recovered=${RECOVERED}"
    exit 1
  fi
  _log "recovered" "recipients_checked=${CHECKED}" "recipients_recovered=${RECOVERED}"
  exit 0
fi

_log "ok" "recipients_checked=${CHECKED}"
exit 0
