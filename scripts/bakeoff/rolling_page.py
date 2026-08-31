"""MUSHY-150: rolling short-horizon predictions over the forced cycle.

The free-run replay asked every model to integrate two hours from one initial
condition -- hours past the 45 min they were trained for, and nothing like how
a controller would use them. This instead re-initialises from the measured
state at EVERY sample and asks the question the model was actually fitted on:
given what you know now, where is the chamber in 5 / 15 / 45 minutes?

Uses the PRE-FORCING checkpoints by default: this is what we had before the
experiment, judged on its own terms.

    .venv/bin/python scripts/bakeoff/rolling_page.py > web/rolling.html
"""
import glob, json, os, sys
import numpy as np
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import CANDIDATES, rollout, ah_sat, CHANNELS, HORIZONS, TAU_LO, TAU_HI

# The bake-off checkpoints ARE the pre-forcing fits: refit_with_forced.py runs
# with ckpt_path='' and never writes here. gary is skipped while its fit is
# still running -- a mid-fit checkpoint is not a model.
CK = 'scripts/bakeoff/results'
DONE = lambda n: os.path.exists(f'scripts/bakeoff/results/inter-{n}-s0.json')
R = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'scripts/bakeoff/web/replay.json'))
dt_s = R['dt_s']
rh = torch.tensor(R['actual_rh'], dtype=torch.float64)
T = torch.tensor(R['temp'], dtype=torch.float64)
duty = torch.tensor(R['duty'], dtype=torch.float64)
amb = torch.tensor(R['amb_ah'], dtype=torch.float64)
ah = rh / 100.0 * ah_sat(T)
N = len(rh)
ks = [int(h * 60 / dt_s) for h in HORIZONS]
K = max(ks)
# EVERY horizon scores the SAME target times: targets run from K to the end,
# and each horizon takes its origin k_h steps earlier. Building windows from a
# shared set of ORIGINS instead would give each panel a different x-range --
# the 5 min panel covering 5..84 min while the 45 min panel covered 45..124 --
# which is not comparable side by side.
targets = list(range(K, N))

# Forced phases: the LONGEST run of duty==0 and the LONGEST run of duty==1.
# Thresholding on duty alone does not work -- the controller is bang-bang, so
# duty hits 1.0 during ordinary operation too; only the forced phases hold a
# constant value for tens of minutes.
d = np.array(R['duty'])


def longest_run(mask):
    best = (0, 0, 0)
    i = 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            if j - i > best[0]:
                best = (j - i, i, j)
            i = j
        else:
            i += 1
    return best


forced = []
regions = {}
for lab, mask in (('forced OFF', d < 1e-6), ('forced ON', d > 0.99)):
    n_, i0, i1 = longest_run(mask)
    if n_ * dt_s > 20 * 60:                      # only a real forced phase
        forced.append(dict(a=round(R['t'][i0] / 60, 2), b=round(R['t'][i1 - 1] / 60, 2), label=lab))
        regions[lab] = (i0, i1)

fi0 = min(v[0] for v in regions.values()) if regions else None
fi1 = max(v[1] for v in regions.values()) if regions else None



def batch_for(k):
    org = [t - k for t in targets]
    take = lambda v: torch.stack([v[i:i + k] for i in org])
    b = {'duty': take(duty), 'temp': take(T), 'amb_ah': take(amb),
         'ah0': ah[torch.tensor(org)], 'rh': take(rh),
         'valid': torch.ones(len(org), k, dtype=torch.bool)}
    for c in CHANNELS:
        b[c] = torch.zeros(len(org), k, dtype=torch.float64)
    return b


BATCH = {k: batch_for(k) for k in ks}

# Which forecast TARGETS land inside the forced phases. The wide window is
# mostly ordinary operation, so one aggregate number would average the failure
# away -- the split is the entire reason for widening it.
in_forced = np.array([(fi0 is not None and fi0 <= i < fi1) for i in targets])


def split_rmse(pred, tgt):
    e = (pred - tgt) ** 2
    f = lambda m_: (float(np.sqrt(e[m_].mean())) if m_.any() else None)
    return dict(all=f(np.ones(len(e), bool)), forced=f(in_forced), normal=f(~in_forced))


DROP = set(os.environ.get('DROP', '').split(',')) - {''}
REFIT = os.environ.get('REFIT', '')

JOBS = []
for name in ('alice', 'bob', 'charlie', 'dave', 'eve', 'frank', 'gary'):
    if name in DROP:
        continue
    p = f'{CK}/inter-{name}-s0.json.{name}.ckpt'
    if os.path.exists(p) and DONE(name):
        JOBS.append((name, name, p, None))

