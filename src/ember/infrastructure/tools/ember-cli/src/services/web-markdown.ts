// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// web-markdown.ts — dependency-free HTML -> markdown converter for WebFetch.
// Handles the structure a model needs (headings, links, lists, code, quotes, tables)
// and drops non-content (script/style/head/svg). Not a full HTML parser:
// malformed markup degrades to text rather than throwing.

import { decodeEntities } from './search/engines/html.ts';

const DROP_BLOCKS = /<(script|style|noscript|svg|template|head|iframe|canvas|select|button)\b[\s\S]*?<\/\1\s*>/gi;
const COMMENTS = /<!--[\s\S]*?-->/g;
const VOID = new Set(['br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr']);
const CELL_OPEN = '\u0001';
const CELL_CLOSE = '\u0002';

interface Frame { tag: string; href?: string; ordered?: boolean; n: number; buf: string }

function attr(raw: string, name: string): string | undefined {
  const m = new RegExp(`\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i').exec(raw);
  return m ? decodeEntities(m[1] ?? m[2] ?? m[3] ?? '') : undefined;
}

function absolutize(href: string | undefined, base?: string): string | undefined {
  if (!href) return undefined;
  if (/^(javascript:|#|data:)/i.test(href)) return undefined;
  try { return new URL(href, base).toString(); } catch { return href; }
}

export function htmlToMarkdown(html: string, baseUrl?: string): string {
  const titleMatch = /<title[^>]*>([\s\S]*?)<\/title\s*>/i.exec(html);
  const title = titleMatch ? decodeEntities(titleMatch[1]!).replace(/\s+/g, ' ').trim() : '';
  let src = html.replace(COMMENTS, '').replace(DROP_BLOCKS, '');
  const body = /<body\b[^>]*>([\s\S]*?)(?:<\/body\s*>|$)/i.exec(src);
  if (body) src = body[1]!;

  const stack: Frame[] = [{ tag: 'root', n: 0, buf: '' }];
  const top = (): Frame => stack[stack.length - 1]!;
  let inPre = false;
  const emit = (s: string): void => { top().buf += s; };
  const block = (s: string): void => emit(`\n\n${s}\n\n`);

  const tokenRe = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>|([^<]+)|</g;
  let m: RegExpExecArray | null;
  while ((m = tokenRe.exec(src)) !== null) {
    if (m[4] !== undefined) {
      const text = decodeEntities(m[4]);
      emit(inPre ? text : text.replace(/\s+/g, ' '));
      continue;
    }
    if (m[2] === undefined) { emit('<'); continue; }
    const closing = m[1] === '/';
    const tag = m[2].toLowerCase();
    const rawAttrs = m[3] ?? '';

    if (!closing) {
      if (tag === 'br') { emit('  \n'); continue; }
      if (tag === 'hr') { block('---'); continue; }
      if (tag === 'img') {
        const alt = attr(rawAttrs, 'alt');
        if (alt) emit(`![${alt}]`);
        continue;
      }
      if (VOID.has(tag)) continue;
      if (tag === 'pre') inPre = true;
      const f: Frame = { tag, n: 0, buf: '' };
      if (tag === 'a') f.href = absolutize(attr(rawAttrs, 'href'), baseUrl);
      if (tag === 'ol') f.ordered = true;
      stack.push(f);
      continue;
    }

    // closing tag: find nearest matching open frame; ignore stray closers
    let idx = stack.length - 1;
    while (idx > 0 && stack[idx]!.tag !== tag) idx--;
    if (idx === 0) continue;
    while (stack.length - 1 > idx) { const orphan = stack.pop()!; top().buf += orphan.buf; }
    const f = stack.pop()!;
    const inner = f.buf;
    const trimmed = inner.trim();
    switch (tag) {
      case 'h1': case 'h2': case 'h3': case 'h4': case 'h5': case 'h6':
        if (trimmed) block(`${'#'.repeat(Number(tag[1]))} ${trimmed.replace(/\s+/g, ' ')}`);
        break;
      case 'p': case 'div': case 'section': case 'article': case 'main': case 'header': case 'footer':
      case 'aside': case 'figure': case 'figcaption': case 'details': case 'summary': case 'form': case 'address':
        if (trimmed) block(trimmed);
        break;
      case 'strong': case 'b': emit(trimmed ? `**${trimmed}**` : ''); break;
      case 'em': case 'i': emit(trimmed ? `*${trimmed}*` : ''); break;
      case 'code': emit(inPre ? inner : trimmed ? '`' + trimmed + '`' : ''); break;
      case 'pre': inPre = false; block('```\n' + inner.replace(/^\n+|\s+$/g, '') + '\n```'); break;
      case 'blockquote': if (trimmed) block(trimmed.split('\n').map((l) => '> ' + l).join('\n')); break;
      case 'a': {
        const label = trimmed.replace(/\s+/g, ' ');
        emit(f.href && label ? `[${label}](${f.href})` : label);
        break;
      }
      case 'li': {
        const parent = stack.slice().reverse().find((x) => x.tag === 'ol' || x.tag === 'ul');
        let bullet = '-';
        if (parent?.ordered) { parent.n++; bullet = `${parent.n}.`; }
        const lines = trimmed.replace(/\n{2,}/g, '\n').split('\n');
        emit(`\n${bullet} ${lines[0]}${lines.slice(1).map((l) => '\n  ' + l).join('')}`);
        break;
      }
      case 'ul': case 'ol': block(inner.trim()); break;
      case 'tr': {
        const re = new RegExp(`${CELL_OPEN}([\\s\\S]*?)${CELL_CLOSE}`, 'g');
        const cells = [...inner.matchAll(re)].map((c) => c[1]!.replace(/\|/g, '\\|').trim());
        if (cells.length) emit(`\n| ${cells.join(' | ')} |\n`);
        break;
      }
      case 'td': case 'th': emit(`${CELL_OPEN}${trimmed.replace(/\s+/g, ' ')}${CELL_CLOSE}`); break;
      case 'table': block(inner.trim()); break;
      default: emit(inner);
    }
  }
  while (stack.length > 1) { const f = stack.pop()!; top().buf += f.buf; }

  const bodyMd = stack[0]!.buf
    .replace(/[\u0001\u0002]/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  return title && !bodyMd.includes(title) && !bodyMd.startsWith('# ') ? `# ${title}\n\n${bodyMd}`.trim() : bodyMd;
}
