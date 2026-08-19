"""MUSHY-75: a transport-parked draft is retried once farmOS can prove it is safe.

A commit that fails on transport lands in commit_failed at the attempt cap and
the watchdog never looks at it again. Draft 1192a845a7 sat there for 17 days --
a confirmed 9-block seeding session that was simply absent from the farm record
until someone went looking.

The naive fix (reset the attempt count when farmOS is reachable) is wrong, and
the two real cases prove it: 84d75743ae had ALREADY been written by the Node
agent, so a blind requeue would have duplicated four blocks, while 1192a845a7
had not. Reachability does not distinguish them. Only farmOS does.

So the probe is an EXISTENCE check, and it doubles as the reachability check:
if the lookup cannot reach farmOS it is not a miss, and nothing is requeued.

Scope is deliberately narrow. A general "has this draft already been written"
is upsert-by-identity (Phase 51, separate milestone). Seeding drafts carry
explicit block names that ARE the identity, so those recover automatically;
anything else is left for a human rather than guessed at.

ASCII-only. No em-dashes.
"""
from __future__ import annotations

import pytest

from farm_agent.farmos.commit_recovery import (
    already_in_farmos,
    expected_block_names,
    recover_transport_parked,
)


def _session_row(names, draft_id="d1"):
    return {
        "id": draft_id,
        "log_type": "seeding_session",
        "draft_json": {
            "type": "seeding_session",
            "groups": [{"child_block_names": {"value": [n]}} for n in names],
        },
    }


class FakeClient:
    """Stands in for the farmOS client's find_asset_by_name behaviour."""

    def __init__(self, existing=(), unreachable=False):
        self.existing = set(existing)
        self.unreachable = unreachable
        self.looked_up: list[str] = []

    async def find(self, name):
        self.looked_up.append(name)
        if self.unreachable:
            return {"found": False, "error": "http_network"}
        return {"found": True, "asset_id": "a1"} if name in self.existing else {"found": False}


class FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.requeued: list[str] = []

    async def find_transport_parked(self, pool):
        return self.rows

    async def requeue_parked(self, pool, draft_id):
        self.requeued.append(draft_id)
        return {"ok": True, "rowcount": 1}


class TestExpectedBlockNames:
    def test_reads_every_child_across_groups(self):
        row = _session_row(["260802_KOS_1", "260802_DT_2"])
        assert expected_block_names(row) == ["260802_KOS_1", "260802_DT_2"]

    def test_single_seeding_uses_its_block_name(self):
        row = {"log_type": "seeding", "draft_json": {"type": "seeding", "block_name": "260425_SHI_1"}}
        assert expected_block_names(row) == ["260425_SHI_1"]

    def test_a_shape_with_no_stable_identity_yields_nothing(self):
        """An observation has no name that identifies it in farmOS, so it must
        not be auto-requeued -- that is Phase 51's problem, not this one's."""
        row = {"log_type": "observation", "draft_json": {"type": "observation", "state": "colonized"}}
        assert expected_block_names(row) == []

    def test_ignores_blank_and_non_string_entries(self):
        row = _session_row(["260802_KOS_1"])
        row["draft_json"]["groups"].append({"child_block_names": {"value": ["", "  ", None, 7]}})
        assert expected_block_names(row) == ["260802_KOS_1"]

    def test_survives_a_malformed_draft(self):
        assert expected_block_names({"log_type": "seeding_session", "draft_json": None}) == []
        assert expected_block_names({}) == []


class TestAlreadyInFarmos:
    @pytest.mark.asyncio
    async def test_absent_blocks_report_not_committed(self):
        c = FakeClient(existing=[])
        assert await already_in_farmos(c.find, ["260802_KOS_1"]) == {"ok": True, "exists": False}

    @pytest.mark.asyncio
    async def test_a_single_existing_block_is_enough_to_refuse(self):
        """84d75743ae's four blocks were already there. One hit must stop it."""
        c = FakeClient(existing=["260816_WIN_3"])
        got = await already_in_farmos(c.find, ["260816_DT_1", "260816_WIN_3"])
        assert got == {"ok": True, "exists": True}

    @pytest.mark.asyncio
    async def test_unreachable_farmos_is_not_a_miss(self):
        """The whole bug class: treating a dead server as 'nothing is there'."""
        c = FakeClient(unreachable=True)
        got = await already_in_farmos(c.find, ["260802_KOS_1"])
        assert got["ok"] is False
        assert "exists" not in got

    @pytest.mark.asyncio
    async def test_stops_looking_once_it_has_an_answer(self):
        c = FakeClient(existing=["A"])
        await already_in_farmos(c.find, ["A", "B", "C"])
        assert c.looked_up == ["A"], "no reason to keep querying after a hit"


class TestRecoverTransportParked:
    @pytest.mark.asyncio
    async def test_requeues_a_genuinely_lost_session(self):
        """The 1192a845a7 case: 9 blocks, none of them in farmOS."""
        db = FakeDb([_session_row(["260802_KOS_1", "260802_DT_2"], "lost")])
        c = FakeClient(existing=[])
        n = await recover_transport_parked(None, c.find, db, None)
        assert db.requeued == ["lost"]
        assert n == 1

    @pytest.mark.asyncio
    async def test_refuses_a_draft_whose_blocks_already_landed(self):
        """The 84d75743ae case. A blind requeue duplicates four blocks."""
        db = FakeDb([_session_row(["260816_DT_1"], "already")])
        c = FakeClient(existing=["260816_DT_1"])
        n = await recover_transport_parked(None, c.find, db, None)
        assert db.requeued == []
        assert n == 0

    @pytest.mark.asyncio
    async def test_requeues_nothing_while_farmos_is_still_down(self):
        db = FakeDb([_session_row(["260802_KOS_1"], "lost")])
        c = FakeClient(unreachable=True)
        assert await recover_transport_parked(None, c.find, db, None) == 0
        assert db.requeued == []

    @pytest.mark.asyncio
    async def test_gives_up_on_the_pass_once_farmos_looks_down(self):
        """No point probing 10 more drafts against a dead server."""
        db = FakeDb([_session_row(["A"], "one"), _session_row(["B"], "two")])
        c = FakeClient(unreachable=True)
        await recover_transport_parked(None, c.find, db, None)
        assert c.looked_up == ["A"], "should stop after the first unreachable probe"

    @pytest.mark.asyncio
    async def test_leaves_an_unidentifiable_shape_alone(self):
        db = FakeDb([{"id": "obs", "log_type": "observation", "draft_json": {"type": "observation"}}])
        c = FakeClient(existing=[])
        assert await recover_transport_parked(None, c.find, db, None) == 0
        assert db.requeued == []

    @pytest.mark.asyncio
    async def test_one_bad_draft_does_not_stop_the_others(self):
        db = FakeDb([
            {"id": "obs", "log_type": "observation", "draft_json": {"type": "observation"}},
            _session_row(["260802_KOS_1"], "lost"),
        ])
        c = FakeClient(existing=[])
        await recover_transport_parked(None, c.find, db, None)
        assert db.requeued == ["lost"]

    @pytest.mark.asyncio
    async def test_never_raises_on_a_broken_db(self):
        class Broken:
            async def find_transport_parked(self, pool):
                raise RuntimeError("db gone")
        assert await recover_transport_parked(None, FakeClient().find, Broken(), None) == 0
