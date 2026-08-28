#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch-health-source.py — 把一份官方文件抓成快照，登記進 data/sources/manifest.json。

做的事只有三件（刻意做窄）：
  1. 給一個 URL，落地成 data/sources/<id>.pdf 或 .html
  2. 算 SHA-256
  3. 在 data/sources/manifest.json 補上或更新一列（schema 見同目錄 schema.json）

不做的事：不解析內容、不抽判準值、不做統計。判準值是 data/criteria 那一層的事，
而且必須由人逐列填「機構＋文件＋版本＋頁碼＋原文引句」，不從這裡自動生。

☠️ fail-honest：兩個已知會回攔截頁的網域
----------------------------------------
hpa.gov.tw 與 diabetesjournals.org 對 curl 會回 403 或 Cloudflare 的
Web Application Firewall 頁面。那頁**也是 HTTP 200、也存得下來、也算得出 sha256**——
存下來就等於在登記簿上放一份假快照，而且後面所有引用它的判準列都會指向一份不存在的
文件。所以這裡偵測到攔截就中止，印出「需瀏覽器抓取」，不留下任何檔案、不寫 manifest。

用 curl 不用 urllib：本機的 framework Python 沒有系統憑證鏈，urllib 會在
CERTIFICATE_VERIFY_FAILED 掛掉；curl 在 macOS 與 GH Actions 都在，行為一致。

用法
----
    python3 scripts/fetch-health-source.py \
        --id ada-soc-2026 --title "Standards of Care in Diabetes—2026" \
        --org "American Diabetes Association" --doc-type pdf \
        --version "2026" --license-bucket licensed-cite-only \
        --url https://example.org/doc.pdf

    # 只探測不落地（先確認這個網域擋不擋）
    python3 scripts/fetch-health-source.py --id x --url https://... --probe-only \
        --title t --org o --doc-type html --version v --license-bucket tw-gov
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "data" / "sources"
MANIFEST = SRC_DIR / "manifest.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
LICENSE_BUCKETS = ("us-federal-pd", "tw-gov", "licensed-cite-only")

# 攔截頁指紋。標題含防火牆字樣、或 HTTP 403，就是攔截頁而不是文件。
_WAF_TITLE = re.compile(
    rb"<title[^>]*>[^<]*(Web Application Firewall|Attention Required|Access Denied|"
    rb"Just a moment)[^<]*</title>", re.I)
_WAF_BODY = re.compile(rb"(cf-error-details|Cloudflare Ray ID|Request blocked)", re.I)
# 已知會擋 curl 的網域——先提醒，實測仍以回應為準（網域政策會變，寫死判定會過期）。
KNOWN_BLOCKED_HINT = ("hpa.gov.tw", "diabetesjournals.org")


def curl(url: str) -> tuple:
    """回 (http_code, body_bytes)。網路層失敗直接丟 OSError。"""
    r = subprocess.run(
        ["curl", "-sSL", "--max-time", "60", "-A", UA,
         "-w", "\n%{http_code}", url],
        capture_output=True)
    if r.returncode != 0:
        raise OSError(f"curl exit {r.returncode}: {r.stderr.decode('utf-8', 'replace').strip()}")
    out = r.stdout
    idx = out.rfind(b"\n")
    code = out[idx + 1:].decode("ascii", "replace").strip()
    return code, out[:idx if idx >= 0 else len(out)]


def blocked_reason(code: str, body: bytes) -> str:
    """回攔截原因字串；不是攔截頁就回空字串。"""
    if code == "403":
        return "HTTP 403"
    m = _WAF_TITLE.search(body[:20000])
    if m:
        return f"頁面標題含防火牆字樣（{m.group(1).decode('utf-8', 'replace')}）"
    if code == "200" and len(body) < 4096 and _WAF_BODY.search(body):
        return "回應內容是防火牆攔截頁"
    if code not in ("200", "206"):
        return f"HTTP {code}"
    return ""


