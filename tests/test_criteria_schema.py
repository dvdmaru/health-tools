#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判準明細 schema 回歸測試（data/criteria/schema.json）。

fixture 是 HbA1c facts pack 第 1A 節的第 1 列與第 5 列，手打成 JSON——
用真實要裝的資料驗 schema，而不是用剛好符合 schema 的假資料。

守的東西：
- schema 裝得下這兩列（ADA 診斷線 ≥6.5%、ADA 糖尿病前期 5.7–6.4%）。
- quote 非空：空引句＝這一列沒有出處，等於數字是憑空的。
- category 白名單：分類是判準的一部分，自創分類會讓篩檢門檻被講成診斷線。
- 禁止統計／彙總欄位：只存明細（百科線驗證教義 1）。
"""
import json
import pathlib
import unittest

from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "data" / "criteria" / "schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
ITEM_VALIDATOR = Draft202012Validator(
    {**SCHEMA["$defs"]["criterion"], "$defs": SCHEMA["$defs"]})

# 1A-#1：ADA Standards of Care in Diabetes—2026, Table 2.1，糖尿病診斷
FIXTURE_DIAGNOSIS = {
    "indicator_id": "hba1c",
    "org": "American Diabetes Association",
    "doc_id": "ada-standards-of-care-2026",
    "version": "2026",
    "category": "diagnosis",
    "lower": 6.5,
    "upper": None,
    "lower_inclusive": True,
    "unit": "%（NGSP）",
    "population": "非孕成人（一般）",
    "page_or_table": "Sec. 2, Table 2.1",
    "quote": "A1C ≥6.5% (≥48 mmol/mol).",
    "fetched_at": "2026-08-28",
}

# 1A-#5：同一份文件 Table 2.2，糖尿病前期區間
FIXTURE_PREDIABETES = {
    "indicator_id": "hba1c",
    "org": "American Diabetes Association",
    "doc_id": "ada-standards-of-care-2026",
    "version": "2026",
    "category": "prediabetes",
    "lower": 5.7,
    "upper": 6.4,
    "unit": "%（NGSP）",
    "population": "非孕成人",
    "page_or_table": "Sec. 2, Table 2.2",
    "quote": "A1C 5.7–6.4% (39–47 mmol/mol)",
    "fetched_at": "2026-08-28",
}

FIXTURES = [FIXTURE_DIAGNOSIS, FIXTURE_PREDIABETES]

# 只存明細：這些欄位名一旦出現在 schema 裡，就是有人開始存彙總值了。
FORBIDDEN_FIELD_HINTS = (
    "count", "total", "sum", "avg", "average", "mean", "median", "min", "max",
    "n_orgs", "org_count", "consensus", "summary", "aggregate", "stats",
)


class TestSchemaItself(unittest.TestCase):
    def test_schema_is_valid(self):
        Draft202012Validator.check_schema(SCHEMA)

    def test_no_aggregate_fields(self):
        """禁止任何統計／彙總欄位：數字＝len(明細)，不預先存起來。"""
        props = SCHEMA["$defs"]["criterion"]["properties"]
        for name in props:
            for hint in FORBIDDEN_FIELD_HINTS:
                with self.subTest(field=name, hint=hint):
                    self.assertNotIn(
                        hint, name.lower(),
                        f"欄位「{name}」看起來是統計／彙總欄位；判準層只存明細")

    def test_additional_properties_are_closed(self):
        """schema 必須關閉未宣告欄位——開著等於任何人都能偷渡一個彙總欄位進來。"""
        self.assertFalse(SCHEMA["$defs"]["criterion"]["additionalProperties"])

    def test_quote_and_provenance_are_required(self):
        required = set(SCHEMA["$defs"]["criterion"]["required"])
        for field in ("org", "doc_id", "version", "page_or_table", "quote"):
            with self.subTest(field=field):
                self.assertIn(field, required, f"{field} 是四項出處／引句之一，必須是必填")


class TestFixturesFit(unittest.TestCase):
    def test_each_fixture_validates(self):
        for fx in FIXTURES:
            with self.subTest(category=fx["category"]):
                ITEM_VALIDATOR.validate(fx)

    def test_array_of_fixtures_validates(self):
        VALIDATOR.validate(FIXTURES)

    def test_range_row_keeps_both_bounds(self):
        """區間型判準的上下界都要裝得下，且不被 schema 改寫。"""
        self.assertEqual(5.7, FIXTURE_PREDIABETES["lower"])
        self.assertEqual(6.4, FIXTURE_PREDIABETES["upper"])
        ITEM_VALIDATOR.validate(FIXTURE_PREDIABETES)

    def test_open_ended_row_uses_null_not_zero(self):
        """沒有上界要寫 null，不能寫 0——0 是一個值，null 才是「來源沒給」。"""
        self.assertIsNone(FIXTURE_DIAGNOSIS["upper"])
        ITEM_VALIDATOR.validate(FIXTURE_DIAGNOSIS)


class TestAssertions(unittest.TestCase):
    def test_quote_must_be_non_empty(self):
        for fx in FIXTURES:
            with self.subTest(category=fx["category"]):
                self.assertTrue(fx["quote"].strip(), "引句不得為空")
        bad = {**FIXTURE_DIAGNOSIS, "quote": ""}
        with self.assertRaises(Exception, msg="空引句必須被 schema 擋下"):
            ITEM_VALIDATOR.validate(bad)

    def test_category_must_be_in_whitelist(self):
        allowed = set(SCHEMA["$defs"]["criterion"]["properties"]["category"]["enum"])
        for fx in FIXTURES:
            with self.subTest(category=fx["category"]):
                self.assertIn(fx["category"], allowed)
        bad = {**FIXTURE_DIAGNOSIS, "category": "篩檢分流"}
        with self.assertRaises(Exception, msg="白名單外的分類必須被擋下"):
            ITEM_VALIDATOR.validate(bad)

    def test_unknown_field_is_rejected(self):
        bad = {**FIXTURE_DIAGNOSIS, "org_count": 3}
        with self.assertRaises(Exception, msg="未宣告欄位必須被擋下（含彙總欄位）"):
            ITEM_VALIDATOR.validate(bad)

    def test_missing_page_or_table_is_rejected(self):
        bad = {k: v for k, v in FIXTURE_DIAGNOSIS.items() if k != "page_or_table"}
        with self.assertRaises(Exception, msg="缺頁碼／表號的判準列必須被擋下"):
            ITEM_VALIDATOR.validate(bad)


if __name__ == "__main__":
    unittest.main()
