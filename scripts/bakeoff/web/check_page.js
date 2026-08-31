// Executes a generated page's <script> against a stub DOM and counts the
// <path> elements each chart produced. `node --check` only proves the syntax
// parses -- it cannot catch a chart that renders nothing, which is exactly
// what happened when x/target/duty_at became shared arrays and the chart code
// kept indexing them per-horizon: valid JS, HTTP 200, zero lines drawn.
//
//   node scripts/bakeoff/web/check_page.js scripts/bakeoff/web/rolling.html
const fs = require('fs');
const html_src = fs.readFileSync(process.argv[2], 'utf8');
const js = html_src.match(/<script>([\s\S]*?)<\/script>/)[1];
const html = {}, els = {};
const mk = id => ({ id, innerHTML: '', textContent: '', style: {},
  insertAdjacentHTML(pos, s) { html[this.id] = (html[this.id] || '') + s;
    for (const m of s.matchAll(/id="([^"]+)"/g)) if (!(m[1] in els)) els[m[1]] = mk(m[1]); },
  addEventListener() {},
  querySelector: () => ({ getBoundingClientRect: () => ({ left: 0, top: 0, width: 1000, height: 250 }) }),
  offsetWidth: 100, offsetHeight: 50, setAttribute() {}, getAttribute() {} });
globalThis.document = { getElementById: id => (els[id] = els[id] || mk(id)), querySelector: () => mk('x') };
new Function('html', 'els', js)(html, els);
const counts = Object.entries(html).map(([k, v]) => [k, (v.match(/<path /g) || []).length]);
const empty = counts.filter(([k, n]) => n === 0 && k !== 'panels' && k !== 'tbl' && k !== 'params');
console.log(JSON.stringify(counts));
if (empty.length) { console.error('EMPTY CHARTS:', empty.map(e => e[0]).join(', ')); process.exit(1); }
console.log('OK: every chart drew at least one path');
