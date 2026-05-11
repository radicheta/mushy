#!/usr/bin/env bats
# Bats tests for scripts/signal/post-rebuild-trust-check.sh
# Mocking strategy: env-var test seams in the script
#   _TRUST_CHECK_FIXTURE — path to a JSON file used as the GET /v1/identities response
#   _TRUST_CHECK_PUT_LOG — path to a file where the script appends each PUT recipient (instead of HTTP)

setup() {
  SCRIPT="${BATS_TEST_DIRNAME}/../post-rebuild-trust-check.sh"
  FIX="${BATS_TEST_DIRNAME}/fixtures"

  # Test baseline matches "clean" + "stale" fixtures (same bot fingerprint)
  export _BASELINE_DIR="$(mktemp -d)"
  cat > "$_BASELINE_DIR/known-good.json" <<'JSON'
{
  "bot_number_placeholder": "+15550000000",
  "bot_fingerprint": "aa bb cc dd ee ff 00 11 22 33 44 55 66 77 88 99 aa bb cc dd ee ff 00 11 22 33 44 55 66 77 88 99",
  "captured_at": "2026-05-11T00:00:00Z",
  "source": "test baseline",
  "fingerprint_format": "signal-cli /v1/identities .fingerprint field"
}
JSON

  export SIGNAL_SENDER="+15550000001"
  export KNOWN_GOOD_PATH="$_BASELINE_DIR/known-good.json"
  export PUT_LOG="$_BASELINE_DIR/puts.log"
  : > "$PUT_LOG"
  export _TRUST_CHECK_PUT_LOG="$PUT_LOG"
}

teardown() {
  rm -rf "$_BASELINE_DIR"
}

@test "clean: matching fingerprint + all recipients accepted → verdict=ok, no PUT calls" {
  export _TRUST_CHECK_FIXTURE="$FIX/identities-clean.json"
  run "$SCRIPT"
  [ "$status" -eq 0 ]
  echo "$output" | grep -q '"verdict":"ok"'
  echo "$output" | grep -q '"recipients_checked":"2"'
  [ ! -s "$PUT_LOG" ]
}

@test "stale: matching fingerprint but one recipient UNTRUSTED → verdict=recovered + PUT issued" {
  # Use a mutable fixture so re-fetch (after recovery) returns clean
  cp "$FIX/identities-stale.json" "$_BASELINE_DIR/live.json"
  # After PUT, simulate re-fetch returning the clean version
  cat > "$_BASELINE_DIR/swap.sh" <<EOF
cp "$FIX/identities-clean.json" "$_BASELINE_DIR/live.json"
EOF
  chmod +x "$_BASELINE_DIR/swap.sh"

  # PUT seam: when invoked, swap the fixture to clean (so step 7 re-fetch sees recovery worked)
  export _TRUST_CHECK_PUT_LOG="$_BASELINE_DIR/puts.log"
  export _TRUST_CHECK_FIXTURE="$_BASELINE_DIR/live.json"

  # Wrap PUT seam: tee the recipient AND run swap
  # Bats can't easily intercept the helper, so use a wrapper script + override the seam
  cat > "$_BASELINE_DIR/wrapper-script.sh" <<EOF
#!/usr/bin/env bash
# Custom seam: log PUT recipient AND swap fixture to clean for the re-fetch
echo "\$1" >> "$_BASELINE_DIR/puts.log"
cp "$FIX/identities-clean.json" "$_BASELINE_DIR/live.json"
EOF
  chmod +x "$_BASELINE_DIR/wrapper-script.sh"

  # Override _trust_recipient via env-driven side-effect: easier to monkey-patch via copying script
  cp "$SCRIPT" "$_BASELINE_DIR/patched.sh"
  # Replace the _trust_recipient body to invoke our wrapper
  sed -i "s|printf '%s\\\\n' \"\$recipient\" >> \"\$_TRUST_CHECK_PUT_LOG\"|\"$_BASELINE_DIR/wrapper-script.sh\" \"\$recipient\"|" "$_BASELINE_DIR/patched.sh"

  run "$_BASELINE_DIR/patched.sh"
  [ "$status" -eq 0 ]
  echo "$output" | grep -q '"verdict":"recovered"'
  echo "$output" | grep -q '"recipients_recovered":"1"'
  # PUT recipient logged
  grep -q '+15550000002' "$_BASELINE_DIR/puts.log"
}

@test "hard_mismatch: bot fingerprint differs from baseline → exit 1, verdict=hard_mismatch, no PUTs" {
  export SIGNAL_SENDER="+15550000001"
  export _TRUST_CHECK_FIXTURE="$FIX/identities-mismatch.json"
  run "$SCRIPT"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q '"verdict":"hard_mismatch"'
  echo "$output" | grep -q '"expected_fp":"aabbccdd"'
  echo "$output" | grep -q '"actual_fp":"ffffffff"'
  [ ! -s "$PUT_LOG" ]
}

@test "signal_cli_unreachable: fetch returns nothing → exit 2, verdict=signal_cli_unreachable" {
  export _TRUST_CHECK_FIXTURE="/dev/null/does-not-exist"
  run "$SCRIPT"
  [ "$status" -eq 2 ]
  echo "$output" | grep -q '"verdict":"signal_cli_unreachable"'
}

@test "baseline_missing: known-good file unreadable → exit 3, verdict=baseline_missing" {
  export KNOWN_GOOD_PATH="$_BASELINE_DIR/does-not-exist.json"
  export _TRUST_CHECK_FIXTURE="$FIX/identities-clean.json"
  run "$SCRIPT"
  [ "$status" -eq 3 ]
  echo "$output" | grep -q '"verdict":"baseline_missing"'
}
