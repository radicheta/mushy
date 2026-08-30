#!/usr/bin/env python3
"""Guard a fit report and push it: ros2 params on fc1 + fc_config.yaml commit (MUSHY-138).

  PYTHONPATH=src/chambers/fc-core .venv/bin/python scripts/self-tune/push-chamber-params.py reports/self-tune/2026-09-05.json
  ... --dry-run   prints what it would do, touches nothing

Exit 0 pushed, 3 refused (report says why), 1 error.
"""
import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'src' / 'chambers' / 'fc-core'))

from fc_core.sim.chamber_model import ChamberParams      # noqa: E402
from fc_core.sim.simc import guard                       # noqa: E402

YAML = REPO_ROOT / 'src' / 'chambers' / 'fc-core' / 'config' / 'fc_config.yaml'
ACCEPTED = REPO_ROOT / 'reports' / 'self-tune' / 'accepted.json'
NODE = '/fc_controller'


def yaml_value(key):
    m = re.search(rf'^(\s*){key}:\s*([0-9.eE+-]+)', YAML.read_text(), re.M)
    return float(m.group(2)) if m else None


def num(v):
    """Serialise so a double param never looks like an int.

    `%.6g` emits `4` for 4.0; a double-typed ROS param set from an int literal
    crashed fc_controller on reboot once already (decay_tau, 2026-06-28).
    """
    return repr(float(v))


def set_yaml(key, value, provenance):
    """Rewrite `key`'s value and replace any trailing comment with the report
    it came from -- the old comment describes a hand tune that no longer holds."""
    text, n = re.subn(rf'^(\s*{key}:\s*)[0-9.eE+-]+.*$',
                      lambda m: f'{m.group(1)}{num(value)}  # self-tune {provenance}',
                      YAML.read_text(), count=1, flags=re.M)
    if n != 1:
        raise SystemExit(f'{key} not found in {YAML}')
    YAML.write_text(text)


def git(*args, check=True):
    return subprocess.run(['git', '-C', str(REPO_ROOT), *args],
                          check=check, capture_output=True, text=True).stdout.strip()


def sh(cmd, dry):
    print('+', ' '.join(cmd))
    if not dry:
        subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('report')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    rep = json.loads(Path(a.report).read_text())
    if not rep['valid'] or rep['median_temp_c'] is None:
        print('refused: fit invalid', rep['reasons'])
        return 3
    fit = ChamberParams(**rep['params'])
    last = ChamberParams(**json.loads(ACCEPTED.read_text())['params']) if ACCEPTED.exists() else ChamberParams()
    tau_c = yaml_value('pid_simc_tau_c_seconds') or None  # 0.0 and unset are equivalent: simc_gains defaults tau_c to the fitted theta either way
    push = guard(fit, last, rep['median_temp_c'], tau_c_s=tau_c)
    print(json.dumps({'ok': push.ok, 'reasons': push.reasons, 'clamped': push.clamped,
                      'params': asdict(push.params), 'gains': asdict(push.gains)}, indent=2))
    if not push.ok:
        return 3

    values = {
        'pid_kp': push.gains.kp, 'pid_ki': push.gains.ki, 'pid_kd': push.gains.kd,
        'fill_g_per_h': push.params.fill_g_per_h, 'surface_g_per_k': push.params.surface_g_per_k,
    }
    # One ssh, all five sets chained with && : a network drop mid-push cannot
    # leave fc1 with half a gain set. It is not transactional -- an ssh that
    # dies between two sets still leaves the earlier ones applied -- so the
    # read-back below is what actually decides whether the yaml is edited.
    remote = ' && '.join(f'ros2-cmd param set {NODE} {k} {num(v)}' for k, v in values.items())
    sh(['ssh', 'fc1', remote], a.dry_run)
    if a.dry_run:
        return 0
    got = subprocess.run(['ssh', 'fc1', f'ros2-cmd param get {NODE} pid_kp'],
                         check=True, capture_output=True, text=True).stdout
    m = re.search(r'([0-9.eE+-]+)\s*$', got.strip())
    if m is None or abs(float(m.group(1)) - values['pid_kp']) > 1e-6:
        print(f'refused: fc1 pid_kp read back as {got.strip()!r}, wanted {num(values["pid_kp"])};'
              ' yaml not touched')
        return 1

    # Only commit a clean checkout of main holding exactly our two files:
    # this runs unattended on a host that is also production.
    branch = git('symbolic-ref', '--short', 'HEAD', check=False)
    if branch != 'main':
        print(f'refused: HEAD is {branch!r}, not main; params pushed to fc1, yaml not committed')
        return 1
    for k, v in values.items():
        set_yaml(k, v, Path(a.report).name)
    ACCEPTED.write_text(json.dumps({'params': asdict(push.params), 'gains': asdict(push.gains),
                                    'report': str(a.report)}, indent=2))
    dirty = sorted(line[3:] for line in git('status', '--porcelain').splitlines())
    expected = sorted(str(f.relative_to(REPO_ROOT)) for f in (YAML, ACCEPTED))
    if dirty != expected:
        print(f'refused: working tree holds {dirty}, expected only {expected}; not committing')
        return 1
    sh(['git', '-C', str(REPO_ROOT), 'add', str(YAML), str(ACCEPTED)], False)
    sh(['git', '-C', str(REPO_ROOT), 'commit', '-q', '-m',
        f'config(fc_core): self-tune push from {Path(a.report).name} [MUSHY-138]'], False)
    sh(['git', '-C', str(REPO_ROOT), 'push', '-q', 'origin', 'main'], False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
