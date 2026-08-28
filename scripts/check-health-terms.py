#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-health-terms.py — 健康內容禁詞 gate。

資料源：config/banned-terms.json（Style Spec v1 §3 五類禁詞逐條落地）。
掃描對象：articles/**/*.md 的正文（去 frontmatter）與 public-health/**/*.html 的可見文字
（去 script/style 與標籤）。

判定
----
- level=absolute 命中且未被放行 → 印 FAIL，整支腳本 exit 1。
- level=conditional 命中且未被放行 → 印 WARN，**exit 0**：這類詞在特定條件下合法
  （轉述指引原文並附出處、語氣已降級等），機器判不出來，交人工判定。
- 放行有兩種：
  1. 全域例外語境（config 的 exceptions）——目前只有 119／急診例外句型。
  2. 詞專屬白名單語境（該詞的 allow_context）——例如「成人預防保健」是服務名稱，
     裡面的「預防」不是療效宣稱。

☠️ 這道 gate 的已知邊界，寫在這裡免得下次有人以為它比實際更強：
- 119 例外的三要件裡，機器只驗得了句型（要件 2）。「前面有沒有先列出具體急症徵象」
  與「是不是用在非緊急情境」（要件 1、3）擋不住——句型對但用錯地方，這裡會放行。
- 產品類的品牌名與商品名無法窮舉，只有語境詞（保健食品等）能提示人去看。
- 語意強度鎖表（might/may/should…的中文定譯）不在本 gate 內：那是逐詞對照原文的
  人工核，不是 grep 得出來的東西。把它塞進來只會產生一堆假陽性，然後 gate 被關掉。

用法
----
    python3 scripts/check-health-terms.py                  # 掃預設兩個目錄
    python3 scripts/check-health-terms.py path/to/file.md  # 只掃指定檔案
    python3 scripts/check-health-terms.py --verbose        # 連放行的命中一起列出
"""
import argparse
import html as html_lib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "banned-terms.json"
DEFAULT_TARGETS = [("articles", "*.md"), ("public-health", "*.html")]

_FRONTMATTER = re.compile(r"^---\s*\n.*?\n---\s*\n", re.S)
_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def load_rules(path: pathlib.Path = CONFIG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_text(path: pathlib.Path) -> str:
    """回傳要掃描的正文。md 去 frontmatter；html 去 script/style 與標籤後還原實體字元。"""
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".md":
        return _FRONTMATTER.sub("", raw, count=1)
    if path.suffix.lower() in (".html", ".htm"):
        body = _SCRIPT_STYLE.sub(" ", raw)
        body = _TAG.sub(" ", body)
        return html_lib.unescape(body)
    return raw


def _spans(pattern: str, text: str) -> list:
    return [m.span() for m in re.finditer(pattern, text)]


def _inside(span, spans) -> bool:
    s, e = span
    return any(a <= s and e <= b for a, b in spans)


def _line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _excerpt(text: str, span, ctx: int = 24) -> str:
    s, e = span
    frag = text[max(0, s - ctx):min(len(text), e + ctx)]
    return re.sub(r"\s+", " ", frag).strip()


def scan(text: str, rules: dict) -> list:
    """回傳命中清單：dict(term, level, category, line, excerpt, exempt, exempt_by)。

    順序固定（terms 的宣告順序，同詞再依位置），輸出才是決定性的。
    """
    exempt_spans = []
    for exc in rules.get("exceptions", []):
        for sp in _spans(exc["pattern"], text):
            exempt_spans.append((sp, exc["id"]))

    hits = []
    for entry in rules.get("terms", []):
        pattern = entry.get("pattern") or re.escape(entry["term"])
        allow_spans = []
        for ctx_pattern in entry.get("allow_context", []):
            allow_spans.extend(_spans(ctx_pattern, text))
        for m in re.finditer(pattern, text):
            span = m.span()
            exempt_by = ""
            for sp, eid in exempt_spans:
                if _inside(span, [sp]):
                    exempt_by = eid
                    break
            if not exempt_by and _inside(span, allow_spans):
                exempt_by = "allow_context"
            hits.append({
                "term": entry["term"],
                "matched": m.group(0),
                "level": entry["level"],
                "category": entry["category"],
                "line": _line_no(text, span[0]),
                "excerpt": _excerpt(text, span),
                "exempt": bool(exempt_by),
                "exempt_by": exempt_by,
                "note": entry.get("note", ""),
            })
    return hits


def _rel(p: pathlib.Path) -> str:
    """顯示用相對路徑；不在 repo 內就原樣印出。"""
    try:
        return str(p.resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def collect_files(paths: list) -> list:
    files = []
    if paths:
        for raw in paths:
            p = pathlib.Path(raw)
            if p.is_dir():
                files.extend(sorted(q for q in p.rglob("*")
                                    if q.suffix.lower() in (".md", ".html", ".htm")))
            elif p.is_file():
                files.append(p)
            else:
                print(f"❌ 路徑不存在：{raw}", file=sys.stderr)
                sys.exit(2)
    else:
        for sub, glob in DEFAULT_TARGETS:
            d = ROOT / sub
            if d.exists():
                files.extend(sorted(d.rglob(glob)))
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="健康內容禁詞 gate（資料源 config/banned-terms.json）")
    ap.add_argument("paths", nargs="*", help="要掃的檔案或目錄（預設 articles/ 與 public-health/）")
    ap.add_argument("--verbose", action="store_true", help="連被放行的命中一起列出")
    args = ap.parse_args()

    rules = load_rules()
    cats = rules.get("categories", {})
    files = collect_files(args.paths)
    if not files:
        print("ℹ️  沒有可掃描的檔案（articles/ 與 public-health/ 皆空）——視為通過。")
        return 0

    n_fail = n_warn = n_exempt = 0
    for f in files:
        for h in scan(extract_text(f), rules):
            label = cats.get(h["category"], h["category"])
            loc = f"{_rel(f)}:{h['line']}"
            if h["exempt"]:
                n_exempt += 1
                if args.verbose:
                    print(f"⚪ EXEMPT {loc} [{label}] 「{h['matched']}」（放行依據：{h['exempt_by']}）")
                continue
            if h["level"] == "absolute":
                n_fail += 1
                print(f"🔴 FAIL   {loc} [{label}] 「{h['matched']}」（規則：{h['term']}）\n"
                      f"          …{h['excerpt']}…")
                if h["note"]:
                    print(f"          註：{h['note']}")
            else:
                n_warn += 1
                print(f"🟡 WARN   {loc} [{label}] 「{h['matched']}」（規則：{h['term']}）等人工判定\n"
                      f"          …{h['excerpt']}…")
                if h["note"]:
                    print(f"          註：{h['note']}")

    print(f"\n掃描 {len(files)} 個檔案：FAIL {n_fail}／WARN {n_warn}／放行 {n_exempt}")
    if n_fail:
        print("❌ 有絕對禁詞命中，不得發布。", file=sys.stderr)
        return 1
    if n_warn:
        print("⚠️  有需附條件的詞命中，請人工判定是否符合 Style Spec §3 的使用條件（不擋發布）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
