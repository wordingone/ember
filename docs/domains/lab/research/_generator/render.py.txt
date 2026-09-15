# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Render the publication bundle: HTML pages, one SVG figure, one compact JSON export.

NO-JAVASCRIPT CONTRACT. Every page's narrative, results, timestamps and evidence links are written
into the HTML by this module. JavaScript adds exactly one thing -- filtering an already-rendered
list -- and a reader with it disabled loses the filter and nothing else. Nothing is fetched at
render time in the browser and nothing is fetched at read time.

THE FIGURE JOIN IS EXPLICIT AND PARTIAL BY CONSTRUCTION. The sweep and the kernel audit are two
different experiments: the sweep is a repeated timing run and the audit ran under a profiler, whose
own receipt says no duration in it is a rate. They are joined ONLY on (m, k, n, device, arm) and
only where both actually measured the same shape. Where the audit has no row, the chart says so
rather than drawing an assumed tile.
"""
import html
import json
import math
import re

VERDICTS = ('SUPPORTED', 'REFUTED', 'INCONCLUSIVE')


def esc(s):
    return html.escape('' if s is None else str(s), quote=True)


def _para(text):
    """Turn a record's prose into paragraphs without inventing structure."""
    if not text:
        return ''
    blocks = [b.strip() for b in re.split(r'\n\s*\n', str(text)) if b.strip()]
    return ''.join('<p>%s</p>' % esc(b).replace('\n', '<br>') for b in blocks)


