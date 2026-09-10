# -*- coding: utf-8 -*-
"""頁面上被渲染的判準／沿革／限制列，引用的每一份文件都必須列在該頁 frontmatter 的 `sources`。

☠️ 起因（2026-09-10）：hba1c 頁補進 WHO/IDF 2006 的 5 列判準後，判準表裡看得到那份文件，
   頁尾「來源與版本」卻沒有它——來源段只讀 frontmatter，而沒有任何檢查要求兩邊一致。
   當時收據 gate、309 條測試、禁詞 gate、決定性 build 全綠，這個洞一個都沒擋到。
   ⇒ 讀者在表格裡看到一份文件，往下找出處卻找不到，本站「每個數字都有出處」的承諾就破了。

射程刻意跟生成器的渲染範圍一致：判準列只算 `TABLE_CATEGORIES`（會進判準表的類別），
沿革與限制兩檔的列全部都算（它們整份渲染成第③④段）。
"""
import importlib.util
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("gen_indicator_for_sources", "scripts/gen-indicator.py")
CRIT = ROOT / "data" / "criteria"


def used_docs(slug: str, ids: list) -> dict:
    """{doc_id: 第一個引用它的位置}——只收會被渲染到頁面上的列。"""
    used = {}
    for r in json.loads((CRIT / f"{slug}.json").read_text(encoding="utf-8")):
        if r["indicator_id"] in ids and r["category"] in gen.TABLE_CATEGORIES:
            used.setdefault(r["doc_id"], f"判準 {r['indicator_id']}／{r['category']}")
    for kind, label in (("history", "沿革"), ("interference", "限制")):
        p = CRIT / f"{slug}-{kind}.json"
        if not p.exists():
            continue
        for r in json.loads(p.read_text(encoding="utf-8")):
            if r.get("doc_id"):
                used.setdefault(r["doc_id"], f"{label} {r.get('id', '?')}")
    return used


class RenderedRowsCiteListedSources(unittest.TestCase):
    def test_every_rendered_document_is_listed_in_page_sources(self):
        pages = sorted((ROOT / "articles" / "indicators").glob("*.md"))
        self.assertTrue(pages, "找不到任何指標頁——這條測試會變成掃了 0 頁的假綠")
        checked = 0
        for md in pages:
            meta, _, _ = gen.parse_article(md)
            slug = meta.get("slug") or md.stem
            ids = gen.page_indicators(meta, slug)[0]
            listed = set(meta["sources"])
            for doc, where in sorted(used_docs(slug, ids).items()):
                checked += 1
                with self.subTest(page=slug, doc=doc):
                    self.assertIn(
                        doc, listed,
                        f"{slug} 頁的{where}引用了 {doc}，但它不在該頁 frontmatter 的 sources"
                        "——讀者在表格看得到這份文件，在「來源與版本」卻找不到")
        self.assertGreater(checked, 0, "沒有檢查到任何引用——射程寫錯了")


if __name__ == "__main__":
    unittest.main()