# Refit variants, reconstructed from the scalars in the refit JSON. Same colour
# as their base model (colour follows the entity), dashed to mark the variant.
if REFIT and os.path.exists(REFIT):
    for r in json.load(open(REFIT))['models']:
        if r['name'] in DROP or r['name'] not in ('alice', 'bob', 'charlie', 'dave'):
            continue
        JOBS.append((r['name'] + '+forced', r['name'], None, r))

out = []
for label, name, p, refit in JOBS:
    m = CANDIDATES[name]()
    if refit is None:
        ck = torch.load(p, weights_only=False)
        m.load_state_dict(ck['model'])
        tau = TAU_LO + (TAU_HI - TAU_LO) * torch.sigmoid(ck['log_tau'])
    else:
        with torch.no_grad():
            for k_, v in refit['params'].items():
                getattr(m, k_).copy_(torch.tensor(
                    np.log(v) if k_.startswith('log') else v, dtype=torch.float64))
        tau = torch.tensor(refit['tau_s'], dtype=torch.float64)
    series, rmse = {}, {}
    tgt = np.array([float(ah[i]) for i in targets])
    for h, k in zip(HORIZONS, ks):
        b = BATCH[k]
        with torch.no_grad():
            pv = (rollout(m, tau, b, dt_s) / 100.0 * ah_sat(b['temp'])).numpy()[:, k - 1]
        series[int(h)] = [round(float(x), 4) for x in pv]
        rmse[int(h)] = split_rmse(pv, tgt)
    out.append(dict(name=label, base=name, series=series, rmse=rmse,
                    dash=refit is not None,
                    n_params=sum(x.numel() for x in m.parameters()) + 1))

# persistence baseline at each horizon, for the same starts
base = {}
tgt = np.array([float(ah[i]) for i in targets])
for h, k in zip(HORIZONS, ks):
    p0 = np.array([float(ah[i - k]) for i in targets])
    base[int(h)] = split_rmse(p0, tgt)


payload = json.dumps({
    'h': [int(x) for x in HORIZONS],
    'x': [round(R['t'][i] / 60, 3) for i in targets],
    'target': [round(float(ah[i]), 4) for i in targets],
    'duty_at': [round(float(duty[i]), 3) for i in targets],
    'forced': forced,
    'models': out, 'base': base, 'n': len(targets),
}, separators=(',', ':'))

