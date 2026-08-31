"""MUSHY-150: render the forced-cycle replay as a standalone page.

    .venv/bin/python scripts/bakeoff/replay_cycle.py > web/replay.json
    .venv/bin/python scripts/bakeoff/make_replay_page.py > web/index.html
"""
import json, sys, datetime as dt

D = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'scripts/bakeoff/web/replay.json'))
COL = {'alice': ('#2a78d6', '#3987e5'), 'bob': ('#eb6834', '#d95926'),
       'charlie': ('#1baf7a', '#199e70'), 'dave': ('#eda100', '#c98500')}
t0 = dt.datetime.fromtimestamp(D['t0_epoch'], dt.timezone(dt.timedelta(hours=-3)))
ms = sorted(D['models'], key=lambda m: m['rmse'])
payload = json.dumps({
    't': [round(x / 60, 3) for x in D['t']], 'actual': [round(x, 4) for x in D['actual_ah']],
    'duty': [round(x, 3) for x in D['duty']], 'temp': [round(x, 3) for x in D['temp']],
    'amb': [round(x, 4) for x in D['amb_ah']], 'rh': [round(x, 3) for x in D['actual_rh']],
    'models': [{'name': m['name'], 'ah': [round(x, 4) for x in m['ah']],
                'rmse': m['rmse'], 'bias': m['bias'], 'final': m['final_err'],
                'par': m['n_params'], 'light': COL[m['name']][0], 'dark': COL[m['name']][1],
                'params': m['params']} for m in ms],
    'start': t0.strftime('%H:%M'), 'date': t0.strftime('%Y-%m-%d'),
}, separators=(',', ':'))

print(f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Forced cycle replay - MUSHY-150</title>
<style>
:root {{
  color-scheme: light;
  --bg:#f7f7f5; --surface-1:#fcfcfb; --border:#e2e1dc;
  --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#84837c;
  --grid:#ecebe6; --measured:#0b0b0b; --zero:#a8a79f;
  --s-alice:#2a78d6; --s-bob:#eb6834; --s-charlie:#1baf7a; --s-dave:#eda100;
}}
@media (prefers-color-scheme:dark) {{ :root:not([data-theme="light"]) {{
  color-scheme: dark;
  --bg:#121211; --surface-1:#1a1a19; --border:#33322e;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8d8c83;
  --grid:#2a2a27; --measured:#ffffff; --zero:#6a6961;
  --s-alice:#3987e5; --s-bob:#d95926; --s-charlie:#199e70; --s-dave:#c98500;
}} }}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --bg:#121211; --surface-1:#1a1a19; --border:#33322e;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8d8c83;
  --grid:#2a2a27; --measured:#ffffff; --zero:#6a6961;
  --s-alice:#3987e5; --s-bob:#d95926; --s-charlie:#199e70; --s-dave:#c98500;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text-primary);
  font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  padding:28px 20px 64px}}
.wrap{{max-width:1060px;margin:0 auto}}
h1{{font-size:22px;line-height:1.25;margin:0 0 6px;letter-spacing:-.01em}}
.sub{{color:var(--text-secondary);margin:0 0 4px;max-width:74ch}}
.meta{{color:var(--text-muted);font-size:12.5px;margin:0 0 22px}}
.card{{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;
  padding:16px 18px 10px;margin-bottom:16px}}