def load_manifest() -> list:
    if not MANIFEST.exists():
        return []
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def save_manifest(rows: list):
    """依 id 排序後寫回，一列一行——排序固定，diff 才看得出真正的變動。"""
    rows = sorted(rows, key=lambda r: r["id"])
    MANIFEST.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


def upsert(rows: list, entry: dict) -> str:
    for i, r in enumerate(rows):
        if r["id"] == entry["id"]:
            action = "更新" if r.get("sha256") != entry["sha256"] else "無變動"
            rows[i] = entry
            return action
    rows.append(entry)
    return "新增"


def main() -> int:
    ap = argparse.ArgumentParser(description="抓一份官方文件快照並登記進 manifest")
    ap.add_argument("--id", required=True, help="本站內部代號（小寫、數字、連字號）")
    ap.add_argument("--url", required=True)
    ap.add_argument("--title", required=True, help="文件標題，照原文抄")
    ap.add_argument("--org", required=True, help="發布機構全名，不用縮寫")
    ap.add_argument("--doc-type", required=True, choices=["pdf", "html"])
    ap.add_argument("--version", required=True, dest="version_or_date",
                    help="文件自己標示的版本或日期；沒標示就寫「文件未標示」")
    ap.add_argument("--license-bucket", required=True, choices=list(LICENSE_BUCKETS))
    ap.add_argument("--note", default="")
    ap.add_argument("--fetched-at", default=None,
                    help="抓取日期 YYYY-MM-DD（預設今天，台北時間）")
    ap.add_argument("--probe-only", action="store_true",
                    help="只探測會不會被擋，不落地也不寫 manifest")
    args = ap.parse_args()

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", args.id):
        print(f"❌ id 格式不合：{args.id}（限小寫字母、數字、連字號）", file=sys.stderr)
        return 2

    if any(h in args.url for h in KNOWN_BLOCKED_HINT):
        print(f"ℹ️  {args.url} 屬於已知會擋 curl 的網域，先試；被擋會照下面的流程停下。")

    try:
        code, body = curl(args.url)
    except OSError as e:
        print(f"❌ 抓取失敗：{e}", file=sys.stderr)
        return 1

    reason = blocked_reason(code, body)
    if reason:
        print(f"🔴 需瀏覽器抓取：{args.url}\n"
              f"   偵測到攔截（{reason}），這不是文件本身。\n"
              f"   已中止，未落地任何檔案、未寫入 manifest——存下攔截頁等於在登記簿上放假快照。\n"
              f"   下一步：用瀏覽器開啟並另存，把檔案放到 "
              f"data/sources/{args.id}.{args.doc_type}，\n"
              f"   再以 --note 記錄取得方式、retrieval 標 browser，手動補上 manifest 一列。",
              file=sys.stderr)
        return 1

    if not body:
        print("❌ 回應是空的，未落地。", file=sys.stderr)
        return 1

    sha = hashlib.sha256(body).hexdigest()
    local_rel = f"data/sources/{args.id}.{args.doc_type}"

    if args.probe_only:
        print(f"✅ 探測通過：HTTP {code}，{len(body)} bytes，sha256 {sha}\n"
              f"   （--probe-only：未落地、未寫 manifest）")
        return 0

    SRC_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / local_rel).write_bytes(body)

    entry = {
        "id": args.id,
        "title": args.title,
        "org": args.org,
        "doc_type": args.doc_type,
        "url": args.url,
        "version_or_date": args.version_or_date,
        "fetched_at": args.fetched_at or datetime.date.today().isoformat(),
        "sha256": sha,
        "local_path": local_rel,
        "license_bucket": args.license_bucket,
        "retrieval": "curl",
    }
    if args.note:
        entry["note"] = args.note

    rows = load_manifest()
    action = upsert(rows, entry)
    save_manifest(rows)
    print(f"✅ {action}：{args.id}（HTTP {code}，{len(body)} bytes）\n"
          f"   → {local_rel}\n   sha256 {sha}")
    if args.license_bucket == "licensed-cite-only":
        print("⚠️  license_bucket=licensed-cite-only：快照只供內部查證與引句比對，"
              "不得整段重製、不得公開發布這份檔案。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
