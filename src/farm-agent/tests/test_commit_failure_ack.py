"""MUSHY-75: a commit failure names the real cause instead of blaming the farmer.

The terminal commit-outcome ack collapsed every failure into one sentence that
ends "Reply EDIT to fix it". A transport failure -- farmOS down, DNS broken,
connection refused -- was therefore reported to the farmer as though their entry
was malformed, and invited them to go hunting for a mistake in an entry that was
correct.

The incident that surfaced it (2026-08-16, draft 84d75743ae): the farmer's inoc
session of 4 blocks failed three times with `fetch failed` because prod farmOS
had been returning 500 since the Aug 13 cold start. The farmer was told
"couldn't save it because data validation failed". Nothing was wrong with the
data.

The two cases need opposite responses:
  transport  -> "your entry is fine, nothing to fix"
  validation -> "your entry needs fixing"

`_is_transient` already carries the distinction; only the wording discarded it.

ASCII-only. No em-dashes (farmer-facing).
"""
from __future__ import annotations

import pytest

from farm_agent.farmos.commit_watchdog import build_failure_ack


def _has_edit_instruction(body: str) -> bool:
    return "EDIT" in body


class TestTransportFailure:
    """farmOS was unreachable. The entry is correct and must not be blamed."""

    def test_the_incident_this_ticket_was_filed_for(self):
        """`fetch failed` with no response is a dead server, not bad data."""
        body = build_failure_ack({"ok": False, "http_status": None, "reason": "fetch failed"})
        assert "unreachable" in body.lower()
        assert not _has_edit_instruction(body), (
            f"a transport failure must not ask the farmer to fix a correct entry: {body!r}"
        )

    def test_says_the_entry_is_fine(self):
        body = build_failure_ack({"ok": False, "http_status": None, "reason": "fetch failed"})
        assert "nothing to fix" in body.lower()

    def test_a_farmos_500_is_the_servers_fault_not_the_farmers(self):
        body = build_failure_ack({"ok": False, "http_status": 500, "reason": "internal error"})
        assert not _has_edit_instruction(body)
        assert "unreachable" in body.lower()

    @pytest.mark.parametrize("reason", ["timeout", "abort", "econnreset", "econnrefused"])
    def test_every_network_pattern_reads_as_transport(self, reason):
        body = build_failure_ack({"ok": False, "http_status": 400, "reason": reason})
        assert not _has_edit_instruction(body), f"{reason!r} is a network failure"

    def test_a_missing_result_is_transport(self):
        """No result at all means the request died before a response."""
        assert not _has_edit_instruction(build_failure_ack(None))

    def test_does_not_promise_a_retry_that_will_not_happen(self):
        """A parked draft is at the attempt cap and the watchdog never picks it
        up again, so promising an automatic retry would be a lie."""
        body = build_failure_ack({"ok": False, "http_status": None, "reason": "fetch failed"})
        assert "will be retried" not in body.lower()
        assert "try again" not in body.lower()


class TestValidationFailure:
    """farmOS answered and refused. The entry really does need fixing."""

    def test_still_asks_the_farmer_to_edit(self):
        body = build_failure_ack({"ok": False, "http_status": 422, "reason": "http_422"})
        assert _has_edit_instruction(body)

    def test_names_the_cause_in_words_the_farmer_can_act_on(self):
        """`observation_requires_target` is the single most common failure on
        prod and means nothing to a farmer."""
        body = build_failure_ack({"ok": False, "http_status": 422, "reason": "observation_requires_target"})
        assert "observation_requires_target" not in body
        assert "which bag" in body.lower() or "which block" in body.lower()

    def test_missing_source_block_is_translated_too(self):
        body = build_failure_ack({"ok": False, "http_status": 422, "reason": "missing_source_block"})
        assert "missing_source_block" not in body
        assert "source block" in body.lower()

    def test_an_unrecognised_reason_still_says_something_specific(self):
        """Fallback must not swallow the cause -- that was the original bug."""
        body = build_failure_ack({"ok": False, "http_status": 422, "reason": "some_new_code"})
        assert "some_new_code" in body, "an untranslated reason is still better than silence"
        assert _has_edit_instruction(body)


class TestBothPaths:
    @pytest.mark.parametrize("result", [
        {"ok": False, "http_status": None, "reason": "fetch failed"},
        {"ok": False, "http_status": 422, "reason": "observation_requires_target"},
        {"ok": False, "http_status": 422, "reason": "some_new_code"},
        None,
    ])
    def test_no_em_dashes_in_farmer_facing_text(self, result):
        """Repo convention: an em-dash is an LLM tell in a farmer-facing artifact."""
        body = build_failure_ack(result)
        assert "—" not in body and "--" not in body, f"em-dash in {body!r}"

    @pytest.mark.parametrize("result", [
        {"ok": False, "http_status": None, "reason": "fetch failed"},
        {"ok": False, "http_status": 422, "reason": "http_422"},
        None,
    ])
    def test_always_says_it_did_not_save(self, result):
        """The farmer was told "recorded" at YES time. Every one of these must
        correct that belief, whatever the cause."""
        assert "save" in build_failure_ack(result).lower()

    @pytest.mark.parametrize("result", [
        {"ok": False, "http_status": None, "reason": "fetch failed"},
        {"ok": False, "http_status": 422, "reason": "observation_requires_target"},
    ])
    def test_is_ascii(self, result):
        build_failure_ack(result).encode("ascii")


class TestLocalValidationIsNotATransportFailure:
    """MUSHY-126: the same lie, arriving from the other side.

    MUSHY-75 stopped a dead server being reported as bad data. But the fix keyed
    transport off `http_status is None`, and a handler that fails its own
    pre-flight check never makes an HTTP call, so it has no status either. Every
    one of those was then reported as "the server was unreachable. Nothing is
    wrong with your entry, so there is nothing to fix."

    Draft 91a9c622b3 (2026-08-29): a relocate onto a block farmOS did not have.
    The farmer was told there was nothing to fix, about an entry that could only
    be fixed by editing it.
    """

    def test_the_incident_this_ticket_was_filed_for(self):
        body = build_failure_ack({"ok": False, "http_status": None,
                                  "reason": "no_target_asset_for_activity"})
        assert "unreachable" not in body.lower(), (
            f"farmOS answered fine; the handler decided this locally: {body!r}"
        )
        assert _has_edit_instruction(body)

    def test_it_reaches_the_plain_words_table(self):
        """The translation already existed. The transient branch shadowed it."""
        body = build_failure_ack({"ok": False, "http_status": None,
                                  "reason": "no_target_asset_for_activity"})
        assert "which bag" in body.lower() or "which block" in body.lower()

    @pytest.mark.parametrize("reason", [
        "missing_strain", "missing_block_name", "fungi_type_not_found",
        "ambiguous_qr_seeding", "log_identity_mismatch",
    ])
    def test_every_locally_decided_reason_is_terminal(self, reason):
        """None of these are the network. All of them need the farmer."""
        body = build_failure_ack({"ok": False, "http_status": None, "reason": reason})
        assert "unreachable" not in body.lower(), f"{reason!r} is not a dead server"

    @pytest.mark.parametrize("reason", ["http_network", "fetch failed", "timeout"])
    def test_real_transport_still_reads_as_transport(self, reason):
        """The formatter that names a dead transport is "http_" + status-or-network.
        Those must keep the MUSHY-75 wording."""
        body = build_failure_ack({"ok": False, "http_status": None, "reason": reason})
        assert "unreachable" in body.lower()
        assert not _has_edit_instruction(body)