.card h2{{font-size:13px;font-weight:650;margin:0 0 2px;letter-spacing:.01em}}
.card p.note{{color:var(--text-secondary);font-size:12.5px;margin:0 0 10px;max-width:78ch}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:10px;margin-bottom:16px}}
.tile{{background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:12px 14px}}
.tile .n{{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--text-secondary);margin-bottom:6px}}
.dot{{width:9px;height:9px;border-radius:2px;flex:none}}
.tile .v{{font-size:23px;font-weight:640;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
.tile .u{{font-size:12px;color:var(--text-muted);font-weight:400;margin-left:3px}}
.tile .d{{font-size:12px;color:var(--text-muted);font-variant-numeric:tabular-nums;margin-top:3px}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;margin:0 0 10px;font-size:12.5px;color:var(--text-secondary)}}
.legend span{{display:flex;align-items:center;gap:6px}}
.chart{{position:relative;width:100%;overflow-x:auto}}
svg{{display:block;width:100%;height:auto}}
.tt{{position:absolute;pointer-events:none;background:var(--surface-1);
  border:1px solid var(--border);border-radius:8px;padding:8px 10px;font-size:12px;
  box-shadow:0 4px 14px rgba(0,0,0,.13);opacity:0;transition:opacity .09s;min-width:172px;z-index:5}}
.tt table{{border-collapse:collapse;width:100%}}
.tt td{{padding:1px 0;font-variant-numeric:tabular-nums}}
.tt td.k{{color:var(--text-secondary);padding-right:10px}}
.tt td.v{{text-align:right;font-weight:600}}
.tt .hd{{font-weight:650;margin-bottom:4px;font-variant-numeric:tabular-nums}}
details{{margin-top:8px}} summary{{cursor:pointer;color:var(--text-secondary);font-size:12.5px}}
table.data{{border-collapse:collapse;width:100%;font-size:12px;margin-top:10px;
  font-variant-numeric:tabular-nums}}
table.data th,table.data td{{border-bottom:1px solid var(--border);padding:5px 8px;text-align:right}}
table.data th:first-child,table.data td:first-child{{text-align:left}}
table.data th{{color:var(--text-secondary);font-weight:600}}
.foot{{color:var(--text-muted);font-size:12px;margin-top:26px;max-width:80ch}}
code{{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--grid);
  padding:1px 5px;border-radius:4px}}
</style></head><body>
<div class="wrap">
<h1>Every model thinks the chamber stays wetter than it does</h1>
<p class="sub">The four physics candidates replayed through the first forced dry-down and wet-up
&mdash; an hour of humidifier fully off, then 45 minutes fully on. None of them has ever seen
data like this: they were fitted only on closed-loop operation, where the controller decides
when the humidifier runs.</p>
<p class="meta" id="meta"></p>
<div class="tiles" id="tiles"></div>

<div class="card">
  <h2>Absolute humidity &mdash; measured against each model</h2>
  <p class="note">Free-running from a single initial condition at the start. Each model is
  given the recorded duty and temperature and left to integrate for the full two hours.</p>
  <div class="legend" id="leg1"></div>
  <div class="chart" id="c1"><div class="tt" id="tt1"></div></div>
</div>

<div class="card">
  <h2>Error &mdash; model minus measured</h2>
  <p class="note">Above the line means the model holds more water than the chamber did.
  All four sit above it for nearly the whole cycle.</p>
  <div class="chart" id="c2"><div class="tt" id="tt2"></div></div>
</div>

<div class="card">
  <h2>What was done to the chamber</h2>
  <p class="note">Commanded humidifier duty. The controller was out of the loop for the whole
  window; both phases were forced through the experiment service.</p>
  <div class="chart" id="c3"><div class="tt" id="tt3"></div></div>
</div>

<div class="card">
  <h2>Fitted parameters</h2>
  <p class="note">From the seed-0 fits on the interleaved split, the models as they stand
  before the forced cycles are added to the corpus.</p>
  <div id="params"></div>
</div>

<details><summary>Data table (every 5 minutes)</summary><div id="tbl"></div></details>

<p class="foot">Baseline captured before re-fitting with the forced cycles included.
Absolute humidity is grams of water per cubic metre of air &mdash; unlike relative humidity it
does not move when temperature moves, so it isolates water actually entering or leaving.
Generated by <code>scripts/bakeoff/replay_cycle.py</code>.</p>
</div>
<script>
const D = {payload};
const F = (x,n=3)=>x.toFixed(n);
const S = (id)=>document.getElementById(id);

S('meta').textContent = `${{D.date}} · window starts ${{D.start}} local · ${{D.t.length}} samples at 10 s · `
  + `measured AH ${{F(D.actual[0],2)}} → ${{F(Math.min(...D.actual),2)}} → ${{F(D.actual[D.actual.length-1],2)}} g/m³`;

// ---- stat tiles: rmse is the headline, bias the diagnosis
S('tiles').innerHTML = D.models.map(m=>`<div class="tile">
  <div class="n"><span class="dot" style="background:var(--s-${{m.name}})"></span>${{m.name}}
    <span style="color:var(--text-muted)">${{m.par}} par</span></div>
  <div class="v">${{F(m.rmse)}}<span class="u">g/m³ rmse</span></div>
  <div class="d">bias ${{m.bias>=0?'+':''}}${{F(m.bias)}} · end ${{m.final>=0?'+':''}}${{F(m.final)}}</div>
</div>`).join('');

