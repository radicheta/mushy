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


def test_deploy_reports_unit_drift():
    """deploy.sh installs no systemd units, so it must at least SAY so.

    Editing scripts/pi-deploy/*.service and deploying otherwise reports
    success while changing nothing on the Pi -- a silent no-op.
    """
    text = code('deploy.sh')
    assert 'DRIFTED' in text and '/etc/systemd/system/' in text, \
        'deploy.sh does not check the repo unit files against the live ones'


if __name__ == '__main__':
    test_no_git_pull()
    test_syncs_and_guards_dirty_tree()
    test_deploy_reports_unit_drift()
    print('OK: deploy path syncs to the branch and guards a dirty tree')