print(f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rolling forecast - MUSHY-150</title>
<style>
:root {{ color-scheme:light; --bg:#f7f7f5; --surface-1:#fcfcfb; --border:#e2e1dc;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#84837c;
  --grid:#ecebe6; --measured:#0b0b0b;
  --s-alice:#2a78d6; --s-bob:#eb6834; --s-charlie:#1baf7a; --s-dave:#eda100; --s-eve:#e87ba4; --s-gary:#008300; --s-frank:#4a3aa7; }}
@media (prefers-color-scheme:dark) {{ :root:not([data-theme="light"]) {{
  color-scheme:dark; --bg:#121211; --surface-1:#1a1a19; --border:#33322e;
  --text-primary:#fff; --text-secondary:#c3c2b7; --text-muted:#8d8c83;
  --grid:#2a2a27; --measured:#fff;
  --s-alice:#3987e5; --s-bob:#d95926; --s-charlie:#199e70; --s-dave:#c98500; --s-eve:#d55181; --s-gary:#008300; --s-frank:#9085e9; }} }}
:root[data-theme="dark"] {{ color-scheme:dark; --bg:#121211; --surface-1:#1a1a19;
  --border:#33322e; --text-primary:#fff; --text-secondary:#c3c2b7; --text-muted:#8d8c83;
  --grid:#2a2a27; --measured:#fff;
  --s-alice:#3987e5; --s-bob:#d95926; --s-charlie:#199e70; --s-dave:#c98500; --s-eve:#d55181; --s-gary:#008300; --s-frank:#9085e9; }}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text-primary);
 font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:28px 20px 64px}}
.wrap{{max-width:1060px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 6px;letter-spacing:-.01em;line-height:1.25}}
.sub{{color:var(--text-secondary);margin:0 0 4px;max-width:76ch}}
.meta{{color:var(--text-muted);font-size:12.5px;margin:0 0 22px}}
.card{{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;
 padding:16px 18px 10px;margin-bottom:16px}}
.card h2{{font-size:13px;font-weight:650;margin:0 0 2px}}
.card p.note{{color:var(--text-secondary);font-size:12.5px;margin:0 0 10px;max-width:80ch}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;margin:0 0 10px;font-size:12.5px;color:var(--text-secondary)}}
.legend span{{display:flex;align-items:center;gap:6px}}
.dot{{width:9px;height:9px;border-radius:2px;flex:none}}
.chart{{position:relative;width:100%}} svg{{display:block;width:100%;height:auto}}
.tt{{position:absolute;pointer-events:none;background:var(--surface-1);border:1px solid var(--border);
 border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.13);
 opacity:0;transition:opacity .09s;min-width:168px;z-index:5}}
.tt table{{border-collapse:collapse;width:100%}} .tt td{{padding:1px 0;font-variant-numeric:tabular-nums}}
.tt td.k{{color:var(--text-secondary);padding-right:10px}} .tt td.v{{text-align:right;font-weight:600}}
.tt .hd{{font-weight:650;margin-bottom:4px}}
table.data{{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:6px;font-variant-numeric:tabular-nums}}
table.data th,table.data td{{border-bottom:1px solid var(--border);padding:6px 9px;text-align:right}}
table.data th:first-child,table.data td:first-child{{text-align:left}}
table.data th{{color:var(--text-secondary);font-weight:600}}
.foot{{color:var(--text-muted);font-size:12px;margin-top:26px;max-width:80ch}}
code{{font:12px ui-monospace,Menlo,monospace;background:var(--grid);padding:1px 5px;border-radius:4px}}
</style></head><body><div class="wrap">
<h1>The same models, asked a question they were trained for</h1>
<p class="sub">Re-initialised from the measured chamber at every 10 s sample, then asked
where absolute humidity will be 5, 15 and 45 minutes later. This is how a controller would
use them, and it is the horizon they were fitted on &mdash; unlike the free-run replay, which
made them integrate two hours from a single starting point.</p>
<p class="meta" id="meta"></p>
<div class="card"><h2>Accuracy at each horizon</h2>
<p class="note">The window is mostly ordinary control with the forced experiment inside it,
so the two regimes are scored separately &mdash; one blended number would average the
failure away.</p><div id="tbl"></div></div>
<div id="panels"></div>
<p class="foot">Pre-forcing checkpoints &mdash; the models exactly as they stood before the
experiment was added to anything. Generated by <code>scripts/bakeoff/rolling_page.py</code>.</p>
</div><script>
const D={payload};
const S=id=>document.getElementById(id), F=(x,n=3)=>x.toFixed(n);
S('meta').textContent=`${{D.n}} forecast origins, one per 10 s sample · absolute humidity in g/m³`;

const REG=[['normal','ordinary control'],['forced','forced phases'],['all','whole window']];
let t='<table class="data"><tr><th>model</th><th>par</th>'
 + REG.map(([k,lab])=>D.h.map(h=>`<th>${{lab.split(' ')[0]}} ${{h}}m</th>`).join('')).join('')+'</tr>';
t+=`<tr><td>hold AH constant</td><td>0</td>`
 + REG.map(([k])=>D.h.map(h=>`<td>1.00</td>`).join('')).join('')+'</tr>';
for(const m of D.models) t+=`<tr><td><span class="dot" style="display:inline-block;background:var(--s-${{m.base}})"></span> ${{m.name}}</td>`
 + `<td>${{m.n_params}}</td>`
 + REG.map(([k])=>D.h.map(h=>{{const v=m.rmse[h][k],b=D.base[h][k];
     return `<td>${{(v==null||b==null)?'&mdash;':(v/b).toFixed(2)}}</td>`;}}).join('')).join('')+'</tr>';
S('tbl').innerHTML=t+'</table>'
 +'<p class="note" style="margin-top:8px">Skill against holding absolute humidity constant, '
 +'split by regime. Below 1.00 beats doing nothing; above 1.00 is worse than doing nothing.</p>';

const W=1000,H=250,PAD={{l:54,r:74,t:12,b:26}};
D.h.forEach((h,idx)=>{{
  const id='p'+h;
  S('panels').insertAdjacentHTML('beforeend',`<div class="card">
    <h2>${{h}}-minute forecast</h2>
    <p class="note">Each point is a prediction made ${{h}} minutes earlier, drawn at the time it
    is about. The black line is what the chamber actually did.</p>
    <div class="legend">${{'<span><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5" stroke="var(--measured)" stroke-width="2.5"/></svg>measured</span>'
      + D.models.map(m=>`<span><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5" stroke="var(--s-${{m.base}})" stroke-width="2.5"${{m.dash?' stroke-dasharray="4 2.5"':''}}/></svg>${{m.name}}</span>`).join('')}}</div>
    <div class="chart" id="${{id}}"><div class="tt" id="tt${{h}}"></div></div></div>`);
  const xs=D.x, tg=D.target;   // shared across panels now
  const all=[tg].concat(D.models.map(m=>m.series[h])).flat();
  let lo=Math.min(...all), hi=Math.max(...all); const pd=(hi-lo)*0.08; lo-=pd; hi+=pd;
  const X=v=>PAD.l+((v-xs[0])/(xs[xs.length-1]-xs[0]))*(W-PAD.l-PAD.r),
        Y=v=>PAD.t+(1-(v-lo)/(hi-lo))*(H-PAD.t-PAD.b);
  let g='';
  for(const b of D.forced){{
    const x0=X(Math.max(b.a,xs[0])), x1=X(Math.min(b.b,xs[xs.length-1]));
    if(x1>x0) g+=`<rect x="${{x0}}" y="${{PAD.t}}" width="${{x1-x0}}" height="${{H-PAD.t-PAD.b}}"
      fill="var(--text-muted)" opacity="0.10"/>`
      +`<text x="${{(x0+x1)/2}}" y="${{PAD.t+12}}" text-anchor="middle" font-size="10.5"
        fill="var(--text-muted)">${{b.label}}</text>`;
  }}
  for(let i=0;i<=4;i++){{const v=lo+(hi-lo)*i/4,y=Y(v);
    g+=`<line x1="${{PAD.l}}" y1="${{y}}" x2="${{W-PAD.r}}" y2="${{y}}" stroke="var(--grid)"/>`
     +`<text x="${{PAD.l-8}}" y="${{y+4}}" text-anchor="end" font-size="11" fill="var(--text-muted)">${{v.toFixed(1)}}</text>`;}}
  for(let mn=Math.ceil(xs[0]/20)*20;mn<=xs[xs.length-1];mn+=20)
    g+=`<text x="${{X(mn)}}" y="${{H-8}}" text-anchor="middle" font-size="11" fill="var(--text-muted)">${{mn}}m</text>`;
  const line=(v,c,w,lab,dash)=>{{let d='';for(let i=0;i<xs.length;i++)d+=(i?'L':'M')+X(xs[i]).toFixed(1)+' '+Y(v[i]).toFixed(1);
    let o=`<path d="${{d}}" fill="none" stroke="${{c}}" stroke-width="${{w}}" stroke-linejoin="round"${{dash?' stroke-dasharray="5 3"':''}}/>`;
    if(lab)o+=`<text x="${{W-PAD.r+7}}" y="${{Y(v[v.length-1])+4}}" font-size="11.5" font-weight="600" fill="${{c}}">${{lab}}</text>`;
    return o;}};
  g+=line(tg,'var(--measured)',2.5,'');
  for(const m of D.models) g+=line(m.series[h],`var(--s-${{m.base}})`,2,m.name,m.dash);
  g+=`<line id="${{id}}-cx" x1="0" y1="${{PAD.t}}" x2="0" y2="${{H-PAD.b}}" stroke="var(--text-muted)" opacity="0"/>`;
  S(id).insertAdjacentHTML('afterbegin',`<svg viewBox="0 0 ${{W}} ${{H}}" preserveAspectRatio="xMidYMid meet" role="img">${{g}}</svg>`);
  const box=S(id),tt=S('tt'+h),svg=box.querySelector('svg'),cx=document.getElementById(id+'-cx');
  box.addEventListener('pointermove',e=>{{
    const r=svg.getBoundingClientRect(),px=(e.clientX-r.left)/r.width*W;
    let i=Math.round((px-PAD.l)/(W-PAD.l-PAD.r)*(xs.length-1));
    i=Math.max(0,Math.min(xs.length-1,i));
    cx.setAttribute('x1',X(xs[i]));cx.setAttribute('x2',X(xs[i]));cx.setAttribute('opacity','.55');
    tt.innerHTML=`<div class="hd">at ${{xs[i].toFixed(0)}} min · duty ${{D.duty_at[i].toFixed(2)}}</div><table>`
      +`<tr><td class="k">measured</td><td class="v">${{F(tg[i])}}</td></tr>`
      +D.models.map(m=>`<tr><td class="k"><span class="dot" style="display:inline-block;background:var(--s-${{m.base}})"></span> ${{m.name}}</td><td class="v">${{F(m.series[h][i])}}</td></tr>`).join('')
      +'</table>';
    tt.style.opacity='1';
    tt.style.left=Math.min(e.clientX-r.left+14,r.width-tt.offsetWidth-6)+'px';
    tt.style.top=Math.max(4,e.clientY-r.top-tt.offsetHeight-12)+'px';
  }});
  box.addEventListener('pointerleave',()=>{{tt.style.opacity='0';cx.setAttribute('opacity','0');}});
}});
</script></body></html>''')
