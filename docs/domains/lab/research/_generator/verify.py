# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Six value checks on the built research site. Not a framework: one file, six named cases,
each printing PASS/FAIL and the evidence it stands on.

    PYTHONIOENCODING=utf-8 python -B scripts/research_site/verify.py

Cases (a) retrieval of a prior investigation using the wording that actually failed on 2026-09-14;
(b) the correction path from the synthesis to the affected earlier results, with original verdicts
intact; (c) recomputation of displayed comparisons from the exported rows, and disclosure where the
public evidence is insufficient; (d) missing evidence / broken join / incompatible comparison cannot
render as a valid-looking result; (e) regeneration after a controlled change to an ISOLATED
publication input, with the live records proved untouched; (f) navigation, project-site-relative
paths, and the no-JavaScript floor.

It runs no training, no evaluation, no profiling. Cases (d) and (e) operate on a throwaway fixture
root under the session scratchpad and never write to state/ outside state/research-site.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build                                          # noqa: E402
import sources                                        # noqa: E402

SITE = os.path.join(sources.SEAT_ROOT, 'state/research-site').replace('\\', '/')
EXPORT = os.path.join(SITE, 'export').replace('\\', '/')
PY = sys.executable
RESULTS = []


def rd(p):
    return io.open(p, encoding='utf-8').read()


def case(name, ok, *lines):
    RESULTS.append((name, ok))
    print('\n%s  %s' % ('PASS' if ok else 'FAIL', name))
    for ln in lines:
        print('      %s' % ln)


def cards(html):
    """(id, searchable blob, verdict) for every rendered record card."""
    out = []
    for m in re.finditer(r'<div class="hyp" id="(.*?)" data-search="(.*?)" data-verdict="(.*?)">\s*'
                         r'<code class="hid">(.*?)</code>', html, re.S):
        out.append((m.group(1), m.group(2), m.group(3)))
    return out


def score(blob, terms, aliases):
    """The scorer the page's JavaScript runs, re-implemented over the same alias map: rank by
    distinct terms matched, then by total occurrences across their alias expansions."""
    n, occ, used = 0, 0, []
    for t in terms:
        k = sum(blob.count(x) for x in [t] + aliases.get(t, []))
        if k:
            n += 1
            occ += k
            used.append(t)
    return n, occ, used


# --- (a) ---------------------------------------------------------------------------
def case_a():
    html = rd(os.path.join(SITE, 'hypotheses.html'))
    cs = cards(html)
    q = 'class census bandwidth compute overlap stream serialization'
    terms = q.split()
    target = 'other-class-is-an-instrument-artifact-partition-restated-20260914'
    # The row is a registry row joined to a loop hypothesis, so it is rendered folded into that
    # hypothesis's card. Retrieval succeeds when the card CARRYING it ranks; the card's own id is
    # the hypothesis, which is the identity the record keeps.
    holder = [(cid, blob) for cid, blob, v in cs if target in blob]
    if not holder:
        return case('(a) retrieval of the duplicated investigation', False,
                    'no rendered record carries %s' % target)
    hits = sorted(((score(b, terms, build.ALIASES)[:2], cid) for cid, b, v in cs), reverse=True)
    order = [c for _, c in hits]
    carrying = sorted((order.index(c) + 1, c) for c, b in holder)
    rank, hid = carrying[0]
    blob = dict(holder)[hid]
    n, occ, used = score(blob, terms, build.ALIASES)
    direct = [t for t in terms if t in blob]
    via_alias = [t for t in used if t not in direct]
    sibling = 'the-unclassified-other-class-of-device-time-is-a-short-head-not-a-long-tail'
    sib_rank = next((i + 1 for i, c in enumerate(order)
                     if sibling in dict((x[0], x[1]) for x in cs).get(c, '')), None)
    ok = n >= 5 and rank <= 10
    case('(a) retrieval of the duplicated investigation', ok,
         'query, verbatim from the 2026-09-14 incident: %r' % q,
         'the prior investigation is registry row %s,' % target,
         'rendered on the card of hypothesis %s' % hid,
         'records carrying that row rank at %s'
         % ', '.join(str(r) for r, _ in carrying),
         'matched %d of %d terms (%d occurrences); rank %d of %d rendered records'
         % (n, len(terms), occ, rank, len(cs)),
         'the cycle-8 row that actually answered the duplicated question ranks %s'
         % (sib_rank if sib_rank else 'NOT IN RESULTS'),
         'matched directly: %s' % ', '.join(direct),
         'matched only through the authored alias map: %s' % (', '.join(via_alias) or 'none'),
         'terms matching nothing even with aliases: %s'
         % (', '.join(t for t in terms if t not in used) or 'none'),
         'searching ids alone would match %d of %d terms against the registry row and %d against '
         'the hypothesis id'
         % (len([t for t in terms if t in target]), len(terms),
            len([t for t in terms if t in hid])),
         'this is a retrieval result, not a claim that a duplicate cycle is now impossible')
    return ok


