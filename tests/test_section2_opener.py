#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第②段開場句「同一個數字，不同機構的判準不一樣」是一句事實主張——逐頁都要成立。

這句是寫手照範本（style-brief 的②段句型）逐頁複製的，兩張查核桌各判過一次 MAJOR：
- 2026-09-10 肝功能：原句寫「門檻」，表上兩家給的是參考區間與正常值，都不是門檻
  → 2026-09-11 全站改成本站判準表的通稱「判準」（肝功能頁加勘誤 E5）。
- 2026-09-11 腎功能：KDIGO 與國健署兩份分期表端點相同，「不一樣」與事實相反
  → 該頁改寫、不用這句。
寫手不會記得逐頁驗，所以由這支對每一頁的判準資料驗：用這句的頁，
至少要有一個指標、兩個機構，給的端點集合不一樣。
"""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ART = ROOT / "articles" / "indicators"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("gen_indicator", "scripts/gen-indicator.py")

OPENER = "不同機構的判準不一樣"
RETIRED = "不同機構的門檻不一樣"


def table_rows(slug: str) -> list:
    """這頁判準表上的列（與生成器同一套篩法：頁面 indicator_ids × TABLE_CATEGORIES）。"""
    meta, _, _ = gen.parse_article(ART / f"{slug}.md")
    ids, _ = gen.page_indicators(meta, slug)
    return [r for r in gen.load_json(gen.CRITERIA_DIR / f"{slug}.json")
            if r["indicator_id"] in ids and r["category"] in gen.TABLE_CATEGORIES]


def orgs_differ(rows: list) -> bool:
    """同一個指標裡，至少兩個機構給了不同的端點集合（lower／upper 非 null 的值）。"""
    by = {}
    for r in rows:
        ends = {v for v in (r.get("lower"), r.get("upper")) if v is not None}
        by.setdefault(r["indicator_id"], {}).setdefault(r["org"], set()).update(ends)
    for orgs in by.values():
        if len({frozenset(s) for s in orgs.values() if s}) >= 2:
            return True
    return False


class Section2Opener(unittest.TestCase):
    def test_opener_holds_on_every_page_that_uses_it(self):
        used = []
        for md in sorted(ART.glob("*.md")):
            if OPENER in md.read_text(encoding="utf-8"):
                used.append(md.stem)
                self.assertTrue(orgs_differ(table_rows(md.stem)),
                                f"{md.stem}：②段寫「{OPENER}」，但判準表上沒有任兩個機構的端點不同")
        self.assertTrue(used, "沒有任何一頁用到開場句——句子改了卻沒改這支測試？")

    def test_retired_wording_is_gone(self):
        for md in sorted(ART.glob("*.md")):
            self.assertNotIn(RETIRED, md.read_text(encoding="utf-8"), md.stem)

    def test_checker_rejects_identical_endpoints(self):
        """陰性對照：腎功能頁 KDIGO 與國健署的 eGFR 端點相同，檢查器必須判「不成立」。
        只驗「真資料會過」證明不了檢查器有作用。"""
        self.assertFalse(orgs_differ(table_rows("creatinine-egfr")))

    def test_checker_accepts_a_known_difference(self):
        """陽性對照：空腹血糖前期 ADA 從 100 起、WHO 從 110 起。"""
        rows = [r for r in table_rows("hba1c") if r["indicator_id"] == "fpg"]
        self.assertTrue(orgs_differ(rows))


if __name__ == "__main__":
    unittest.main()
