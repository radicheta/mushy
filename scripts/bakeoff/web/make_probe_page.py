import json, datetime as dt
S='/tmp/claude-1000/-mnt-slime-kingdom-opt-mushy/d1f72193-43d8-47fc-899b-4a47c6e1dbe5/scratchpad/'
d=json.load(open(S+'sched.json'))
pts, segs = d['pts'], d['segs']
holds=[s for s in segs if s['kind']=='hold' and s['end']-s['start']>1]
sines=[s for s in segs if s['kind']=='sine']
rails=[h for h in holds if h['duty'] in (0.0,1.0)]
dw=[h['end']-h['start'] for h in holds]
stats=dict(hours=round(pts[-1][0]/60,1), segments=len(holds), sine_h=round(sum(s['end']-s['start'] for s in sines)/60,1),
           dwell=f"{round(min(dw))}-{round(max(dw))}", rails=len(rails), levels=len(holds)-len(rails),
           ramps=len([s for s in segs if s['kind']=='ramp']), cmds=len(pts))
payload=json.dumps({'pts':pts,'segs':segs,'t0':d['t0'],'stats':stats},separators=(',',':'))

html = '''<title>Duty Probe Schedule</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500&display=swap">
<style>
:root{
  --ground:#F5F7F6; --panel:#FFFFFF; --edge:#DDE3E1;
  --ink:#141917; --ink-2:#4A5553; --ink-3:#78827F;
  --trace:#0B6E64; --trace-soft:rgba(11,110,100,.13);
  --sine:#A96518; --sine-soft:rgba(169,101,24,.11);
  --rail:#8A3F3F; --grid:#E7ECEA;
  --mono:"IBM Plex Mono",ui-monospace,monospace;
  --sans:"IBM Plex Sans",system-ui,sans-serif;
  --disp:"Archivo","IBM Plex Sans",system-ui,sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0E1413; --panel:#151D1B; --edge:#26302E;
  --ink:#E8EEEC; --ink-2:#A3AFAC; --ink-3:#77837F;
  --trace:#4FC7B8; --trace-soft:rgba(79,199,184,.15);
  --sine:#E0A15A; --sine-soft:rgba(224,161,90,.13);
  --rail:#E08B8B; --grid:#1F2927;
}}
:root[data-theme="dark"]{
  --ground:#0E1413; --panel:#151D1B; --edge:#26302E;
  --ink:#E8EEEC; --ink-2:#A3AFAC; --ink-3:#77837F;
  --trace:#4FC7B8; --trace-soft:rgba(79,199,184,.15);
  --sine:#E0A15A; --sine-soft:rgba(224,161,90,.13);
  --rail:#E08B8B; --grid:#1F2927;
}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);font-family:var(--sans);
     font-size:15px;line-height:1.55;margin:0;padding:32px 22px 72px}
.wrap{max-width:1080px;margin:0 auto;display:flex;flex-direction:column;gap:26px}
header{display:flex;flex-direction:column;gap:8px}
.eyebrow{font-family:var(--mono);font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3)}
h1{font-family:var(--disp);font-weight:700;font-size:31px;line-height:1.1;margin:0;text-wrap:balance;letter-spacing:-.015em}
.lede{color:var(--ink-2);max-width:64ch;margin:0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(122px,1fr));gap:1px;
       background:var(--edge);border:1px solid var(--edge);border-radius:3px;overflow:hidden}
.stat{background:var(--panel);padding:13px 15px;display:flex;flex-direction:column;gap:3px}
.stat b{font-family:var(--mono);font-size:21px;font-weight:500;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.stat span{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3)}
.card{background:var(--panel);border:1px solid var(--edge);border-radius:3px;padding:18px 18px 10px}
.card h2{font-family:var(--disp);font-size:15px;font-weight:600;margin:0 0 2px;letter-spacing:.005em}
.card p.note{margin:0 0 14px;color:var(--ink-2);font-size:13.5px;max-width:74ch}
.chartbox{position:relative;overflow-x:auto}
svg{display:block;width:100%;height:auto;touch-action:none}
.key{display:flex;flex-wrap:wrap;gap:16px;margin:10px 0 6px;font-family:var(--mono);font-size:11.5px;color:var(--ink-2)}
.key i{display:inline-block;width:22px;height:9px;border-radius:1px;vertical-align:-1px;margin-right:6px}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:760px){.pair{grid-template-columns:1fr}}
.tip{position:absolute;pointer-events:none;opacity:0;transition:opacity .1s;
     background:var(--panel);border:1px solid var(--edge);border-radius:3px;padding:7px 10px;
     font-family:var(--mono);font-size:11.5px;line-height:1.5;white-space:nowrap;
     box-shadow:0 3px 14px rgba(0,0,0,.13);color:var(--ink)}
.tip b{font-weight:500;color:var(--trace)}
ul.check{margin:0;padding-left:18px;color:var(--ink-2);font-size:14px;display:flex;flex-direction:column;gap:6px}
ul.check b{color:var(--ink);font-weight:500}
footer{font-family:var(--mono);font-size:11.5px;color:var(--ink-3);border-top:1px solid var(--edge);padding-top:14px}
</style>
<div class="wrap">
<header>
  <div class="eyebrow">MUSHY-150 &middot; fc1 preflight</div>
  <h1>24-hour duty probe schedule</h1>
  <p class="lede">One dry run of <code>scripts/duty-probe.sh</code>, plotted before it goes near the chamber.
  This is the open-loop excitation five months of closed-loop operation cannot provide &mdash; the controller
  raises duty <em>because</em> RH fell, so cause and effect never separate in the corpus. Everything below is
  commanded duty against the virtual clock; the schedule is random, so check the shape, not the exact times.</p>
</header>

<div class="stats" id="stats"></div>

<section class="card">
  <h2>The whole run</h2>
  <p class="note">Commanded duty over 24 h. Level segments sit at or below 0.35 &mdash; roughly 2.5&times; the 0.137
  the chamber needs to hold steady, above which RH pins to the ceiling and the closed-loop guard takes over.
  A third of segments go to a rail (0 or 1) for the biggest available edge.</p>
  <div class="key">
    <span><i style="background:var(--trace)"></i>commanded duty</span>
    <span><i style="background:var(--sine-soft);border:1px solid var(--sine)"></i>sine block</span>
    <span><i style="background:var(--rail);height:2px"></i>rail (duty 1.0)</span>
  </div>
  <div class="chartbox" id="main"></div>
</section>

<div class="pair">
  <section class="card">
    <h2>Sine block, 60 min period</h2>
    <p class="note">Gain measured cleanly by lock-in: everything not at this frequency rejects out.
    A 140&nbsp;s dead time is only 14&deg; of phase here.</p>
    <div class="chartbox" id="z1"></div>
  </section>
  <section class="card">
    <h2>Sine block, 20 min period</h2>
    <p class="note">The same delay is 42&deg; of phase at this period &mdash; this is the block that
    separates transport delay from mixing.</p>
    <div class="chartbox" id="z2"></div>
  </section>
</div>

<section class="card">
  <h2>Hard steps, detail</h2>
  <p class="note">Two hours of ordinary segments. Steps carry the edge that pins dead time; one arrival in
  four is a 2&nbsp;min ramp instead, kept only to check the fitted model handles a moving input.</p>
  <div class="chartbox" id="z3"></div>
</section>

<section class="card">
  <h2>What to check before this runs</h2>
  <ul class="check">
    <li><b>Sine blocks are far apart.</b> Both in the same few hours means they are confounded with one time
    of day &mdash; that is a scheduling bug, and it happened on the first draw.</li>
    <li><b>No level segment above 0.35</b> outside the rails, or the guard spends the run overriding and
    writes closed-loop data into the one experiment built to avoid it.</li>
    <li><b>Dwells stay in 7&ndash;15 min.</b> Below ~3&times; the dead time consecutive responses overlap;
    above it thermal drift starts competing with the duty signal.</li>
    <li><b>Rails appear throughout,</b> not clustered &mdash; they are the largest edges in the run.</li>
  </ul>
</section>

<footer>Dry run &middot; virtual clock &middot; nothing sent to fc1. Regenerate with
<code>DRYRUN=1 ./scripts/duty-probe.sh dry 24</code></footer>
</div>
<script>
const D = __DATA__;
const S = D.stats;
document.getElementById('stats').innerHTML = [
  [S.hours + ' h', 'duration'], [S.segments, 'segments'], [S.dwell + ' min', 'dwell'],
  [S.rails, 'rail holds'], [S.levels, 'level holds'], [S.ramps, 'ramps'],
  [S.sine_h + ' h', 'sine'], [S.cmds, 'duty commands']
].map(([v, l]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join('');

const t0 = new Date(D.t0);
const clock = m => new Date(t0.getTime() + m * 60000).toISOString().slice(11, 16) + 'Z';

function draw(el, m0, m1, opts) {
  const W = 1000, H = opts.h || 250, P = { t: 14, r: 14, b: 30, l: 40 };
  const x = m => P.l + (m - m0) / (m1 - m0) * (W - P.l - P.r);
  const y = d => P.t + (1 - d / 1.02) * (H - P.t - P.b);
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', opts.label);
  const add = (n, a, p) => { const e = document.createElementNS(ns, n);
    for (const k in a) e.setAttribute(k, a[k]); (p || svg).appendChild(e); return e; };

  // sine blocks behind everything
  D.segs.filter(s => s.kind === 'sine' && s.end > m0 && s.start < m1).forEach(s => {
    add('rect', { x: x(Math.max(s.start, m0)), y: P.t,
      width: x(Math.min(s.end, m1)) - x(Math.max(s.start, m0)),
      height: H - P.t - P.b, fill: 'var(--sine-soft)', stroke: 'var(--sine)',
      'stroke-width': .8, 'stroke-dasharray': '3 3' });
  });

  [0, .35, 1].forEach(v => {
    add('line', { x1: P.l, x2: W - P.r, y1: y(v), y2: y(v), stroke: 'var(--grid)', 'stroke-width': 1 });
    add('text', { x: P.l - 8, y: y(v) + 4, 'text-anchor': 'end', fill: 'var(--ink-3)',
      'font-family': 'var(--mono)', 'font-size': 11 }).textContent = v.toFixed(2);
  });
  const step = opts.tick;
  for (let m = Math.ceil(m0 / step) * step; m <= m1; m += step) {
    add('line', { x1: x(m), x2: x(m), y1: H - P.b, y2: H - P.b + 4, stroke: 'var(--ink-3)', 'stroke-width': 1 });
    add('text', { x: x(m), y: H - P.b + 18, 'text-anchor': 'middle', fill: 'var(--ink-3)',
      'font-family': 'var(--mono)', 'font-size': 11 }).textContent = clock(m);
  }

  // commanded duty is a step function: it holds until the next command
  const p = D.pts.filter(q => q[0] >= m0 - 30 && q[0] <= m1 + 30);
  let dpath = '', prev = null;
  p.forEach((q, i) => {
    const X = x(Math.min(Math.max(q[0], m0), m1)), Y = y(q[1]);
    if (i === 0) dpath = `M${X},${Y}`;
    else dpath += (q[2].startsWith('sine') || q[2] === 'ramp')
      ? `L${X},${Y}` : `L${X},${y(prev)}L${X},${Y}`;
    prev = q[1];
  });
  dpath += `L${x(m1)},${y(prev)}`;
  add('path', { d: dpath + `L${x(m1)},${y(0)}L${x(m0)},${y(0)}Z`, fill: 'var(--trace-soft)', stroke: 'none' });
  add('path', { d: dpath, fill: 'none', stroke: 'var(--trace)', 'stroke-width': 2,
    'stroke-linejoin': 'round', 'stroke-linecap': 'round' });

  // rails at full duty get their own mark -- they are the largest edges in the run
  D.segs.filter(s => s.kind === 'hold' && s.duty === 1 && s.end > m0 && s.start < m1).forEach(s => {
    add('line', { x1: x(Math.max(s.start, m0)), x2: x(Math.min(s.end, m1)), y1: y(1), y2: y(1),
      stroke: 'var(--rail)', 'stroke-width': 3, 'stroke-linecap': 'round' });
  });

  el.appendChild(svg);
  if (!opts.hover) return;

  const tip = document.createElement('div'); tip.className = 'tip'; el.appendChild(tip);
  const cross = add('line', { x1: 0, x2: 0, y1: P.t, y2: H - P.b, stroke: 'var(--ink-3)',
    'stroke-width': 1, 'stroke-dasharray': '2 3', opacity: 0 });
  const dot = add('circle', { r: 4, fill: 'var(--trace)', stroke: 'var(--panel)', 'stroke-width': 2, opacity: 0 });
  svg.addEventListener('pointermove', ev => {
    const r = svg.getBoundingClientRect();
    const m = m0 + (ev.clientX - r.left) / r.width * W / (W - P.l - P.r) * (m1 - m0)
              - P.l / (W - P.l - P.r) * (m1 - m0);
    let q = D.pts[0];
    for (const c of D.pts) { if (c[0] <= m) q = c; else break; }
    cross.setAttribute('x1', x(m)); cross.setAttribute('x2', x(m)); cross.setAttribute('opacity', 1);
    dot.setAttribute('cx', x(m)); dot.setAttribute('cy', y(q[1])); dot.setAttribute('opacity', 1);
    tip.style.opacity = 1;
    tip.innerHTML = `${clock(m)}<br><b>duty ${q[1].toFixed(3)}</b><br>${q[2]}`;
    const left = ev.clientX - r.left;
    tip.style.left = Math.min(Math.max(left + 14, 0), r.width - tip.offsetWidth - 4) + 'px';
    tip.style.top = '10px';
  });
  svg.addEventListener('pointerleave', () => {
    tip.style.opacity = 0; cross.setAttribute('opacity', 0); dot.setAttribute('opacity', 0);
  });
}

const sines = D.segs.filter(s => s.kind === 'sine');
draw(document.getElementById('main'), 0, D.pts[D.pts.length - 1][0],
     { h: 260, tick: 120, hover: true, label: 'Commanded duty over the full 24 hour run' });
[['z1', sines[0]], ['z2', sines[1]]].forEach(([id, s], i) => {
  if (!s) return;
  draw(document.getElementById(id), s.start - 12, s.end + 12,
       { h: 210, tick: i ? 20 : 60, hover: true, label: 'Sine block detail' });
});
const steps = D.segs.find(s => s.kind === 'hold' && s.start > (sines[0] ? sines[0].end + 60 : 300));
draw(document.getElementById('z3'), steps.start, steps.start + 120,
     { h: 220, tick: 30, hover: true, label: 'Two hours of stepped segments' });
</script>'''

open(S+'duty-probe-schedule.html','w').write(html.replace('__DATA__', payload))
print('wrote', len(html)+len(payload), 'bytes')