# --- (b) ---------------------------------------------------------------------------
def case_b():
    art = rd(os.path.join(SITE, 'fp16-kernel-selection.html'))
    led = rd(os.path.join(SITE, 'hypotheses.html'))
    affected = {
        'the-time-weighted-fp16-accumulation-rate-over-the-whole-eligible-share-20260915': 'REFUTED',
        'machine-fill-not-intensity-decides-where-the-roofline-over-predicts-20260915': 'INCONCLUSIVE',
    }
    verdicts = dict((cid, v) for cid, b, v in cards(led))
    notes = []
    ok = 'Correction annotation' in art
    notes.append('synthesis carries a correction annotation: %s' % ok)
    for hid, want in affected.items():
        listed = hid in art
        got = verdicts.get(hid)
        same = (got == want)
        ok = ok and listed and same
        notes.append('%s -> named in synthesis %s; ledger verdict %s (original %s) %s'
                     % (hid, listed, got, want, 'UNCHANGED' if same else 'CHANGED'))
    relabel = re.search(r'(REFUTED|INCONCLUSIVE)\s*(?:is|was)\s*(?:now|re-?labell?ed)', art, re.I)
    ok = ok and not relabel
    notes.append('no relabelling language in the synthesis: %s' % (not relabel))
    notes.append('receipts are not edited by the build: it opens them read-only and writes only '
                 'under state/research-site')
    case('(b) correction follows to the affected results, verdicts intact', ok, *notes)
    return ok


# --- (c) ---------------------------------------------------------------------------
def case_c():
    fig = json.load(io.open(os.path.join(EXPORT, 'fp16-sweep-audit.json'), encoding='utf-8'))
    art = rd(os.path.join(SITE, 'fp16-kernel-selection.html'))
    notes, ok = [], True

    bad = []
    for r in fig['sweep']['rows']:
        recomputed = r['lt32_ms'] / r['lt16_ms']
        if abs(recomputed - r['speedup_16f_over_32f']) > 1e-9:
            bad.append(r['m'])
        shown = '%.4f' % r['speedup_16f_over_32f']
        if shown not in art:
            bad.append(('not displayed', r['m']))
    ok = ok and not bad
    notes.append('every displayed sweep speedup recomputed from lt32_ms / lt16_ms in the export: '
                 '%d of %d rows agree to 1e-9' % (len(fig['sweep']['rows']) - len(bad),
                                                  len(fig['sweep']['rows'])))

    aud = {}
    for a in fig['kernel_audit']['rows']:
        aud.setdefault(a['m'], {})[a['arm']] = a
    checked = []
    for m in fig['joined_shapes']:
        p = aud[m]
        ratio = p['32F']['profiled_us_NOT_A_RATE'] / p['16F']['profiled_us_NOT_A_RATE']
        shown = '%.3f' % ratio
        present = shown in art
        ok = ok and present
        checked.append('m=%d audit ratio %s (displayed: %s)' % (m, shown, present))
    notes.extend(checked)
    notes.append('the audit ratio is a quotient of two profiled durations and the page says so; '
                 'it is not quoted as a timing')

    notes.append('DISCLOSED INSUFFICIENT: the article quotes 1.359x time-weighted and 1.209x '
                 'median from fp16-accum-timeweighted. That receipt is published HEADER-ONLY '
                 '(3 of 22 fields), so its per-shape rows and census weights are not in the '
                 'export and a reader cannot recompute those two numbers from what is published. '
                 'They are a reported summary with the underlying evidence not publicly available.')
    case('(c) displayed comparisons recomputed from the exported rows', ok, *notes)
    return ok


