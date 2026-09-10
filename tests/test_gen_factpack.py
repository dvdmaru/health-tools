#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事實包產生器的 gate（scripts/gen-factpack.py）。

守的是 2026-09-10 同一天漏三次的那件事：事實包少印一欄，查核席就憑空生出一條假 finding。

1. 每一列都印滿 schema 的全部欄位（對真資料實跑，把產物讀回來數）。
2. 陰性對照：產物少一欄時，檢查器必須抓得到；資料多一個 schema 沒有的欄位時必須中止。
3. 不選列：判準檔有幾列，事實包就有幾個列標題（含不進判準表的列）。
4. 決定性：連跑兩次 byte-identical。
"""
import importlib.util
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fp = _load("gen_factpack", "scripts/gen-factpack.py")

# 活體 fixture：hba1c 是站上列數最多、三個資料檔都有、且混有不進判準表的列的一頁。
SLUG = "hba1c"


def _sections(doc: str) -> dict:
    """把事實包切成 {節標題: [每一列的行]}。"""
    out, cur_sec, cur_rows = {}, None, None
    for line in doc.splitlines():
        if line.startswith("## "):
            cur_sec = line[3:]
            cur_rows = out.setdefault(cur_sec, [])
        elif line.startswith("### ") and cur_rows is not None:
            cur_rows.append([])
        elif cur_rows:
            cur_rows[-1].append(line)
    return out


class TestFactpackFields(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.doc = fp.build(SLUG)
        cls.secs = _sections(cls.doc)

    def _check(self, prefix, schema_rel):
        props = fp.item_properties(ROOT / schema_rel)
        title = next(t for t in self.secs if t.startswith(prefix))
        rows = self.secs[title]
        self.assertGreater(len(rows), 0)
        for i, block in enumerate(rows, start=1):
            with self.subTest(section=prefix, row=i):
                self.assertEqual([], fp.missing_fields(block, props))

    def test_criteria_rows_print_every_schema_field(self):
        self._check("一、", "data/criteria/schema.json")

    def test_history_rows_print_every_schema_field(self):
        self._check("二、", "data/criteria/history-schema.json")

    def test_interference_rows_print_every_schema_field(self):
        self._check("三、", "data/criteria/interference-schema.json")

    def test_manifest_entries_print_every_schema_field(self):
        props = fp.manifest_properties()
        title = next(t for t in self.secs if t.startswith("四、"))
        for i, block in enumerate(self.secs[title], start=1):
            with self.subTest(doc=i):
                self.assertEqual([], fp.missing_fields(block, props))

    def test_every_criteria_row_is_printed_not_only_table_rows(self):
        rows = json.loads((ROOT / "data" / "criteria" / f"{SLUG}.json").read_text(encoding="utf-8"))
        title = next(t for t in self.secs if t.startswith("一、"))
        self.assertEqual(len(rows), len(self.secs[title]))
        # fixture 本身要混有不進判準表的列，否則這條驗不到「不選列」。
        self.assertIn("不進判準表", self.doc)


class TestFactpackNegativeControls(unittest.TestCase):

    def test_checker_catches_a_dropped_field(self):
        props = fp.item_properties(ROOT / "data" / "criteria" / "schema.json")
        rec = json.loads((ROOT / "data" / "criteria" / f"{SLUG}.json").read_text(encoding="utf-8"))[0]
        block = fp.render_record(rec, props, "neg")
        self.assertEqual([], fp.missing_fields(block, props))
        dropped = [l for l in block if not l.startswith("- `quote_extra`")]
        self.assertEqual(["quote_extra"], fp.missing_fields(dropped, props))

    def test_unknown_field_in_data_aborts(self):
        props = fp.item_properties(ROOT / "data" / "criteria" / "schema.json")
        rec = dict(json.loads((ROOT / "data" / "criteria" / f"{SLUG}.json").read_text(encoding="utf-8"))[0])
        rec["normal_range"] = "4–5.6"
        with self.assertRaises(SystemExit):
            fp.render_record(rec, props, "neg")

    def test_unfilled_optional_field_is_printed_as_unfilled(self):
        props = fp.item_properties(ROOT / "data" / "criteria" / "schema.json")
        rows = json.loads((ROOT / "data" / "criteria" / f"{SLUG}.json").read_text(encoding="utf-8"))
        rec = next(r for r in rows if "quote_extra" not in r)
        block = fp.render_record(rec, props, "neg")
        self.assertTrue(any(re.match(r"^- `quote_extra`：（未填", l) for l in block))


class TestFactpackDeterminism(unittest.TestCase):

    def test_two_runs_are_byte_identical(self):
        self.assertEqual(fp.build(SLUG), fp.build(SLUG))


if __name__ == "__main__":
    unittest.main()
