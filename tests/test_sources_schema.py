#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""來源登記簿 schema（data/sources/schema.json）的 doc_type 白名單測試。

doc_type=ods＝來源只以 OpenDocument 試算表發布；快照存原檔，gate 以固定規則抽字比對。
守兩件事：ods 條目要能通過驗證；打錯的值（例 odt）要被擋——白名單只要不擋錯字，
就等於沒有白名單。
"""
import json
import pathlib
import unittest

from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "data" / "sources" / "schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


def entry(**over) -> dict:
    row = {
        "id": "ods-fixture", "title": "fixture", "org": "fixture",
        "doc_type": "ods", "url": "https://example.org/fixture.ods",
        "version_or_date": "文件未標示", "fetched_at": "2026-09-10",
        "sha256": "0" * 64, "local_path": "data/sources/ods-fixture.ods",
        "license_bucket": "tw-gov", "retrieval": "manual",
    }
    row.update(over)
    return row


class DocTypeOds(unittest.TestCase):
    def test_schema_itself_is_valid(self):
        Draft202012Validator.check_schema(SCHEMA)

    def test_an_ods_entry_validates(self):
        self.assertEqual([], list(VALIDATOR.iter_errors([entry()])))

    def test_a_typo_is_rejected(self):
        for bad in ("odt", "ODS", "xlsx", ""):
            with self.subTest(doc_type=bad):
                self.assertTrue(list(VALIDATOR.iter_errors([entry(doc_type=bad)])))

    def test_existing_values_are_still_accepted(self):
        for ok in ("pdf", "html", "html-text"):
            with self.subTest(doc_type=ok):
                self.assertEqual([], list(VALIDATOR.iter_errors([entry(doc_type=ok)])))

    def test_description_says_what_ods_means(self):
        desc = SCHEMA["$defs"]["source"]["properties"]["doc_type"]["description"]
        self.assertIn("ods＝來源只以 OpenDocument 試算表發布", desc)


if __name__ == "__main__":
    unittest.main()
