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

CK = 'scripts/bakeoff/web/baseline-2026-08-31-preforced'
R = json.load(open('scripts/bakeoff/web/replay.json'))
dt_s = R['dt_s']
rh = torch.tensor(R['actual_rh'], dtype=torch.float64)
T = torch.tensor(R['temp'], dtype=torch.float64)
duty = torch.tensor(R['duty'], dtype=torch.float64)
amb = torch.tensor(R['amb_ah'], dtype=torch.float64)
ah = rh / 100.0 * ah_sat(T)
N = len(rh)
ks = [int(h * 60 / dt_s) for h in HORIZONS]
K = max(ks)
starts = list(range(0, N - K))

take = lambda v: torch.stack([v[i:i + K] for i in starts])
B = {'duty': take(duty), 'temp': take(T), 'amb_ah': take(amb),
     'ah0': ah[torch.tensor(starts)], 'rh': take(rh),
     'valid': torch.ones(len(starts), K, dtype=torch.bool)}
for c in CHANNELS:
    B[c] = torch.zeros(len(starts), K, dtype=torch.float64)
sat_win = ah_sat(B['temp'])

COL = {'alice': 'alice', 'bob': 'bob', 'charlie': 'charlie', 'dave': 'dave', 'gary': 'gary'}
out = []
for name in ('alice', 'bob', 'charlie', 'dave', 'gary'):
    p = f'{CK}/{name}.ckpt'
    if not os.path.exists(p):
        continue
    ck = torch.load(p, weights_only=False)
    m = CANDIDATES[name]()
    m.load_state_dict(ck['model'])
    tau = TAU_LO + (TAU_HI - TAU_LO) * torch.sigmoid(ck['log_tau'])
    with torch.no_grad():
        pred_ah = (rollout(m, tau, B, dt_s) / 100.0 * sat_win).numpy()
    series, rmse = {}, {}
    for h, k in zip(HORIZONS, ks):
        tgt = np.array([ah[i + k - 1] for i in starts])
        pv = pred_ah[:, k - 1]
        series[int(h)] = [round(float(x), 4) for x in pv]
        rmse[int(h)] = float(np.sqrt(((pv - tgt) ** 2).mean()))
    out.append(dict(name=name, series=series, rmse=rmse,
                    n_params=sum(x.numel() for x in m.parameters()) + 1))

# persistence baseline at each horizon, for the same starts
base = {}
for h, k in zip(HORIZONS, ks):
    tgt = np.array([float(ah[i + k - 1]) for i in starts])
    p0 = np.array([float(ah[i]) for i in starts])
    base[int(h)] = float(np.sqrt(((p0 - tgt) ** 2).mean()))

payload = json.dumps({
    'h': [int(x) for x in HORIZONS],
    'x': {int(h): [round(R['t'][i + k - 1] / 60, 3) for i in starts]
          for h, k in zip(HORIZONS, ks)},
    'target': {int(h): [round(float(ah[i + k - 1]), 4) for i in starts]
               for h, k in zip(HORIZONS, ks)},
    'duty_at': {int(h): [round(float(duty[i + k - 1]), 3) for i in starts]
                for h, k in zip(HORIZONS, ks)},
    'models': out, 'base': base, 'n': len(starts),
}, separators=(',', ':'))