S('leg1').innerHTML = `<span><svg width="16" height="10"><line x1="0" y1="5" x2="16" y2="5"
  stroke="var(--measured)" stroke-width="2.5"/></svg>measured</span>` +
  D.models.map(m=>`<span><span class="dot" style="background:var(--s-${{m.name}})"></span>${{m.name}}</span>`).join('');

const W=1000, PAD={{l:54,r:78,t:10,b:26}};
function scale(series,pad){{
  let lo=Math.min(...series.flat()), hi=Math.max(...series.flat());
  const s=(hi-lo)*pad; return [lo-s, hi+s];
}}
function mkChart(el,H,ys,dom,opts){{
  const [lo,hi]=dom, X=t=>PAD.l+(t/D.t[D.t.length-1])*(W-PAD.l-PAD.r),
        Y=v=>PAD.t+(1-(v-lo)/(hi-lo))*(H-PAD.t-PAD.b);
  let g='';
  const ticks=opts.ticks||5;
  for(let i=0;i<=ticks;i++){{const v=lo+(hi-lo)*i/ticks, y=Y(v);
    g+=`<line x1="${{PAD.l}}" y1="${{y}}" x2="${{W-PAD.r}}" y2="${{y}}" stroke="var(--grid)" stroke-width="1"/>`
     +`<text x="${{PAD.l-8}}" y="${{y+4}}" text-anchor="end" font-size="11" fill="var(--text-muted)">${{opts.fmt(v)}}</text>`;}}
  for(let mn=0;mn<=D.t[D.t.length-1];mn+=20){{const x=X(mn);
    g+=`<text x="${{x}}" y="${{H-8}}" text-anchor="middle" font-size="11" fill="var(--text-muted)">${{mn}}m</text>`;}}
  if(opts.zero!==undefined){{const y=Y(opts.zero);
    g+=`<line x1="${{PAD.l}}" y1="${{y}}" x2="${{W-PAD.r}}" y2="${{y}}" stroke="var(--zero)" stroke-width="1.5" stroke-dasharray="4 3"/>`;}}
  for(const s of ys){{
    let d='';
    for(let i=0;i<D.t.length;i++){{ if(s.v[i]==null) continue;
      d+=(d?'L':'M')+X(D.t[i]).toFixed(1)+' '+Y(s.v[i]).toFixed(1); }}
    g+=`<path d="${{d}}" fill="none" stroke="${{s.c}}" stroke-width="${{s.w||2}}"
        stroke-linejoin="round" stroke-linecap="round" ${{s.dash?`stroke-dasharray="${{s.dash}}"`:''}}/>`;
    if(s.label){{ const last=s.v[s.v.length-1];
      g+=`<text x="${{W-PAD.r+7}}" y="${{Y(last)+4}}" font-size="11.5" font-weight="600" fill="${{s.c}}">${{s.label}}</text>`;}}
  }}
  g+=`<line id="${{el}}-cross" x1="0" y1="${{PAD.t}}" x2="0" y2="${{H-PAD.b}}" stroke="var(--text-muted)" stroke-width="1" opacity="0"/>`;
  S(el).insertAdjacentHTML('afterbegin',
    `<svg viewBox="0 0 ${{W}} ${{H}}" preserveAspectRatio="xMidYMid meet" role="img">${{g}}</svg>`);
  return {{X,Y,H}};
}}

const modelSeries = D.models.map(m=>({{v:m.ah, c:`var(--s-${{m.name}})`, label:m.name}}));
const c1 = mkChart('c1',300,
  [{{v:D.actual,c:'var(--measured)',w:2.5,label:''}}].concat(modelSeries),
  scale([D.actual].concat(D.models.map(m=>m.ah)),0.08), {{fmt:v=>v.toFixed(1)}});

const errs = D.models.map(m=>({{v:m.ah.map((x,i)=>x-D.actual[i]), c:`var(--s-${{m.name}})`, label:m.name}}));
const c2 = mkChart('c2',210, errs, scale(errs.map(e=>e.v),0.12), {{fmt:v=>v.toFixed(2), zero:0}});