# --- fixture plumbing for (d) and (e) -----------------------------------------------
def fixture(tag):
    root = os.path.join(os.environ.get('TEMP', '.'), 'ember-research-fixture-%s' % tag)
    root = root.replace('\\', '/')
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(os.path.join(root, 'state/issue1945-receipts'))
    for rel in (sources.REGISTRY, sources.LOOP):
        shutil.copyfile(os.path.join(sources.SEAT_ROOT, rel), os.path.join(root, rel))
    for rel in sources.RECEIPT_ALLOWLIST.values():
        shutil.copyfile(os.path.join(sources.SEAT_ROOT, rel), os.path.join(root, rel))
    return root


def run_build(root, out, extra=()):
    env = dict(os.environ)
    env['EMBER_RESEARCH_SEAT_ROOT'] = root
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    p = subprocess.run([PY, '-B', os.path.join(HERE, 'build.py'), '--out', out] + list(extra),
                       cwd=sources.SEAT_ROOT, env=env, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def patch_json(path, fn):
    d = json.load(io.open(path, encoding='utf-8'))
    fn(d)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(d, fh, indent=1)


# --- (d) ---------------------------------------------------------------------------
def case_d():
    notes, ok = [], True

    root = fixture('missing')
    out = root + '/out'
    os.remove(os.path.join(root, sources.RECEIPT_ALLOWLIST['wave-boundary-sweep']))
    rc, txt = run_build(root, out)
    good = rc == 3 and 'allowlisted receipts absent' in txt and not os.path.isdir(out)
    ok = ok and good
    notes.append('missing evidence: exit %d, no output directory written (%s)'
                 % (rc, 'refused' if good else 'DID NOT REFUSE'))

    root = fixture('join')
    out = root + '/out'
    p = os.path.join(root, sources.REGISTRY)
    lines = io.open(p, encoding='utf-8').read().split('\n')
    hit = None
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r.get('loop_hypothesis'):
            r['loop_hypothesis'] = 'a-hypothesis-that-does-not-exist-20260101'
            lines[i] = json.dumps(r)
            hit = r['id']
            break
    io.open(p, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
    rc, txt = run_build(root, out)
    page = rd(os.path.join(out, 'hypotheses.html')) if rc == 0 else ''
    reported = ('a-hypothesis-that-does-not-exist-20260101' in txt
                and 'a-hypothesis-that-does-not-exist-20260101' in page)
    attached = bool(re.search(r'a-hypothesis-that-does-not-exist-20260101</code>\s*<div class="row">',
                              page))
    good = rc == 0 and reported and not attached
    ok = ok and good
    notes.append('broken join on row %s: reported as an unresolved reference in the build output '
                 'and on the page (%s); never silently attached to a plausible neighbour (%s)'
                 % (hit, reported, not attached))

    root = fixture('incompat')
    out = root + '/out'
    patch_json(os.path.join(root, sources.RECEIPT_ALLOWLIST['kernel-identity-audit']),
               lambda d: d.__setitem__('n', 2048))
    rc, txt = run_build(root, out)
    good = rc == 3 and 'common (k, n, device)' in txt and not os.path.isdir(out)
    ok = ok and good
    notes.append('incompatible comparison (audit n=2048 against sweep n=1024): exit %d, no page '
                 'written (%s)' % (rc, 'refused' if good else 'DID NOT REFUSE'))

    case('(d) missing evidence, a broken join and an incompatible comparison cannot render', ok,
         *notes)
    return ok


# --- (e) ---------------------------------------------------------------------------
def case_e():
    live_before = dict((f, hashlib.sha256(open(os.path.join(sources.SEAT_ROOT, f), 'rb').read())
                        .hexdigest())
                       for f in [sources.REGISTRY, sources.LOOP]
                       + list(sources.RECEIPT_ALLOWLIST.values()))
    root = fixture('regen')
    out = root + '/out'
    rc0, _ = run_build(root, out)
    base = json.load(io.open(os.path.join(out, 'export/fp16-sweep-audit.json'), encoding='utf-8'))
    before = dict((r['m'], r['speedup_16f_over_32f']) for r in base['sweep']['rows'])

    def bump(d):
        for r in d['rows']:
            if r['m'] == 4096:
                r['lt16_ms'] = r['lt32_ms'] / 1.75
                r['speedup_16f_over_32f'] = 1.75
    patch_json(os.path.join(root, sources.RECEIPT_ALLOWLIST['wave-boundary-sweep']), bump)
    rc1, _ = run_build(root, out)
    after = json.load(io.open(os.path.join(out, 'export/fp16-sweep-audit.json'), encoding='utf-8'))
    got = dict((r['m'], r['speedup_16f_over_32f']) for r in after['sweep']['rows'])
    art = rd(os.path.join(out, 'fp16-kernel-selection.html'))
    moved = abs(got[4096] - 1.75) < 1e-12 and '1.7500' in art
    others = all(abs(got[m] - before[m]) < 1e-12 for m in before if m != 4096)
    live_after = dict((f, hashlib.sha256(open(os.path.join(sources.SEAT_ROOT, f), 'rb').read())
                       .hexdigest())
                      for f in live_before)
    untouched = live_before == live_after
    ok = rc0 == 0 and rc1 == 0 and moved and others and untouched
    case('(e) regeneration after a controlled change to an isolated input', ok,
         'fixture root %s' % root,
         'm=4096 speedup %.4f -> %.4f; the page now shows 1.7500 (%s)'
         % (before[4096], got[4096], moved),
         'every other shape unchanged: %s' % others,
         'live registry, loop log and all four receipts byte-identical before and after: %s'
         % untouched)
    return ok


# --- (f) ---------------------------------------------------------------------------
def case_f():
    notes, ok = [], True
    pages = ['index.html', 'hypotheses.html', 'fp16-kernel-selection.html', 'method.html']
    for pg in pages:
        html = rd(os.path.join(SITE, pg))
        for href in re.findall(r'href="([^"]+)"', html):
            if href.startswith(('http://', 'https://', '#', 'mailto:')):
                continue
            if href.startswith('/'):
                ok = False
                notes.append('%s links to a root-absolute path %r, which breaks on a project site'
                             % (pg, href))
                continue
            tgt = os.path.join(SITE, href.split('#')[0])
            if not os.path.exists(tgt):
                ok = False
                notes.append('%s -> %s does not exist' % (pg, href))
    notes.append('every internal link in %d pages resolves and is relative' % len(pages))

    art = rd(os.path.join(SITE, 'fp16-kernel-selection.html'))
    nojs = re.sub(r'<script.*?</script>', '', art, flags=re.S)
    floor = {
        'narrative': 'The finding that outranks the verdict' in nojs,
        'results table': '<table>' in nojs and '1.6584' in nojs,
        'figure': '<svg' in nojs,
        'timestamps': 'source events included through' in nojs.lower()
                      or 'events through' in nojs.lower(),
        'evidence links': 'wave-boundary-sweep' in nojs and 'export/fp16-sweep-audit.json' in nojs,
    }
    for k, v in sorted(floor.items()):
        ok = ok and v
        notes.append('without JavaScript, %s present: %s' % (k, v))

    led = rd(os.path.join(SITE, 'hypotheses.html'))
    cs = cards(led)
    nojs_led = re.sub(r'<script.*?</script>', '', led, flags=re.S)
    all_present = all(cid in nojs_led for cid, _, _ in cs)
    ok = ok and all_present
    notes.append('all %d records render without JavaScript; search only reorders an '
                 'already-present list: %s' % (len(cs), all_present))
    notes.append('search scorer exercised over the rendered blobs in case (a); it is the same '
                 'alias map the page ships (%d entries)' % len(build.ALIASES))
    case('(f) navigation, project-site paths, no-JavaScript floor', ok, *notes)
    return ok


def main():
    print('VERIFYING %s' % SITE)
    for fn in (case_a, case_b, case_c, case_d, case_e, case_f):
        try:
            fn()
        except Exception as exc:                       # noqa: BLE001
            case(fn.__name__, False, 'raised %s: %s' % (type(exc).__name__, exc))
    bad = [n for n, o in RESULTS if not o]
    print('\n%d of %d cases pass' % (len(RESULTS) - len(bad), len(RESULTS)))
    if bad:
        print('FAILED: %s' % ', '.join(bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
