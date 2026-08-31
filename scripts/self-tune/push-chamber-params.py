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
TRIM_RANGE = (0.01, 10.0)   # sanity bound on the MUSHY-145 rescaled feedforward trim


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


def dirty_paths():
    """Paths git reports as modified, sorted.

    NOT via git(): that strips the output, which eats the leading space of
    porcelain's 2-char status column on the FIRST line only, so `line[3:]`
    lost a character of that path and no comparison against a list of
    expected files could ever match (MUSHY-142 round 2).
    """
    out = subprocess.run(['git', '-C', str(REPO_ROOT), 'status', '--porcelain'],
                         check=True, capture_output=True, text=True).stdout
    return sorted(line[3:] for line in out.splitlines())


def ours():
    return sorted(str(f.relative_to(REPO_ROOT)) for f in (YAML, ACCEPTED))


def precondition_refusal():
    """Why this checkout must not be committed to, or None if it is safe.

    Checked BEFORE anything is written or pushed (MUSHY-142). The old check
    ran after set_yaml, so it could not tell a pre-existing hand edit to
    fc_config.yaml -- params set live then committed by hand is a routine
    workflow here -- from this script's own write, and would have folded that
    edit into an automated commit and pushed it to origin/main. Running before
    the fc1 param set as well means a refusal never leaves fc1 holding gains
    the yaml does not record.
    """
    branch = git('symbolic-ref', '--short', 'HEAD', check=False)
    if branch != 'main':
        return f'HEAD is {branch!r}, not main'
    overlap = [f for f in dirty_paths() if f in ours()]
    if overlap:
        return f'{overlap} already modified before this run; commit or revert first'
    return None


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

    refusal = precondition_refusal()
    if refusal and not a.dry_run:
        print(f'refused: {refusal}; nothing pushed')
        return 1

    values = {
        'pid_kp': push.gains.kp, 'pid_ki': push.gains.ki, 'pid_kd': push.gains.kd,
        'fill_g_per_h': push.params.fill_g_per_h, 'surface_g_per_k': push.params.surface_g_per_k,
    }
    # MUSHY-145: F is a DIVISOR in temp_feedforward_gain (control_kernel.py),
    # so writing fill_g_per_h silently rescales the MUSHY-125 temperature
    # feedforward -- an effect nobody asked this push to have. The numerator of
    # that gain does not contain F, so the gain moves by exactly F_old/F_new;
    # scaling the trim by F_new/F_old holds the EFFECTIVE feedforward where the
    # farmer tuned it. Twin-verified on 2026-08-30 13-23Z: leaving the trim
    # alone widened RH p2p 4.22 -> 5.03 and put the chamber 3 min below the
    # floor, while the rescale reproduced today's behaviour exactly.
    #
    # This keeps the push NEUTRAL on the feedforward. Retuning it against the
    # corrected model is a separate, deliberate decision (MUSHY-125), not a
    # side effect of a model update.
    f_old, trim_old = yaml_value('fill_g_per_h'), yaml_value('humidifier_temp_feedforward')
    if trim_old and f_old:
        trim_new = trim_old * push.params.fill_g_per_h / f_old
        lo, hi = TRIM_RANGE
        if not (lo <= trim_new <= hi):
            print(f'refused: rescaled humidifier_temp_feedforward={trim_new:.4g} outside '
                  f'[{lo}, {hi}]; F moved {f_old:.4g} -> {push.params.fill_g_per_h:.4g}')
            return 3
        values['humidifier_temp_feedforward'] = trim_new
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

    for k, v in values.items():
        set_yaml(k, v, Path(a.report).name)
    ACCEPTED.write_text(json.dumps({'params': asdict(push.params), 'gains': asdict(push.gains),
                                    'report': str(a.report)}, indent=2))
    # Belt and braces: the tree was clean of our files at precondition time,
    # so anything beyond them now is a concurrent edit -- still not ours to commit.
    dirty, expected = dirty_paths(), ours()
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
