#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-receipts.py — 收據 gate：每一條判準／變更史／限制列，都要能把引句 grep 回快照。

這道 gate 守的是本站唯一的承諾：**頁面上的每個數字都能回查原始文件**。
它對 data/criteria/*.json 的每一列做四件事：

  ① doc_id 必須存在於 data/sources/manifest.json——指不到來源的列不得渲染。
  ② quote（含 quote_extra、corroboration）非空。
  ③ 該來源的快照檔在磁碟上存在時，每一句引句都必須在快照裡找得到。
     PDF 走 `pdftotext -layout`；比對前雙方都做 re.sub(r"\\s+", "", …) 正規化
     （PDF 轉檔會在中文與數字之間插入或吃掉空白，原樣 grep 必假陰性）。
     **全形／半形不轉換**——來源自己的 ≧／≥、mg/dl／mg/dL 不一致就是回查的指紋，
     把它們正規化掉等於把「引句照抄」這條紅線拆了。
  ④ 快照檔不存在時印 SKIP，**不是 PASS**。SKIP 代表「還沒驗過」，
     退出碼仍為 0，但彙總會把待補來源逐份列出。

☠️ 不准把驗不過的列塞進例外清單。
   這道 gate 沒有例外清單，而且刻意不提供——百科線的驗證教義第 2 條說得很清楚：
   最大的風險不是漏寫例外，是「發現 gate 紅了就把錯誤塞進例外清單合法化」。
   引句 grep 不中只有兩種可能：引句抄錯了，或快照不是那份文件。兩種都必須停下來給人裁決，
   而不是在這裡加一行 `if row_id in KNOWN_FAILURES: continue`。
   **也不准反過來改 quote 去遷就快照**——那是把出處改成事後編的。

用法
----
    python3 scripts/check-receipts.py            # 全部檢查
    python3 scripts/check-receipts.py --verbose  # 連 PASS 的列一起列出
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = ROOT / "data" / "sources" / "manifest.json"
CRITERIA_DIR = ROOT / "data" / "criteria"

# 每個資料檔怎麼認自己的列：(檔名, 列號欄位或 None, 顯示名)。
# 動態掃描 data/criteria/*.json（schema 檔除外）——新指標落地不必回來改這裡，
# 也不會出現「檔在、gate 沒讀」的假綠。
def _datasets():
    out = []
    for f in sorted(CRITERIA_DIR.glob("*.json")):
        if f.name.endswith("schema.json"):
            continue
        if f.name.endswith("-history.json"):
            out.append((f.name, "id", "history"))
        elif f.name.endswith("-interference.json"):
            out.append((f.name, "id", "interference"))
        else:
            out.append((f.name, None, "criteria"))
    return out

_pdf_cache: dict = {}
_text_cache: dict = {}


def norm(s: str) -> str:
    """只吃掉空白。全形半形、大小寫、≧／≥ 一律不動——那些是回查原文的指紋。"""
    return re.sub(r"\s+", "", s)


def snapshot_text(path: pathlib.Path, doc_type: str) -> str:
    key = str(path)
    if key in _text_cache:
        return _text_cache[key]
    if doc_type == "pdf":
        r = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                           capture_output=True)
        if r.returncode != 0:
            raise OSError(f"pdftotext 失敗（{path.name}）："
                          f"{r.stderr.decode('utf-8', 'replace').strip()}")
        text = r.stdout.decode("utf-8", "replace")
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    _text_cache[key] = norm(text)
    return _text_cache[key]


def quotes_of(row: dict) -> list:
    """回 [(doc_id, quote, 欄位名), …]——一列可能引不只一句、也可能引不只一份文件。"""
    out = [(row["doc_id"], row["quote"], "quote")]
    for i, q in enumerate(row.get("quote_extra", [])):
        out.append((row["doc_id"], q, f"quote_extra[{i}]"))
    for i, c in enumerate(row.get("corroboration", [])):
        out.append((c["doc_id"], c["quote"], f"corroboration[{i}]"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="收據 gate：引句必須 grep 得回快照")
    ap.add_argument("--verbose", action="store_true", help="連 PASS 的列一起列出")
    args = ap.parse_args()

    if not SOURCES.exists():
        print("❌ 找不到 data/sources/manifest.json", file=sys.stderr)
        return 1
    sources = {s["id"]: s for s in json.loads(SOURCES.read_text(encoding="utf-8"))}

    n_pass = n_skip = n_fail = 0
    failures = []
    skipped_docs = {}

    for fname, id_field, label in _datasets():
        path = CRITERIA_DIR / fname
        if not path.exists():
            print(f"❌ 找不到 {path.relative_to(ROOT)}", file=sys.stderr)
            return 1
        rows = json.loads(path.read_text(encoding="utf-8"))
        for idx, row in enumerate(rows):
            row_id = row.get(id_field) if id_field else f"#{idx + 1}"
            tag = f"{label}:{row_id}"

            for doc_id, quote, field in quotes_of(row):
                where = f"{tag} {field}"
                src = sources.get(doc_id)
                if src is None:
                    n_fail += 1
                    failures.append((where, doc_id,
                                     f"doc_id「{doc_id}」不在 manifest", quote))
                    continue
                if not quote or not quote.strip():
                    n_fail += 1
                    failures.append((where, doc_id, "引句為空", quote))
                    continue

                local = src.get("local_path") or ""
                fpath = ROOT / local if local else None
                if not local or not fpath.exists():
                    n_skip += 1
                    reason = ("retrieval=browser-needed，快照尚未取得"
                              if src.get("retrieval") == "browser-needed"
                              else "快照檔不在磁碟上（可能未入版控，見 .gitignore）")
                    skipped_docs.setdefault(doc_id, [reason, 0])
                    skipped_docs[doc_id][1] += 1
                    print(f"SKIP  {where}  ← {doc_id}（{reason}）")
                    continue

                try:
                    hay = snapshot_text(fpath, src["doc_type"])
                except OSError as e:
                    n_fail += 1
                    failures.append((where, doc_id, str(e), quote))
                    continue

                if norm(quote) in hay:
                    n_pass += 1
                    if args.verbose:
                        print(f"PASS  {where}  ← {doc_id}")
                else:
                    n_fail += 1
                    failures.append((where, doc_id, "引句在快照中找不到", quote))

    if failures:
        print("\n" + "=" * 72)
        print("FAIL 明細（引句抄錯，或快照不是那份文件——兩種都要人裁決，不准塞例外）")
        print("=" * 72)
        for where, doc_id, why, quote in failures:
            print(f"\n  ✗ {where}\n    來源：{doc_id}\n    原因：{why}\n    引句：{quote!r}")

    if skipped_docs:
        print("\n" + "-" * 72)
        print(f"待補快照的來源（{len(skipped_docs)} 份）——這些列是 SKIP，不是 PASS：")
        for doc_id, (reason, cnt) in sorted(skipped_docs.items()):
            print(f"  · {doc_id}：{cnt} 句待驗（{reason}）")

    print("\n" + "=" * 72)
    print(f"收據 gate：PASS {n_pass}／SKIP {n_skip}／FAIL {n_fail}")
    print("=" * 72)
    if n_fail:
        print("🔴 有引句回查不到原文。停下回報，不要改 quote 去遷就快照。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