def _chip(verdict):
    v = (verdict or 'OPEN').upper()
    cls = {'SUPPORTED': 'v-sup', 'REFUTED': 'v-ref', 'INCONCLUSIVE': 'v-inc'}.get(v, 'v-open')
    return '<span class="chip %s">%s</span>' % (cls, esc(v))


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------
CSS = """
:root{
  --paper:#f7f6f3; --panel:#fffefb; --rule:#ddd9d0; --rule-2:#eae6de;
  --ink:#1b1c20; --ink-2:#4b4d55; --ink-3:#7c7f88;
  --amber:#a8621b; --amber-soft:#f0e3d2; --deep:#23252c;
  --mono-bg:#f1efe9;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --paper:#15161a; --panel:#1c1e23; --rule:#32353d; --rule-2:#262931;
  --ink:#e9e7e1; --ink-2:#b0b2ba; --ink-3:#83868f;
  --amber:#e0975a; --amber-soft:#3a2c1c; --deep:#e9e7e1;
  --mono-bg:#23262d;
}}
:root[data-theme="dark"]{
  --paper:#15161a; --panel:#1c1e23; --rule:#32353d; --rule-2:#262931;
  --ink:#e9e7e1; --ink-2:#b0b2ba; --ink-3:#83868f;
  --amber:#e0975a; --amber-soft:#3a2c1c; --deep:#e9e7e1;
  --mono-bg:#23262d;
}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);margin:0;
  font:400 16px/1.62 "Source Serif 4",Georgia,"Times New Roman",serif;}
.ui,button,input,select,th,.chip,.meta,nav,footer,.label{
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
code,kbd,.mono,.hid{font-family:"IBM Plex Mono",ui-monospace,Consolas,monospace;font-size:.86em;}
.wrap{max-width:1180px;margin:0 auto;padding-inline:20px;padding-block:0;}
a{color:var(--amber);text-decoration:none;border-bottom:1px solid transparent}
a:hover{border-bottom-color:currentColor}
a:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid var(--amber);outline-offset:2px}

header.site{border-bottom:1px solid var(--rule);background:var(--panel);
  padding-block:18px calc(18px + env(safe-area-inset-top,0px));}
header.site .wrap{display:flex;flex-wrap:wrap;gap:8px 22px;align-items:baseline}
.brand{font:600 19px/1.1 "IBM Plex Sans",sans-serif;letter-spacing:-.01em;color:var(--ink)}
.brand span{color:var(--amber)}
nav{display:flex;gap:18px;flex-wrap:wrap;font-size:14px}
nav a{color:var(--ink-2)}
nav a[aria-current="page"]{color:var(--ink);font-weight:600;border-bottom:1.5px solid var(--amber)}

main{padding-block:38px 10px}
h1{font:600 clamp(26px,4vw,36px)/1.18 "IBM Plex Sans",sans-serif;letter-spacing:-.02em;
   margin:0 0 10px;text-wrap:balance}
h2{font:600 21px/1.28 "IBM Plex Sans",sans-serif;margin:38px 0 12px;text-wrap:balance;
   padding-top:14px;border-top:1px solid var(--rule-2)}
h3{font:600 16px/1.3 "IBM Plex Sans",sans-serif;margin:24px 0 8px}
.lede{font-size:18px;color:var(--ink-2);max-width:62ch;margin:0 0 20px}
.prose{max-width:66ch}
.prose p{margin:0 0 14px}
.prose ol,.prose ul{max-width:64ch;padding-left:22px}
.prose li{margin:0 0 8px}

.label{font:600 11px/1 "IBM Plex Sans",sans-serif;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-3)}
.meta{font-size:13px;color:var(--ink-3)}
.chip{display:inline-block;font:600 10.5px/1 "IBM Plex Sans",sans-serif;letter-spacing:.09em;
  padding:5px 8px;border-radius:2px;white-space:nowrap;vertical-align:baseline}
.v-ref{background:var(--deep);color:var(--paper)}
.v-sup{background:transparent;color:var(--amber);border:1.5px solid var(--amber)}
.v-inc{background:transparent;color:var(--ink-3);border:1.5px dashed var(--ink-3)}
.v-open{background:var(--rule-2);color:var(--ink-2)}

.note{border-left:3px solid var(--amber);background:var(--amber-soft);padding:14px 16px;
  margin:20px 0;max-width:66ch;font-size:15px}
.note p{margin:0 0 10px} .note p:last-child{margin:0}
.note .label{color:var(--amber);display:block;margin-bottom:6px}

.panel{background:var(--panel);border:1px solid var(--rule);border-radius:3px;padding:16px 18px;margin:18px 0}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));margin:18px 0}
.stat{background:var(--panel);border:1px solid var(--rule);border-radius:3px;padding:13px 15px}
.stat b{display:block;font:600 24px/1.1 "IBM Plex Sans",sans-serif;font-variant-numeric:tabular-nums;
  margin-bottom:4px;letter-spacing:-.02em}

.tablewrap{overflow-x:auto;margin:16px 0;border:1px solid var(--rule);border-radius:3px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font-size:13.5px;font-family:"IBM Plex Sans",sans-serif}
th,td{text-align:left;padding:8px 11px;border-bottom:1px solid var(--rule-2);vertical-align:top}
th{font-weight:600;font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-3);
   white-space:nowrap;background:var(--mono-bg)}
tbody tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums;font-family:"IBM Plex Mono",monospace}
td.none{color:var(--ink-3);font-style:italic}

details{border-top:1px solid var(--rule-2);padding:10px 0}
details>summary{cursor:pointer;font:600 13px/1.4 "IBM Plex Sans",sans-serif;color:var(--ink-2);
  list-style:none;display:flex;gap:8px;align-items:baseline}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"+";color:var(--amber);font-weight:700;width:11px;flex:none}
details[open]>summary::before{content:"\\2212"}
details .body{padding:10px 0 4px 19px;font-size:14.5px;color:var(--ink-2);max-width:70ch}
details .body p{margin:0 0 10px}

.hyp{border:1px solid var(--rule);background:var(--panel);border-radius:3px;padding:15px 17px;margin:0 0 12px}
.hyp .hid{font-size:12.5px;color:var(--ink-3);word-break:break-all;display:block;margin-bottom:7px}
.hyp h3{margin:0 0 9px;font-size:15.5px;line-height:1.38}
.hyp .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:9px}
.hyp .snip{font-size:14px;color:var(--ink-2);margin:0 0 2px;max-width:82ch}
.nc{margin:10px 0 0;padding-left:18px;font-size:13.5px;color:var(--ink-2)}
.nc li{margin:0 0 6px}

.searchbar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--paper);
  padding:12px 0;border-bottom:1px solid var(--rule);margin-bottom:18px}
.searchbar .in{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input[type=search]{flex:1 1 280px;min-width:0;padding:9px 12px;font-size:15px;border-radius:3px;
  border:1px solid var(--rule);background:var(--panel);color:var(--ink);
  font-family:"IBM Plex Sans",sans-serif}
.filters{display:flex;gap:6px;flex-wrap:wrap}
.filters button{padding:7px 11px;font:600 11px/1 "IBM Plex Sans",sans-serif;letter-spacing:.07em;
  border:1px solid var(--rule);background:var(--panel);color:var(--ink-2);border-radius:2px;cursor:pointer}
.filters button[aria-pressed=true]{background:var(--deep);color:var(--paper);border-color:var(--deep)}
#count{font-size:13px;color:var(--ink-3);font-family:"IBM Plex Sans",sans-serif}
.nojs{font-size:13px;color:var(--ink-3);margin:8px 0 0}

figure{margin:22px 0;padding:0}
figure svg{display:block;width:100%;height:auto;max-width:100%}
figcaption{font-size:13.5px;color:var(--ink-2);margin-top:12px;max-width:74ch;
  font-family:"IBM Plex Sans",sans-serif;line-height:1.55}
.svgbox{background:var(--panel);border:1px solid var(--rule);border-radius:3px;padding:16px 12px}

footer{border-top:1px solid var(--rule);margin-top:48px;padding-block:22px
  calc(26px + env(safe-area-inset-bottom,0px));font-size:13px;color:var(--ink-3);
  font-family:"IBM Plex Sans",sans-serif}
footer .wrap>div{margin-bottom:6px}
@media (max-width:640px){ h2{margin-top:30px} .stat b{font-size:20px} }
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600&'
         'family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">')


def shell(title, current, body, stamp, standalone=True):
    nav = ''.join(
        '<a href="%s"%s>%s</a>' % (h, ' aria-current="page"' if k == current else '', esc(t))
        for k, h, t in (('index', 'index.html', 'Overview'),
                        ('ledger', 'hypotheses.html', 'Hypothesis ledger'),
                        ('article', 'fp16-kernel-selection.html', 'FP16 & kernel selection'),
                        ('method', 'method.html', 'How this page is made')))
    head = ('<title>%s</title>%s<style>%s</style>' % (esc(title), FONTS, CSS))
    page = (
        '<header class="site"><div class="wrap">'
        '<div class="brand">Ember <span>Research</span></div><nav class="ui">%s</nav>'
        '</div></header><main><div class="wrap">%s</div></main>'
        '<footer><div class="wrap">'
        '<div><strong>Source events included through</strong> %s &nbsp;&middot;&nbsp; '
        '<strong>export generated</strong> %s</div>'
        '<div>This page states what its export contains. It makes no claim about local events '
        'newer than the source snapshot above; establishing that would take a fresh source check, '
        'and a generation timestamp is not an evidence timestamp.</div>'
        '<div>Ember Research &mdash; a rendering of an existing research record. It is not an '
        'acceptance authority and moves no campaign gate.</div>'
        '</div></footer>' % (nav, body, esc(stamp['source_events_through']), esc(stamp['generated_at'])))
    if not standalone:
        return head + page
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '%s</head><body>%s</body></html>' % (head, page))


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
SEARCH_JS = """
(function(){
  var ALIAS = %s;
  var q=document.getElementById('q'), cards=[].slice.call(document.querySelectorAll('[data-search]'));
  var out=document.getElementById('count'), btns=[].slice.call(document.querySelectorAll('.filters button'));
  var active=null;
  cards.forEach(function(c){ c._t=(c.getAttribute('data-search')||'').toLowerCase();
                             c._v=(c.getAttribute('data-verdict')||'').toUpperCase(); });
  function expand(term){ var s=[term]; (ALIAS[term]||[]).forEach(function(a){ s.push(a); }); return s; }
  function run(){
    var raw=(q.value||'').toLowerCase().trim();
    var terms=raw?raw.split(/\\s+/):[], shown=0, used=[];
    cards.forEach(function(c){
      var okv = !active || c._v===active;
      var n=0, occ=0;
      terms.forEach(function(t){
        var k=0; expand(t).forEach(function(x){ k += c._t.split(x).length-1; });
        if(k){n++; occ+=k; if(used.indexOf(t)<0)used.push(t);} });
      var okq = !terms.length || n>0;
      c.hidden = !(okv&&okq);
      if(!c.hidden){shown++; c._score=n; c._occ=occ;}
    });
    if(terms.length){
      var vis=cards.filter(function(c){return !c.hidden;});
      vis.sort(function(a,b){return (b._score-a._score)||(b._occ-a._occ);});
      var p=vis.length?vis[0].parentNode:null;
      if(p) vis.forEach(function(c){p.appendChild(c);});
    }
    out.textContent = shown+' of '+cards.length+' shown'+
      (terms.length? ' \\u00b7 matched on '+used.length+' of '+terms.length+' term(s)':'');
  }
  q.addEventListener('input',run);
  btns.forEach(function(b){ b.addEventListener('click',function(){
    var v=b.getAttribute('data-v');
    active = (active===v)?null:v;
    btns.forEach(function(x){ x.setAttribute('aria-pressed', String(x.getAttribute('data-v')===active)); });
    run(); }); });
  run();
})();
"""


def ledger_page(hyps, registry, joinmeta, coverage, aliases, stamp):
    reg_by_hyp = {}
    for r in registry:
        if r.get('_hypothesis'):
            reg_by_hyp.setdefault(r['_hypothesis'], []).append(r)

    cards = []
    for h in sorted(hyps, key=lambda x: (x.get('last_ts') or ''), reverse=True):
        rows = reg_by_hyp.get(h['id'], [])
        blob = (h['_search'] + ' ' + ' '.join(r.get('_search', '') for r in rows)).lower()
        obs = h.get('observation') or ''
        snip = obs.strip().split('\n')[0][:300]
        rcpts = h.get('receipts') or []
        nc = h.get('not_closed')
        bits = ['<div class="hyp" id="%s" data-search="%s" data-verdict="%s">'
                % (esc(h['id']), esc(blob), esc(h.get('verdict') or '')),
                '<code class="hid">%s</code>' % esc(h['id']),
                '<div class="row">%s<span class="meta">stage %s &middot; %s events &middot; last %s</span></div>'
                % (_chip(h.get('verdict')), esc(h.get('stage')), len(h.get('events') or []),
                   esc(h.get('last_ts')))]
        if snip:
            bits.append('<p class="snip">%s%s</p>' % (esc(snip), '&hellip;' if len(obs) > 300 else ''))
        if h.get('criterion'):
            bits.append('<details><summary>Criterion, frozen before the run</summary>'
                        '<div class="body">%s</div></details>' % _para(h['criterion']))
        if h.get('criterion_supported_if'):
            bits.append('<details><summary>Supported if</summary><div class="body">%s</div></details>'
                        % _para(h['criterion_supported_if']))
        if h.get('observation'):
            bits.append('<details><summary>Observation that opened it</summary>'
                        '<div class="body">%s</div></details>' % _para(h['observation']))
        if h.get('explanation'):
            bits.append('<details><summary>Explanation offered</summary>'
                        '<div class="body">%s</div></details>' % _para(h['explanation']))
        if h.get('ruling'):
            bits.append('<details><summary>Ruling, quoting the frozen criterion</summary>'
                        '<div class="body">%s</div></details>' % _para(h['ruling']))
        if nc:
            bits.append('<details><summary>What the verdict does NOT close</summary>'
                        '<div class="body">%s</div></details>' % _para(nc))
        ev = []
        if h.get('instrument'):
            ev.append('<div><span class="label">Instrument</span> <code>%s</code></div>' % esc(h['instrument']))
        for rc in rcpts:
            ev.append('<div><span class="label">Receipt</span> <code>%s</code></div>' % esc(rc))
        if h.get('successor'):
            ev.append('<div><span class="label">Successor</span> <code>%s</code></div>' % esc(h['successor']))
        for r in rows:
            ev.append('<div><span class="label">Registry row</span> <code>%s</code> &mdash; %s</div>'
                      % (esc(r['id']), esc(r.get('status'))))
        if ev:
            bits.append('<details><summary>Evidence, instrument, successor</summary>'
                        '<div class="body">%s</div></details>' % ''.join(ev))
        bits.append('</div>')
        cards.append(''.join(bits))

    # Registry rows with no hypothesis get their own section -- never hidden, never merged in.
    orphan = [r for r in registry if not r.get('_hypothesis')]
    ocards = []
    for r in sorted(orphan, key=lambda x: x.get('date') or '', reverse=True):
        ocards.append(
            '<div class="hyp" id="%s" data-search="%s" data-verdict="">'
            '<code class="hid">%s</code>'
            '<div class="row"><span class="chip v-open">%s</span>'
            '<span class="meta">%s &middot; basis %s</span></div>'
            '<p class="snip">%s</p>'
            '<details><summary>Treatment, condition, evidence</summary><div class="body">%s%s%s</div></details>'
            '<details><summary>What it does NOT close</summary><div class="body">%s</div></details>'
            '</div>'
            % (esc(r['id']), esc(r.get('_search', '').lower()), esc(r['id']), esc(r.get('status')),
               esc(r.get('date')), esc(r.get('basis') or 'unstated'),
               esc(str(r.get('treatment') or '')[:280]),
               _para(r.get('treatment')), _para(r.get('condition')),
               '<div><span class="label">Evidence</span> <code>%s</code></div>' % esc(r.get('evidence')),
               _para('\n\n'.join(r['not_closed']) if isinstance(r.get('not_closed'), list)
                     else r.get('not_closed'))))

    cov = coverage_block(coverage, joinmeta)
    body = (
        '<h1>Hypothesis ledger</h1>'
        '<p class="lede">Every hypothesis in the loop log and every row in the attempt registry, '
        'searchable across the explanatory text rather than ids alone. A refuted route keeps its '
        '&ldquo;does not close&rdquo; list, which is how it stays reopenable.</p>'
        + cov +
        '<div class="searchbar"><div class="in">'
        '<input type="search" id="q" placeholder="Search criteria, observations, rulings, not-closed text…" '
        'aria-label="Search the research record">'
        '<div class="filters">%s</div><span id="count">%d hypotheses</span>'
        '</div><p class="nojs">Search filters an already-rendered list. Without JavaScript every '
        'record below is still present and readable.</p></div>'
        '<h2>Hypotheses &mdash; %d</h2>%s'
        '<h2>Registry rows with no loop hypothesis &mdash; %d</h2>'
        '<p class="meta">These predate the loop or were recorded directly. Shown separately '
        'because an inferred join would be a guess.</p>%s'
        % (''.join('<button type="button" data-v="%s" aria-pressed="false">%s</button>' % (v, v)
                   for v in VERDICTS),
           len(hyps), len(hyps), ''.join(cards), len(orphan), ''.join(ocards)))
    js = SEARCH_JS % json.dumps(aliases)
    return shell('Hypothesis ledger', 'ledger', body + '<script>%s</script>' % js, stamp)


def coverage_block(cov, joinmeta):
    r, l = cov['registry'], cov['loop']
    rc = cov['receipts']
    read = [x for x in rc if x['status'] == 'READ']
    absent = [x for x in rc if x['status'] != 'READ']
    san = cov['sanitizer']
    rows = ''.join(
        '<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td><td>%s</td><td>%s</td></tr>'
        % (esc(x['path']), x['records_in_source'], x['included'],
           esc(x['mtime_utc']), esc(', '.join(x['omitted_fields']) or 'none'))
        for x in (r, l))
    return (
        '<div class="panel"><span class="label">Source coverage</span>'
        '<div class="tablewrap"><table><thead><tr><th>Source snapshot</th><th>Records in source</th>'
        '<th>Included</th><th>Source modified (UTC)</th><th>Fields omitted</th></tr></thead>'
        '<tbody>%s</tbody></table></div>'
        '<p class="meta" style="margin-top:10px">%d receipts read by name from an allowlist '
        '(%s); no directory was walked and no receipt was read that is not named above. '
        '%d allowlisted receipts were absent. Joins: %d registry rows link a hypothesis explicitly, '
        '%d were matched on the evidence receipt filename, %d have no hypothesis and are listed '
        'separately, and %d name a hypothesis the loop log does not contain (reported, never '
        'attached to a plausible neighbour). Sanitizer removed %d host-account paths, normalized %d '
        'absolute local paths, replaced %d operator-name occurrences, and flagged %d '
        'credential-shaped strings.</p>'
        '<p class="meta"><strong>This is a selected subset, not the complete research history.</strong> '
        'The receipt store holds many more measurement files than the %d published here; those are '
        'referenced by name and are not publicly inspectable from this page.</p></div>'
        % (rows, len(read), esc(', '.join(x['key'] for x in read)), len(absent),
           joinmeta['explicit_loop_hypothesis_links'],
           joinmeta['links_inferred_from_evidence_filename'],
           joinmeta['registry_rows_with_no_hypothesis'], len(joinmeta['unresolved_references']),
           san['host_account_paths_removed'], san['absolute_local_paths_normalized'],
           san['operator_name_occurrences_replaced'], san['credential_shaped_strings_flagged'],
           len(read)))


# ---------------------------------------------------------------------------
# Figure: speedup vs m, with kernel identity shown ONLY where the audit measured it
# ---------------------------------------------------------------------------
def figure_svg(sweep, audit):
    srows = sweep['rows']
    arows = audit['rows']
    aud = {}
    for a in arows:
        aud.setdefault(a['m'], {})[a['arm']] = a

    W, H = 940, 430
    L, R, T, B = 62, 250, 26, 68
    xs = [r['m'] for r in srows]
    x0, x1 = math.log(min(xs)), math.log(max(xs))
    y0, y1 = 0.90, 1.80

    def px(m):
        return L + (math.log(m) - x0) / (x1 - x0) * (W - L - R)

    def py(v):
        return T + (y1 - v) / (y1 - y0) * (H - T - B)

    p = ['<svg viewBox="0 0 %d %d" role="img" xmlns="http://www.w3.org/2000/svg" '
         'aria-label="Measured speedup of the 16-bit compute-type request over the 32-bit request, '
         'against m, with kernel identity marked only at the five shapes the audit measured.">' % (W, H),
         '<style>'
         '.ax{stroke:var(--rule);stroke-width:1}.gr{stroke:var(--rule-2);stroke-width:1}'
         '.tk{fill:var(--ink-3);font:11px "IBM Plex Sans",sans-serif}'
         '.tkm{fill:var(--ink-3);font:11px "IBM Plex Mono",monospace}'
         '.ln{fill:none;stroke:var(--ink-2);stroke-width:1.6}'
         '.lg{fill:var(--ink-2);font:11.5px "IBM Plex Sans",sans-serif}'
         '.lgb{fill:var(--ink);font:600 11.5px "IBM Plex Sans",sans-serif}'
         '.kn{fill:var(--amber);font:600 10px "IBM Plex Mono",monospace}'
         '.dip{stroke:var(--amber);stroke-width:1.2;stroke-dasharray:3 3}'
         '.ttl{fill:var(--ink);font:600 12px "IBM Plex Sans",sans-serif}'
         '</style>']
    # gridlines + y ticks
    for v in (1.0, 1.2, 1.4, 1.6, 1.8):
        p.append('<line class="gr" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>' % (L, py(v), W - R, py(v)))
        p.append('<text class="tkm" x="%.1f" y="%.1f" text-anchor="end">%.1fx</text>' % (L - 8, py(v) + 4, v))
    p.append('<line class="ax" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>' % (L, py(y0), W - R, py(y0)))
    p.append('<line class="ax" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>' % (L, T, L, py(y0)))
    # parity line
    p.append('<line class="ax" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke-dasharray="2 4"/>'
             % (L, py(1.0), W - R, py(1.0)))
    # x ticks
    for m in xs:
        p.append('<line class="ax" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                 % (px(m), py(y0), px(m), py(y0) + 4))
    for m in (512, 1024, 2048, 4096, 8192, 16384):
        p.append('<text class="tkm" x="%.1f" y="%.1f" text-anchor="middle">%d</text>'
                 % (px(m), py(y0) + 18, m))
    p.append('<text class="tk" x="%.1f" y="%.1f" text-anchor="middle">m  (k = n = 1024, log scale)</text>'
             % ((L + W - R) / 2.0, H - 16))
    p.append('<text class="ttl" x="%.1f" y="%.1f">speedup: 16-bit compute-type request '
             'over 32-bit</text>' % (L, T - 8))
    # line
    p.append('<polyline class="ln" points="%s"/>' % ' '.join(
        '%.1f,%.1f' % (px(r['m']), py(r['speedup_16f_over_32f'])) for r in srows))
    # dip marker
    p.append('<line class="dip" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
             % (px(2048), T + 4, px(2048), py(y0)))
    p.append('<text class="kn" x="%.1f" y="%.1f" text-anchor="middle">dip, unexplained</text>'
             % (px(2048), T + 1))
    # points
    for r in srows:
        m, v = r['m'], r['speedup_16f_over_32f']
        joined = m in aud and '32F' in aud[m] and '16F' in aud[m]
        if joined:
            p.append('<rect x="%.1f" y="%.1f" width="8" height="8" fill="var(--amber)"/>'
                     % (px(m) - 4, py(v) - 4))
        else:
            p.append('<circle cx="%.1f" cy="%.1f" r="4" fill="var(--paper)" '
                     'stroke="var(--ink-2)" stroke-width="1.5"/>' % (px(m), py(v)))
    # right-hand kernel key, only for joined shapes
    y = T + 16
    p.append('<text class="lgb" x="%.1f" y="%.1f">Kernel actually selected</text>' % (W - R + 10, y))
    y += 13
    p.append('<text class="lg" x="%.1f" y="%.1f">(profiled audit; 5 shapes only)</text>' % (W - R + 10, y))
    y += 19
    for m in sorted(aud):
        if not (m in [r['m'] for r in srows]):
            continue
        a32, a16 = aud[m].get('32F'), aud[m].get('16F')
        if not (a32 and a16):
            continue
        p.append('<text class="lgb" x="%.1f" y="%.1f">m = %d</text>' % (W - R + 10, y, m))
        y += 14
        p.append('<text class="kn" x="%.1f" y="%.1f">32F tile %s</text>' % (W - R + 10, y, a32['tile_in_name']))
        y += 13
        p.append('<text class="kn" x="%.1f" y="%.1f">16F tile %s</text>' % (W - R + 10, y, a16['tile_in_name']))
        y += 18
    p.append('<rect x="%.1f" y="%.1f" width="8" height="8" fill="var(--amber)"/>' % (W - R + 10, y - 7))
    p.append('<text class="lg" x="%.1f" y="%.1f">kernel evidence</text>' % (W - R + 24, y))
    y += 16
    p.append('<circle cx="%.1f" cy="%.1f" r="4" fill="var(--paper)" stroke="var(--ink-2)" '
             'stroke-width="1.5"/>' % (W - R + 14, y - 4))
    p.append('<text class="lg" x="%.1f" y="%.1f">no kernel evidence</text>' % (W - R + 24, y))
    p.append('</svg>')
    return ''.join(p)


def figure_table(sweep, audit):
    aud = {}
    for a in audit['rows']:
        aud.setdefault(a['m'], {})[a['arm']] = a
    sw = dict((r['m'], r) for r in sweep['rows'])
    allm = sorted(set(list(sw)) | set(list(aud)))
    tr = []
    for m in allm:
        s, a = sw.get(m), aud.get(m, {})
        a32, a16 = a.get('32F'), a.get('16F')
        if s:
            sp = '%.4f' % s['speedup_16f_over_32f']
            spread = '%.3f / %.3f' % (s['spread_32f'], s['spread_16f'])
        else:
            sp, spread = '&mdash;', '&mdash;'
        if a32 and a16:
            k32 = '<code>%s</code>' % esc(a32['tile_in_name'])
            k16 = '<code>%s</code>' % esc(a16['tile_in_name'])
            same = 'same' if a32['kernel'] == a16['kernel'] else '<strong>different</strong>'
            ar = '%.3f' % (a32['profiled_us_NOT_A_RATE'] / a16['profiled_us_NOT_A_RATE'])
        else:
            k32 = k16 = same = ar = '<span class="none">no audit row</span>'
        tr.append('<tr><td class="num">%d</td><td class="num">%s</td><td class="num">%s</td>'
                  '<td>%s</td><td>%s</td><td>%s</td><td class="num">%s</td>'
                  '<td>%s</td></tr>'
                  % (m, sp, spread, k32, k16, same, ar,
                     'sweep only' if s and not (a32 and a16) else
                     ('audit only' if a32 and a16 and not s else 'both')))
    return ('<div class="tablewrap"><table><thead><tr>'
            '<th>m</th><th>sweep speedup</th><th>spread 32F / 16F</th>'
            '<th>32F tile</th><th>16F tile</th><th>kernel</th>'
            '<th>audit ratio<br>(profiled, not a rate)</th><th>measured in</th>'
            '</tr></thead><tbody>%s</tbody></table></div>' % ''.join(tr))