print(f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rolling forecast - MUSHY-150</title>
<style>
:root {{ color-scheme:light; --bg:#f7f7f5; --surface-1:#fcfcfb; --border:#e2e1dc;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#84837c;
  --grid:#ecebe6; --measured:#0b0b0b;
  --s-alice:#2a78d6; --s-bob:#eb6834; --s-charlie:#1baf7a; --s-dave:#eda100; --s-gary:#e87ba4; }}
@media (prefers-color-scheme:dark) {{ :root:not([data-theme="light"]) {{
  color-scheme:dark; --bg:#121211; --surface-1:#1a1a19; --border:#33322e;
  --text-primary:#fff; --text-secondary:#c3c2b7; --text-muted:#8d8c83;
  --grid:#2a2a27; --measured:#fff;
  --s-alice:#3987e5; --s-bob:#d95926; --s-charlie:#199e70; --s-dave:#c98500; --s-gary:#d55181; }} }}
:root[data-theme="dark"] {{ color-scheme:dark; --bg:#121211; --surface-1:#1a1a19;
  --border:#33322e; --text-primary:#fff; --text-secondary:#c3c2b7; --text-muted:#8d8c83;
  --grid:#2a2a27; --measured:#fff;
  --s-alice:#3987e5; --s-bob:#d95926; --s-charlie:#199e70; --s-dave:#c98500; --s-gary:#d55181; }}
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
<p class="note">Root mean squared error of the rolling forecast, against holding
absolute humidity constant. Below 1.00 beats doing nothing.</p><div id="tbl"></div></div>
<div id="panels"></div>
<p class="foot">Pre-forcing checkpoints &mdash; the models exactly as they stood before the
experiment was added to anything. Generated by <code>scripts/bakeoff/rolling_page.py</code>.</p>
</div><script>
const D={payload};
const S=id=>document.getElementById(id), F=(x,n=3)=>x.toFixed(n);
S('meta').textContent=`${{D.n}} forecast origins, one per 10 s sample · absolute humidity in g/m³`;

let t='<table class="data"><tr><th>model</th><th>par</th>'
 + D.h.map(h=>`<th>${{h}} min</th>`).join('') + D.h.map(h=>`<th>skill ${{h}}m</th>`).join('') + '</tr>';
t+=`<tr><td>hold AH constant</td><td>0</td>`+D.h.map(h=>`<td>${{F(D.base[h])}}</td>`).join('')
 + D.h.map(()=>'<td>1.00</td>').join('')+'</tr>';
for(const m of D.models) t+=`<tr><td><span class="dot" style="display:inline-block;background:var(--s-${{m.name}})"></span> ${{m.name}}</td>`
 + `<td>${{m.n_params}}</td>` + D.h.map(h=>`<td>${{F(m.rmse[h])}}</td>`).join('')
 + D.h.map(h=>`<td>${{(m.rmse[h]/D.base[h]).toFixed(2)}}</td>`).join('')+'</tr>';
S('tbl').innerHTML=t+'</table>';

const W=1000,H=250,PAD={{l:54,r:74,t:12,b:26}};
D.h.forEach((h,idx)=>{{
  const id='p'+h;
  S('panels').insertAdjacentHTML('beforeend',`<div class="card">
    <h2>${{h}}-minute forecast</h2>
    <p class="note">Each point is a prediction made ${{h}} minutes earlier, drawn at the time it
    is about. The black line is what the chamber actually did.</p>
    <div class="legend">${{'<span><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5" stroke="var(--measured)" stroke-width="2.5"/></svg>measured</span>'
      + D.models.map(m=>`<span><span class="dot" style="background:var(--s-${{m.name}})"></span>${{m.name}}</span>`).join('')}}</div>
    <div class="chart" id="${{id}}"><div class="tt" id="tt${{h}}"></div></div></div>`);
  const xs=D.x[h], tg=D.target[h];
  const all=[tg].concat(D.models.map(m=>m.series[h])).flat();
  let lo=Math.min(...all), hi=Math.max(...all); const pd=(hi-lo)*0.08; lo-=pd; hi+=pd;
  const X=v=>PAD.l+((v-xs[0])/(xs[xs.length-1]-xs[0]))*(W-PAD.l-PAD.r),
        Y=v=>PAD.t+(1-(v-lo)/(hi-lo))*(H-PAD.t-PAD.b);
  let g='';
  for(let i=0;i<=4;i++){{const v=lo+(hi-lo)*i/4,y=Y(v);
    g+=`<line x1="${{PAD.l}}" y1="${{y}}" x2="${{W-PAD.r}}" y2="${{y}}" stroke="var(--grid)"/>`
     +`<text x="${{PAD.l-8}}" y="${{y+4}}" text-anchor="end" font-size="11" fill="var(--text-muted)">${{v.toFixed(1)}}</text>`;}}
  for(let mn=Math.ceil(xs[0]/20)*20;mn<=xs[xs.length-1];mn+=20)
    g+=`<text x="${{X(mn)}}" y="${{H-8}}" text-anchor="middle" font-size="11" fill="var(--text-muted)">${{mn}}m</text>`;
  const line=(v,c,w,lab)=>{{let d='';for(let i=0;i<xs.length;i++)d+=(i?'L':'M')+X(xs[i]).toFixed(1)+' '+Y(v[i]).toFixed(1);
    let o=`<path d="${{d}}" fill="none" stroke="${{c}}" stroke-width="${{w}}" stroke-linejoin="round"/>`;
    if(lab)o+=`<text x="${{W-PAD.r+7}}" y="${{Y(v[v.length-1])+4}}" font-size="11.5" font-weight="600" fill="${{c}}">${{lab}}</text>`;
    return o;}};
  g+=line(tg,'var(--measured)',2.5,'');
  for(const m of D.models) g+=line(m.series[h],`var(--s-${{m.name}})`,2,m.name);
  g+=`<line id="${{id}}-cx" x1="0" y1="${{PAD.t}}" x2="0" y2="${{H-PAD.b}}" stroke="var(--text-muted)" opacity="0"/>`;
  S(id).insertAdjacentHTML('afterbegin',`<svg viewBox="0 0 ${{W}} ${{H}}" preserveAspectRatio="xMidYMid meet" role="img">${{g}}</svg>`);
  const box=S(id),tt=S('tt'+h),svg=box.querySelector('svg'),cx=document.getElementById(id+'-cx');
  box.addEventListener('pointermove',e=>{{
    const r=svg.getBoundingClientRect(),px=(e.clientX-r.left)/r.width*W;
    let i=Math.round((px-PAD.l)/(W-PAD.l-PAD.r)*(xs.length-1));
    i=Math.max(0,Math.min(xs.length-1,i));
    cx.setAttribute('x1',X(xs[i]));cx.setAttribute('x2',X(xs[i]));cx.setAttribute('opacity','.55');
    tt.innerHTML=`<div class="hd">at ${{xs[i].toFixed(0)}} min · duty ${{D.duty_at[h][i].toFixed(2)}}</div><table>`
      +`<tr><td class="k">measured</td><td class="v">${{F(tg[i])}}</td></tr>`
      +D.models.map(m=>`<tr><td class="k"><span class="dot" style="display:inline-block;background:var(--s-${{m.name}})"></span> ${{m.name}}</td><td class="v">${{F(m.series[h][i])}}</td></tr>`).join('')
      +'</table>';
    tt.style.opacity='1';
    tt.style.left=Math.min(e.clientX-r.left+14,r.width-tt.offsetWidth-6)+'px';
    tt.style.top=Math.max(4,e.clientY-r.top-tt.offsetHeight-12)+'px';
  }});
  box.addEventListener('pointerleave',()=>{{tt.style.opacity='0';cx.setAttribute('opacity','0');}});
}});
</script></body></html>''')
