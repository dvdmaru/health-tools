"""rowctx.py <slug>：把 criteria／history／interference 每一列連同快照裡引句前後文 dump 成 markdown，
供查核席逐列核對（二審 SOP 見 MODEL.md §1-1）。用法：python3 scripts/audit-rowctx.py blood-pressure → .audit/<slug>-rows.md（.audit/ 已 gitignore）"""
import json, pathlib, re, sys, subprocess, html
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / '.audit'; OUT.mkdir(exist_ok=True)
slug = sys.argv[1]
manifest = {m['id']: m for m in json.loads((ROOT / 'data/sources/manifest.json').read_text())}
_cache = {}
def text_of(doc_id):
    if doc_id in _cache: return _cache[doc_id]
    m = manifest.get(doc_id)
    if not m or not m['local_path']: _cache[doc_id] = None; return None
    p = ROOT / m['local_path']
    if not p.exists(): _cache[doc_id] = None; return None
    if m['doc_type'] == 'pdf':
        t = subprocess.run(['pdftotext', '-layout', str(p), '-'], capture_output=True, text=True).stdout
    else:
        t = p.read_text(errors='replace')
        if m['doc_type'] == 'html':
            t = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', t, flags=re.S | re.I)
            t = html.unescape(re.sub(r'<[^>]+>', ' ', t))
    _cache[doc_id] = t; return t
def ctx(doc_id, quote, width=350):
    t = text_of(doc_id)
    if t is None: return '（快照不在本機：licensed 快照未落地或路徑缺）'
    if not quote: return ''
    # 空白不敏感搜尋
    pat = r'\s*'.join(re.escape(ch) for ch in re.sub(r'\s+', '', quote)[:60])
    m = re.search(pat, t)
    if not m: return '⚠️ 引句前 60 字在快照找不到（收據 gate 是用整句 norm 比對，可能是切片差異）'
    s, e = max(0, m.start() - width), min(len(t), m.end() + width)
    return re.sub(r'[ \t]+', ' ', t[s:e]).strip()
lines = [f'# {slug} 全列 dump（自動產生，供查核）\n']
for kind, fn in [('criteria', f'{slug}.json'), ('history', f'{slug}-history.json'), ('interference', f'{slug}-interference.json')]:
    rows = json.loads((ROOT / 'data/criteria' / fn).read_text())
    lines.append(f'\n## {kind}（{len(rows)} 列）\n')
    for i, r in enumerate(rows):
        rid = r.get('id', f'#{i}')
        meta = {k: v for k, v in r.items() if k not in ('quote', 'quote_extra', 'corroboration', 'note')}
        lines.append(f'\n### {kind} {rid}\n')
        lines.append('```json\n' + json.dumps(meta, ensure_ascii=False, indent=1) + '\n```')
        lines.append(f'- quote: `{r.get("quote","")}`')
        for q in r.get('quote_extra', []) or []: lines.append(f'- quote_extra: `{q}`')
        for c in r.get('corroboration', []) or []: lines.append(f'- corroboration[{c.get("doc_id")}]: `{c.get("quote")}`')
        if r.get('note'): lines.append(f'- note: {r["note"]}')
        lines.append('- 快照上下文：\n\n> ' + ctx(r.get('doc_id'), r.get('quote', '')).replace('\n', '\n> '))
out = OUT / f'{slug}-rows.md'
out.write_text('\n'.join(lines) + '\n'); print(out, out.stat().st_size, 'bytes')
