"""MUSHY-117: the Pi deploy path must SYNC to fc1/prod, never merge into it.

`git pull` only works while the branch fast-forwards. fc1/prod gets rewritten
(main->prod syncs force-push it), and a pull is then a non-fast-forward merge
that conflicts in fc_controller.py, leaving the Pi on a conflicted tree still
running the old build -- silently, because the chamber stays controlled.

Run: python3 scripts/test_pi_deploy_sync.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent / 'pi-deploy'
FILES = ['deploy.sh', 'fc-update.service']


def code(name):
    """File contents minus comment lines -- the comments discuss `git pull`."""
    lines = (HERE / name).read_text().splitlines()
    return '\n'.join(ln for ln in lines if not ln.lstrip().startswith('#'))


def test_no_git_pull():
    for name in FILES:
        assert 'git pull' not in code(name), (
            f'{name} uses `git pull` -- it will conflict after a force-push. '
            'Use `git fetch` + `git reset --hard origin/<branch>` instead.')


def test_syncs_and_guards_dirty_tree():
    for name in FILES:
        text = code(name)
        assert 'git reset' in text and '--hard' in text, \
            f'{name} does not reset to the branch'
        assert 'git status --porcelain' in text, \
            f'{name} resets --hard without checking for local changes first'


def test_deploy_reconciles_units():
    """deploy.sh must INSTALL the repo's units, not just report on them.

    MUSHY-119: it used to deploy code but not units, so editing
    scripts/pi-deploy/*.service and deploying reported success while changing
    nothing on the Pi -- you found out at the next boot. fc-system-sync.service
    sat 36 lines stale that way.
    """
    text = code('deploy.sh')
    assert '/etc/systemd/system/' in text, \
        'deploy.sh does not look at the live unit files at all'
    assert 'install -m 644' in text, \
        'deploy.sh checks unit drift but never installs -- back to a silent no-op'
    assert 'daemon-reload' in text, \
        'deploy.sh installs units without telling systemd to re-read them'
    assert '.bak-' in text, \
        'deploy.sh overwrites a live unit with no backup on the Pi'


def test_deploy_never_restarts_fc_system_sync():
    """Installing the unit file is safe; RUNNING it is not.

    fc-system-sync stages netplan and /etc/cyclonedds.xml and can call
    `netplan generate` / `wpa_cli reconfigure` -- on the box whose only link is
    wifi + wg0. A code deploy must never trigger that; it takes effect at the
    next boot, under someone's supervision.
    """
    text = code('deploy.sh')
    for forbidden in ('restart fc-system-sync', 'start fc-system-sync'):
        assert forbidden not in text, \
            f'deploy.sh runs `{forbidden}` -- that reconfigures the network mid-deploy'


if __name__ == '__main__':
    test_no_git_pull()
    test_syncs_and_guards_dirty_tree()
    test_deploy_reconciles_units()
    test_deploy_never_restarts_fc_system_sync()
    print('OK: deploy path syncs to the branch, guards a dirty tree, reconciles units')
