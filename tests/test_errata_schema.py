#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""勘誤紀錄 schema 與資料的 gate（data/errata-schema.json／data/errata.json）。

勘誤是對讀者的承諾——「你當時看到的是別的字」。所以守的不是欄位型別，是這幾件事：

1. **上線前的修改不是勘誤**：本檔初始 `[]`，M4 的內部修正不得補記進來（人審，
   這裡只驗檔案存在且合 schema）。
2. **有依據就要拿得出原文**：`doc_id` 與 `quote` 互為必填（dependentRequired），
   而且引句同樣受收據 gate 逐句 grep（`scripts/check-receipts.py`）。
   ☠️ 沒有 `doc_id` 的列在 gate 裡是「跳過」不是 FAIL——判 FAIL 會逼人編一個
   doc_id 出來，那才是把出處變成事後編的。
3. **slug 要有落點**：指不到 `articles/indicators/<slug>.md` 的勘誤列，在站級頁上
   就是一條連到 404 的連結。這裡拿 repo 真資料驗，並配一組陰性對照。
4. **只存明細**：不准出現勘誤次數、最後勘誤日這種彙總欄。
5. **gate 真的讀得到這個檔**：`_datasets()` 沒登記它就是「檔在、gate 沒讀」的假綠。
"""
import importlib.util
import json
import pathlib
import unittest

from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "data" / "errata-schema.json"
DATA_PATH = ROOT / "data" / "errata.json"
ARTICLE_DIR = ROOT / "articles" / "indicators"

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
ITEM_VALIDATOR = Draft202012Validator(
    {**SCHEMA["$defs"]["erratum"], "$defs": SCHEMA["$defs"]})


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("gen_indicator", "scripts/gen-indicator.py")
receipts = _load("check_receipts", "scripts/check-receipts.py")

# 一列真實形狀：第②段判準表上的分類標籤沒把「這不是診斷線」寫出來，改掉。
# （形狀取真的 slug、真的 section 值；內容是示例，不代表站上發生過這次更正。）
FIXTURE = {
    "id": "E1",
    "date": "2026-09-15",
    "slug": "hba1c",
    "section": "table",
    "was": "篩檢分流：≥5.9%",
    "now": "篩檢分流（非診斷判準）：≥5.9%",
    "reason": "原標籤沒在表上寫明這不是診斷線，讀者可能把轉介門檻讀成診斷值。",
}

# 有依據文件的那一種：doc_id 指得到 manifest，quote 是原文（收據 gate 會 grep）。
FIXTURE_WITH_DOC = {
    "id": "E2",
    "date": "2026-09-20",
    "slug": "hba1c",
    "section": "2",
    "was": "ADA 把糖尿病前期畫在 5.7%",
    "now": "ADA 把糖尿病診斷畫在 6.5%",
    "reason": "原句把兩條線寫反了。",
    "doc_id": "ada-standards-of-care-2026",
    "quote": "A1C ≥6.5% (≥48 mmol/mol).",
    "note": "同一句話在第②段與判準表各出現一次，只有第②段那份寫錯。",
}

# 只存明細：這些字出現在欄位名裡，就是有人開始存彙總值了。
FORBIDDEN_FIELD_HINTS = (
    "count", "total", "sum", "avg", "average", "mean", "median", "min", "max",
    "latest", "last", "consensus", "summary", "aggregate", "stats",
)


class TestSchemaItself(unittest.TestCase):
    def test_schema_is_valid(self):
        Draft202012Validator.check_schema(SCHEMA)

    def test_empty_array_is_valid(self):
        """初始值就是 []——「還沒有勘誤」必須是合法狀態，不是缺資料。"""
        VALIDATOR.validate([])

    def test_additional_properties_are_closed(self):
        self.assertFalse(SCHEMA["$defs"]["erratum"]["additionalProperties"])

    def test_no_aggregate_fields(self):
        props = SCHEMA["$defs"]["erratum"]["properties"]
        for name in props:
            for hint in FORBIDDEN_FIELD_HINTS:
                with self.subTest(field=name, hint=hint):
                    self.assertNotIn(
                        hint, name.lower(),
                        f"欄位「{name}」看起來是彙總欄；勘誤層只存明細（次數＝len()）")

    def test_the_seven_core_fields_are_required(self):
        required = set(SCHEMA["$defs"]["erratum"]["required"])
        for field in ("id", "date", "slug", "section", "was", "now", "reason"):
            with self.subTest(field=field):
                self.assertIn(field, required)

    def test_section_enum_matches_the_generator_label_table(self):
        """schema 的白名單與 gen-indicator.py 的中文標籤表必須一一對應——
        兩邊各長各的，就會出現一個渲染時 KeyError 的合法值。"""
        self.assertEqual(
            sorted(SCHEMA["$defs"]["erratum"]["properties"]["section"]["enum"]),
            sorted(gen.ERRATA_SECTION_LABEL))


class TestFixturesFit(unittest.TestCase):
    def test_plain_fixture_validates(self):
        ITEM_VALIDATOR.validate(FIXTURE)

    def test_document_backed_fixture_validates(self):
        ITEM_VALIDATOR.validate(FIXTURE_WITH_DOC)

    def test_array_of_fixtures_validates(self):
        VALIDATOR.validate([FIXTURE, FIXTURE_WITH_DOC])


class TestAssertions(unittest.TestCase):
    def test_doc_id_without_quote_is_rejected(self):
        bad = {k: v for k, v in FIXTURE_WITH_DOC.items() if k != "quote"}
        with self.assertRaises(Exception,
                               msg="有依據文件卻沒有原文引句＝拿不出那份依據"):
            ITEM_VALIDATOR.validate(bad)

    def test_quote_without_doc_id_is_rejected(self):
        """反向也綁：一句沒說是哪份文件的引句，收據 gate 無從 grep，等於沒有出處。"""
        bad = {k: v for k, v in FIXTURE_WITH_DOC.items() if k != "doc_id"}
        with self.assertRaises(Exception):
            ITEM_VALIDATOR.validate(bad)

    def test_a_row_with_neither_doc_id_nor_quote_is_fine(self):
        """陽性對照：多數勘誤是自己的筆誤，本來就沒有外部依據，不該被擋。"""
        ITEM_VALIDATOR.validate(FIXTURE)

    def test_id_pattern_rejects_free_form_ids(self):
        for bad_id in ("1", "e1", "E", "E12345", "E1a"):
            with self.subTest(id=bad_id):
                with self.assertRaises(Exception):
                    ITEM_VALIDATOR.validate({**FIXTURE, "id": bad_id})

    def test_unknown_section_is_rejected(self):
        for bad in ("7", "判準表", "chart-1", "footer"):
            with self.subTest(section=bad):
                with self.assertRaises(Exception):
                    ITEM_VALIDATOR.validate({**FIXTURE, "section": bad})

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(Exception):
            ITEM_VALIDATOR.validate({**FIXTURE, "errata_count": 3})

    def test_empty_was_or_now_is_rejected(self):
        for field in ("was", "now", "reason"):
            with self.subTest(field=field):
                with self.assertRaises(Exception):
                    ITEM_VALIDATOR.validate({**FIXTURE, field: ""})


def slugs_without_a_page(rows: list) -> list:
    """回傳「指不到 articles/indicators/<slug>.md」的 slug。空 list＝每一列都有落點。"""
    return sorted({r["slug"] for r in rows
                   if not (ARTICLE_DIR / f"{r['slug']}.md").exists()})


class TestRealData(unittest.TestCase):
    def setUp(self):
        self.rows = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    def test_the_file_exists_and_validates(self):
        VALIDATOR.validate(self.rows)
        self.assertIsInstance(self.rows, list)

    def test_ids_are_unique(self):
        ids = [r["id"] for r in self.rows]
        self.assertEqual(len(ids), len(set(ids)), "勘誤 id 重複——讀者引用過的號不能撞")

    def test_every_slug_points_at_an_existing_page(self):
        self.assertEqual([], slugs_without_a_page(self.rows),
                         "勘誤列的 slug 指不到指標頁；站級頁會生出一條連到 404 的連結")

    def test_the_slug_checker_catches_a_missing_page(self):
        """陰性對照：上面那條在資料是 [] 時也會綠，所以檢查器自己要驗一次。"""
        self.assertEqual(
            ["no-such-indicator"],
            slugs_without_a_page([{**FIXTURE, "slug": "no-such-indicator"}]))
        self.assertEqual([], slugs_without_a_page([FIXTURE]))

    def test_the_receipts_gate_actually_reads_this_file(self):
        """☠️「檔在、gate 沒讀」的假綠：收據 gate 必須把 errata 登記成一個資料集。"""
        self.assertIn(("data/errata.json", "id", "errata"), receipts._datasets())


if __name__ == "__main__":
    unittest.main()
