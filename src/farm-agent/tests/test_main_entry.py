"""
tests/test_main_entry.py -- MUSHY-106: a failed boot must exit the process.

The regression being guarded: on 2026-08-23 boot raised PoolTimeout and the
process stayed alive anyway, so `restart: unless-stopped` never fired and the
container sat Up with no farmer-facing agent.
"""

import farm_agent.__main__ as entry


def test_boot_failure_exits_nonzero():
    """A boot exception must reach the handler and exit non-zero."""
    exits: list[int] = []

    async def boom():
        raise RuntimeError("the database system is starting up")

    entry.run_until_dead(coro_fn=boom, exit_fn=exits.append)

    assert exits == [1], "a failed boot must exit(1) so Docker restarts it"


def test_clean_return_does_not_exit():
    """Normal shutdown (main returns) must not be turned into a failure exit."""
    exits: list[int] = []

    async def clean():
        return None

    entry.run_until_dead(coro_fn=clean, exit_fn=exits.append)

    assert exits == []


def test_importing_entry_module_does_not_boot():
    """Importing the module must not start the daemon.

    The previous version called asyncio.run(main()) at module scope, so any
    import of farm_agent.__main__ booted a second agent -- which on the shared
    Signal account is destructive (receive consumes messages).
    """
    assert hasattr(entry, "run_until_dead")
