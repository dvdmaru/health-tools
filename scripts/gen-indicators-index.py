#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen-indicators-index.py — /indicators/ 索引頁（public-health/indicators/index.html）。

輸入＝與 gen-indicator.py 完全相同的那批來源（articles/indicators/*.md ＋
data/criteria/<slug>.json／<slug>-history.json）；輸出＝一頁卡片式索引。

為什麼是獨立一支而不是塞進 gen-indicator.py：那支的職責是「一個 slug 一頁」，
索引是「全部 slug 一頁」——把跨頁彙總塞進單頁生成器，`gen-indicator.py <slug>`
的部分 build 就會拿殘缺的清單去覆蓋索引頁。兩支各自吃全量來源，互不干擾。

☠️ 卡片上的每個數字都是從同一批來源即時算出來的，不從指標頁的 HTML 反推、也不
另存一份彙總檔（判準層只存明細，不存統計）：

- 「判準 N 列」＝該 slug 的 criteria 檔裡 `indicator_id ∈ frontmatter 的
  indicator_ids` 且 `category ∈ gen.TABLE_CATEGORIES` 的列數。這條過濾與
  gen-indicator.py 的 build() 是同一份實作（直接引用它的常數），所以 N 恆等於
  那一頁判準表的列數。測試有一條就在驗這個等式。
- 「機構 K 家」＝同一批列的 distinct org（照 org 全名去重，不是短標籤）。
- 「來源 S 份」＝ frontmatter 的 sources 條目數。
- 「沿革最近一次」＝ <slug>-history.json 排除 status「未證實」後的最大 year
  （欄位名見 data/criteria/history-schema.json）。沒有 history 檔或全被排除
  ＝不顯示這一行，不寫「無」也不補 0。

缺判準檔就 SystemExit：索引頁上的一張卡等於宣稱「這個指標頁存在且有資料」，
資料不在就不能發半頁出去。

dormant（config/site.json 的 published 為 false）：
    頁面照生（要能看、能審），但不接線。翻 true 才把 {BASE}/indicators/ 放進
    sitemap part 與 llms.txt 的「## 指標頁」區塊第一行。

    ⚠️ 接線是「讀既有檔 → 改 → 寫回」而不是自己寫一份：gen-indicator.py 的
    wire_sitemap() 每次都重寫整個 part 檔，本腳本必須跑在它之後，否則索引 URL
    會被它蓋掉。llms.txt 同理（那個區塊整塊由它重寫）。

決定性：內容全由來源檔決定，不寫時間戳；接線是「先移除既有的同一行再插到最前」，
同輸入連跑幾次都 byte-identical。

跑序：build-articles.py → gen-indicator.py → **本腳本** → build-sitemap.py
用法：python3 scripts/gen-indicators-index.py
"""
import argparse
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 帶連字號的檔名不能 import，照 tests/ 的載法。gen 帶著它自己那份 healthlib
# 實例（hl.PUBLISHED 是模組級旗標），這裡直接沿用同一份——同一次 build 內
# 「導覽 gate」與「sitemap／llms 接線」必須吃同一個旗標，不能各持一份。
gen = _load("gen_indicator", "scripts/gen-indicator.py")
hl = gen.hl

esc = gen.esc

PAGE_TITLE = "指標索引"
# 頁首說明：直接講這頁是什麼。判準值本身在各指標頁上，這裡只交代這頁的邊界。
INTRO = "這頁列出本站已整理的健檢指標。每一頁把各機構的判準值並列，逐列標註機構、文件、版本與頁碼。"

INDEX_URL = f"{hl.BASE}/indicators/"
SITEMAP_OWNER = gen.SITEMAP_OWNER          # "indicators"（與指標頁共用同一個 part）
LLMS_HEAD = gen.LLMS_HEAD                  # "## 指標頁"
LLMS_LINE = f"- [{PAGE_TITLE}]({INDEX_URL})：本站已整理的指標一覽。"


# ---------- 卡片資料（全部由既有來源推導） ----------

DESC_LEN = 120


def _clip(text: str) -> str:
    """第①段第一段前 DESC_LEN 字；超長者補刪節號標明還有下文。"""
    return text[:DESC_LEN] + "…" if len(text) > DESC_LEN else text

def collect_cards(src_dir=None, criteria_dir=None) -> list:
    """回傳卡片 list（依 slug 字母序）。

    順序：articles/indicators/*.md 的 frontmatter 目前**沒有** order 欄（實查過
    五篇），所以一律 slug 字母序。☠️ 不在這裡發明一個沒人寫的 order 欄——
    「支援但永遠沒被填」的欄位＝下一個人以為排序可調、實際上動不了。
    """
    src_dir = pathlib.Path(src_dir) if src_dir else gen.SRC_DIR
    criteria_dir = pathlib.Path(criteria_dir) if criteria_dir else gen.CRITERIA_DIR

    files = sorted(src_dir.glob("*.md")) if src_dir.exists() else []
    cards = []
    for f in files:
        meta, h1, sections = gen.parse_article(f)
        slug = meta.get("slug") or f.stem
        ids, labels = gen.page_indicators(meta, slug)

        crit_path = criteria_dir / f"{slug}.json"
        if not crit_path.exists():
            raise SystemExit(
                f"❌ 索引頁：找不到判準明細 {crit_path}。索引上的一張卡等於宣稱"
                f"「/indicators/{slug}/ 存在且有資料」，資料不在就不生成半頁索引。")
        rows = [r for r in gen.load_json(crit_path)
                if r["indicator_id"] in ids and r["category"] in gen.TABLE_CATEGORIES]
        if not rows:
            raise SystemExit(
                f"❌ 索引頁：{slug}（{'、'.join(ids)}）沒有可渲染的判準列"
                "（TABLE_CATEGORIES 皆空）——gen-indicator.py 也生不出這一頁，"
                "索引不得掛一張連過去是 404 的卡。")

        # 沿革最近一次：未證實的列不算數（那些列在指標頁上也不渲染）。
        hp = criteria_dir / f"{slug}-history.json"
        years = [r["year"] for r in gen.load_json(hp)
                 if r.get("status") != "未證實" and isinstance(r.get("year"), int)] \
            if hp.exists() else []

        cards.append({
            "slug": slug,
            "title": meta.get("title", h1),
            "url": f"{hl.BASE}/indicators/{slug}/",
            "href": f"/indicators/{slug}/",
            # 多指標頁的短標籤只能來自 frontmatter（page_indicators 已驗過缺一即中止）；
            # 單指標頁沒有短標籤，用頁標題本身。
            "labels": [labels[i] for i in ids] if len(ids) > 1 else [meta.get("title", h1)],
            "n_rows": len(rows),
            "n_orgs": len({r["org"] for r in rows}),
            "n_sources": len(meta["sources"]),
            "last_year": max(years) if years else None,
            # 與 gen-indicator.py render_page() 的 desc 同一來源：第①段第一段前 120 字。
            # 被截斷時補刪節號：卡片上的字是給人讀的，斷在句中而不標，讀起來像
            # 原文就寫到那裡為止。截點與長度不變，只多一個「還有下文」的記號。
            "desc": _clip(sections[0][1][0] if sections[0][1] else ""),
        })

    cards.sort(key=lambda c: c["slug"])
    return cards


# ---------- 版面 ----------

INDEX_CSS = """
.ix-intro{ font-size:15px; color:var(--fg-soft); margin:10px 0 4px; line-height:1.9; }
.ix-cards{ list-style:none; margin:22px 0 0; padding:0; display:grid;
           grid-template-columns:repeat(auto-fit,minmax(272px,1fr)); gap:14px; }
.ix-card{ border:1px solid var(--line); border-radius:var(--radius);
          background:var(--surface); padding:15px 17px 14px; }
.ix-card .ix-h{ font-family:var(--font-display); font-size:17px; font-weight:800;
                line-height:1.5; margin:0 0 8px; }
.ix-card .ix-h a{ text-decoration:none; }
.ix-tags{ display:flex; flex-wrap:wrap; gap:5px 6px; margin:0 0 9px; padding:0; list-style:none; }
.ix-tags li{ font-size:12px; color:var(--dim); line-height:1.6;
             border:1px solid var(--line-2); border-radius:999px; padding:1px 9px; }
.ix-desc{ font-size:14px; color:var(--fg-soft); line-height:1.8; margin:0 0 10px; }
.ix-meta{ font-family:var(--font-mono); font-size:12px; color:var(--dim);
          line-height:1.7; margin:0; }
.ix-foot{ font-size:12.5px; color:var(--dim); border-top:1px solid var(--line);
          padding-top:10px; margin-top:34px; }
"""


def render_card(c: dict) -> str:
    tags = "".join(f"<li>{esc(t)}</li>" for t in c["labels"])
    counts = (f"判準 {c['n_rows']} 列・機構 {c['n_orgs']} 家・來源 {c['n_sources']} 份")
    hist = (f'<p class="ix-meta">沿革最近一次：{c["last_year"]}</p>'
            if c["last_year"] is not None else "")
    return (
        '<li class="ix-card">'
        f'<h2 class="ix-h"><a href="{esc(c["href"])}">{esc(c["title"])}</a></h2>'
        f'<ul class="ix-tags">{tags}</ul>'
        f'<p class="ix-desc">{esc(c["desc"])}</p>'
        f'<p class="ix-meta">{esc(counts)}</p>'
        f'{hist}'
        "</li>")


def render_index(cards: list) -> str:
    body = ('  <main>\n'
            f'  <h1 class="pg-h1">{esc(PAGE_TITLE)}</h1>\n'
            f'  <p class="ix-intro">{esc(INTRO)}</p>\n'
            f'  <ul class="ix-cards">{"".join(render_card(c) for c in cards)}</ul>\n'
            f'  <p class="ix-foot">{esc(gen.FOOT_LINE)}</p>\n  </main>')

    page_node = {
        "@type": "CollectionPage", "@id": f"{INDEX_URL}#page",
        "name": PAGE_TITLE, "description": INTRO, "url": INDEX_URL,
        "inLanguage": "zh-Hant", "isAccessibleForFree": True,
        "mainEntityOfPage": INDEX_URL,
        "publisher": {"@id": f"{hl.BASE}/#org"},
    }
    # ☠️ ItemList 只鏡射頁面上真實可見的卡片與其順序，不排名、不放任何評分。
    item_list = {
        "@type": "ItemList", "@id": f"{INDEX_URL}#list",
        "numberOfItems": len(cards),
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": c["title"], "url": c["url"]}
            for i, c in enumerate(cards, start=1)],
    }
    jsonld = hl.graph_ld([
        hl.org_node(), hl.website_node(), page_node, item_list,
        hl.breadcrumb_node([("首頁", f"{hl.BASE}/"), ("指標", INDEX_URL)])])

    return hl.page_shell(PAGE_TITLE, INTRO, INDEX_URL, jsonld, body,
                         "indicators", extra_css=INDEX_CSS)


# ---------- dormant 接線（跑在 gen-indicator.py 之後，讀既有檔改寫回） ----------

def wire_sitemap(parts_dir: pathlib.Path, published: bool):
    """把索引 URL 放進 sitemap part 的第一行。

    gen-indicator.py 的 wire_sitemap() 每次重寫整個 part 檔，所以這裡不能自己
    寫一份，只能在它之後讀既有內容、把索引 URL 提到最前面再寫回。
    dormant 時它已經把 part 刪掉了 → 檔不存在＝什麼都不做。
    """
    part = pathlib.Path(parts_dir) / f"{SITEMAP_OWNER}.txt"
    if not published:
        return
    if not part.exists():
        # published 卻沒有 part＝跑序被打破（gen-indicator.py 還沒跑）。不自己造一份：
        # 那會生出一個「有索引、沒有任何指標頁」的 sitemap，而且沒有人會發現。
        print(f"🔴 sitemap part '{SITEMAP_OWNER}' 不存在，索引 URL 未接線。"
              "請照跑序先跑 scripts/gen-indicator.py 再跑本腳本。")
        return
    urls = [l.strip() for l in part.read_text(encoding="utf-8").splitlines() if l.strip()]
    urls = [INDEX_URL] + [u for u in urls if u != INDEX_URL]
    content = "".join(f"{u}\n" for u in urls)
    if part.read_text(encoding="utf-8") != content:
        part.write_text(content, encoding="utf-8")
    print(f"🗺️  sitemap part '{SITEMAP_OWNER}' 第一行 → {INDEX_URL}")


def wire_llms(llms_path: pathlib.Path, published: bool):
    """在 llms.txt 的「## 指標頁」區塊第一行插入索引頁連結。

    區塊整塊由 gen-indicator.py 的 wire_llms() 重寫，所以同樣只能跑在它之後。
    dormant 時區塊不存在（或整個檔不存在）＝不動。
    """
    llms_path = pathlib.Path(llms_path)
    if not published or not llms_path.exists():
        return
    text = llms_path.read_text(encoding="utf-8")
    marker = f"\n{LLMS_HEAD}\n"
    if marker not in text:
        return
    head, _, tail = text.partition(marker)
    nxt = tail.find("\n## ")
    block, rest = (tail[:nxt], tail[nxt:]) if nxt >= 0 else (tail, "")
    lines = block.split("\n")
    if LLMS_LINE not in lines:
        first_bullet = next((i for i, l in enumerate(lines) if l.startswith("- ")), None)
        if first_bullet is None:
            # 區塊在、卻一條連結都沒有＝上游的形狀變了。不猜插在哪裡。
            print(f"🔴 llms.txt 的「{LLMS_HEAD}」區塊沒有任何連結行，索引連結未插入。")
            return
        lines.insert(first_bullet, LLMS_LINE)
        block = "\n".join(lines)
    new_text = head + marker + block + rest
    if new_text != text:
        llms_path.write_text(new_text, encoding="utf-8")
    print(f"📄 llms.txt「{LLMS_HEAD}」區塊第一行 → {PAGE_TITLE}")


# ---------- build ----------

def build(out_root=None, parts_dir=None, llms_path=None, published=None,
          src_dir=None, criteria_dir=None) -> str:
    out_root = pathlib.Path(out_root) if out_root else hl.PUB
    parts_dir = pathlib.Path(parts_dir) if parts_dir else ROOT / "data" / "sitemap-parts"
    llms_path = pathlib.Path(llms_path) if llms_path else out_root / "llms.txt"
    if published is None:
        published = json.loads((ROOT / "config" / "site.json").read_text(
            encoding="utf-8")).get("published", False) is True

    # 導覽／頁尾的 published gate 與底下的接線吃同一個旗標（見 gen-indicator.build()）。
    hl.PUBLISHED = published

    cards = collect_cards(src_dir, criteria_dir)
    html_out = render_index(cards)
    out_dir = out_root / "indicators"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html_out, encoding="utf-8")
    print(f"✅ /indicators/　索引 {len(cards)} 張卡"
          f"（{'、'.join(c['slug'] for c in cards)}）")

    wire_sitemap(parts_dir, published)
    wire_llms(llms_path, published)
    if not published:
        print("🔒 dormant（config/site.json published=false）：索引頁已生成，"
              "但不進 sitemap／llms.txt，導覽不連。")
    return html_out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="/indicators/ 索引頁生成器（資料驅動，dormant 感知；跑在 gen-indicator.py 之後）")
    ap.parse_args()
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