const c3 = mkChart('c3',120,[{{v:D.duty,c:'var(--text-secondary)',w:2}}],[-0.06,1.06],
  {{fmt:v=>v.toFixed(1), ticks:2}});

// ---- shared crosshair + tooltip
function wire(el,ttid,ch,rows){{
  const box=S(el), tt=S(ttid), svg=box.querySelector('svg'), cross=document.getElementById(el+'-cross');
  box.addEventListener('pointermove',e=>{{
    const r=svg.getBoundingClientRect(), px=(e.clientX-r.left)/r.width*W;
    const frac=(px-PAD.l)/(W-PAD.l-PAD.r);
    let i=Math.round(frac*(D.t.length-1)); i=Math.max(0,Math.min(D.t.length-1,i));
    cross.setAttribute('x1',ch.X(D.t[i])); cross.setAttribute('x2',ch.X(D.t[i]));
    cross.setAttribute('opacity','0.55');
    tt.innerHTML=`<div class="hd">${{D.t[i].toFixed(0)}} min · ${{D.rh[i].toFixed(1)}}% RH · ${{D.temp[i].toFixed(2)}}&deg;C</div><table>`
      + rows(i) + '</table>';
    tt.style.opacity='1';
    const w=tt.offsetWidth, left=e.clientX-r.left+14;
    tt.style.left=Math.min(left, r.width-w-6)+'px';
    tt.style.top=Math.max(4, e.clientY-r.top-tt.offsetHeight-12)+'px';
  }});
  box.addEventListener('pointerleave',()=>{{tt.style.opacity='0';cross.setAttribute('opacity','0');}});
}}
const rowsAH=i=>`<tr><td class="k">measured</td><td class="v">${{F(D.actual[i])}}</td></tr>`
  + D.models.map(m=>`<tr><td class="k"><span class="dot" style="display:inline-block;background:var(--s-${{m.name}})"></span> ${{m.name}}</td><td class="v">${{F(m.ah[i])}}</td></tr>`).join('')
  + `<tr><td class="k">ambient</td><td class="v">${{F(D.amb[i],2)}}</td></tr>`;
const rowsErr=i=>D.models.map(m=>{{const e=m.ah[i]-D.actual[i];
  return `<tr><td class="k"><span class="dot" style="display:inline-block;background:var(--s-${{m.name}})"></span> ${{m.name}}</td><td class="v">${{e>=0?'+':''}}${{F(e)}}</td></tr>`;}}).join('');
wire('c1','tt1',c1,rowsAH); wire('c2','tt2',c2,rowsErr);
wire('c3','tt3',c3,i=>`<tr><td class="k">duty</td><td class="v">${{D.duty[i].toFixed(2)}}</td></tr>`);

// ---- parameters + table view (relief for the light-mode contrast warn)
const keys=[...new Set(D.models.flatMap(m=>Object.keys(m.params)))];
S('params').innerHTML='<table class="data"><tr><th>model</th><th>par</th>'
  + keys.map(k=>`<th>${{k.replace('log','')}}</th>`).join('')+'</tr>'
  + D.models.map(m=>`<tr><td><span class="dot" style="display:inline-block;background:var(--s-${{m.name}})"></span> ${{m.name}}</td><td>${{m.par}}</td>`
    + keys.map(k=>`<td>${{m.params[k]!==undefined?F(m.params[k]):'&mdash;'}}</td>`).join('')+'</tr>').join('')
  + '</table>';
let rows='<table class="data"><tr><th>min</th><th>RH %</th><th>T &deg;C</th><th>duty</th><th>measured AH</th>'
  + D.models.map(m=>`<th>${{m.name}}</th>`).join('')+'</tr>';
for(let i=0;i<D.t.length;i+=30) rows+=`<tr><td>${{D.t[i].toFixed(0)}}</td><td>${{D.rh[i].toFixed(1)}}</td>`
  + `<td>${{D.temp[i].toFixed(2)}}</td><td>${{D.duty[i].toFixed(2)}}</td><td>${{F(D.actual[i])}}</td>`
  + D.models.map(m=>`<td>${{F(m.ah[i])}}</td>`).join('')+'</tr>';
S('tbl').innerHTML=rows+'</table>';
</script></body></html>''')
