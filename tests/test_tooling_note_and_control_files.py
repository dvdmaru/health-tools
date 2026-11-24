#!/usr/bin/env python3
"""兩個工具小洞的回歸測試（2026-11-24，PR #42 處理 medlineplus-gfr-test 改版時踩到）。

1. fetch-health-source.py 的 upsert：更新既有列時沒帶 --note，舊 note 被整個洗掉。
2. verify-deploy.py：`_headers` 是 Cloudflare 控制檔，線上回 0 bytes，整檔比對必然假紅。
"""
import contextlib
import importlib.util
import io
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(modname: str, filename: str):
    spec = importlib.util.spec_from_file_location(modname, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fetch = _load("fetch_health_source", "fetch-health-source.py")
verify = _load("verify_deploy", "verify-deploy.py")


def _row(**kw):
    base = {"id": "x", "sha256": "a" * 64, "url": "https://old.example/"}
    base.update(kw)
    return base


class UpsertKeepsNote(unittest.TestCase):
    def test_update_without_note_keeps_old_note_and_warns(self):
        rows = [_row(note="舊 note：這份來源的坑")]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            action = fetch.upsert(rows, _row(sha256="b" * 64, url="https://new.example/"))
        self.assertEqual(action, "更新")
        self.assertEqual(rows[0]["note"], "舊 note：這份來源的坑")
        self.assertEqual(rows[0]["url"], "https://new.example/")
        self.assertIn("沿用舊 note", buf.getvalue())

    def test_explicit_note_replaces_old(self):
        rows = [_row(note="舊")]
        fetch.upsert(rows, _row(sha256="b" * 64, note="新"))
        self.assertEqual(rows[0]["note"], "新")

    def test_unchanged_sha_keeps_note_silently(self):
        rows = [_row(note="舊")]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            action = fetch.upsert(rows, _row())
        self.assertEqual(action, "無變動")
        self.assertEqual(rows[0]["note"], "舊")
        self.assertEqual(buf.getvalue(), "")

    def test_old_row_without_note_stays_without_note(self):
        rows = [_row()]
        fetch.upsert(rows, _row(sha256="b" * 64))
        self.assertNotIn("note", rows[0])

    def test_new_row_appended(self):
        rows = []
        self.assertEqual(fetch.upsert(rows, _row()), "新增")


class VerifySkipsControlFiles(unittest.TestCase):
    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["verify-deploy.py", "--site", "https://t.example", *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = verify.main()
        return rc, out.getvalue(), err.getvalue()

    def test_headers_skipped_and_page_still_compared(self):
        tmp = ROOT / "public-health" / "_tooling_test_tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: [p.unlink() for p in tmp.iterdir()] and tmp.rmdir())
        page = tmp / "index.html"
        page.write_bytes(b"<p>hi</p>")
        hdr = tmp / "_headers"
        hdr.write_bytes(b"/*\n  X-Test: 1\n")
        fetched = []

        def fake_fetch(url, cache_bust):
            fetched.append(url)
            return b"<p>hi</p>"

        with mock.patch.object(verify, "fetch", side_effect=fake_fetch):
            rc, out, _ = self._run([str(hdr), str(page)])
        self.assertEqual(rc, 0)
        self.assertIn("跳過", out)
        self.assertEqual(fetched and [u.split("?")[0] for u in fetched],
                         ["https://t.example/_tooling_test_tmp/"])

    def test_only_control_files_is_an_error(self):
        tmp = ROOT / "public-health" / "_tooling_test_tmp2"
        tmp.mkdir(parents=True, exist_ok=True)
        hdr = tmp / "_headers"
        hdr.write_bytes(b"x")
        self.addCleanup(lambda: (hdr.unlink(), tmp.rmdir()))
        rc, _, err = self._run([str(hdr)])
        self.assertEqual(rc, 2)
        self.assertIn("沒有任何檔案可比對", err)


if __name__ == "__main__":
    unittest.main()
