#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IndexNow 金鑰檔的回歸測試（scripts/build-articles.py 的 write_indexnow_key）。

為什麼要測：金鑰檔沒產出來是**靜默失敗**——站照樣 build、照樣部署、頁面照樣對，
只有搜尋引擎那端默默驗不過，而那端不會來跟你講。這是本 repo 記過的
「綠 build ≠ 接好」同型，所以把它釘在測試裡。

☠️ IndexNow 金鑰是**設計上就要公開**的值（引擎抓 https://<host>/<key>.txt 驗擁有權），
不是密鑰；正本進 repo 是對的。這裡連帶檢查它的格式，避免有人塞了一個不合規的值
進去而在部署後才發現。
"""
import importlib.util
import pathlib
import re
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(modname: str, rel: str):
    spec = importlib.util.spec_from_file_location(modname, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = _load("_build_articles_under_test", "scripts/build-articles.py")


class WriteIndexNowKey(unittest.TestCase):
    def test_writes_key_file_named_after_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            key_file = tmp / "key.txt"
            key_file.write_text("abc123\n", encoding="utf-8")
            pub = tmp / "pub"
            returned = build.write_indexnow_key(pub, key_file)
            self.assertEqual("abc123", returned)
            out = pub / "abc123.txt"
            self.assertTrue(out.exists(), "金鑰檔要以金鑰本身命名")
            self.assertEqual("abc123", out.read_text(encoding="utf-8").strip(),
                             "檔案內容必須就是金鑰本身，引擎是這樣驗的")

    def test_missing_key_file_writes_nothing_and_returns_none(self):
        """沒設定金鑰時不准產空檔或假檔——那會讓驗證永遠失敗且沒人知道。"""
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            pub = tmp / "pub"
            self.assertIsNone(build.write_indexnow_key(pub, tmp / "nope.txt"))
            self.assertFalse(pub.exists() and any(pub.iterdir()))

    def test_blank_key_file_is_treated_as_unset(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            key_file = tmp / "key.txt"
            key_file.write_text("   \n", encoding="utf-8")
            pub = tmp / "pub"
            self.assertIsNone(build.write_indexnow_key(pub, key_file))
            self.assertFalse(pub.exists() and any(pub.iterdir()))


class RepoKeyIsWellFormed(unittest.TestCase):
    def test_key_file_exists_and_is_32_hex(self):
        key_file = ROOT / "data" / "indexnow-key.txt"
        self.assertTrue(key_file.exists(), "data/indexnow-key.txt 是正本，不該消失")
        key = key_file.read_text(encoding="utf-8").strip()
        self.assertRegex(key, r"^[0-9a-f]{32}$",
                         "IndexNow 金鑰慣例是 32 碼十六進位；格式不合會在部署後才被引擎拒絕")


if __name__ == "__main__":
    unittest.main()
