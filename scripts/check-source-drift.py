#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-source-drift.py — 來源改版監測:判準列引用的那句話,線上版還在不在。

☠️ 為什麼不是「重抓比 sha256」
--------------------------------
data/sources/manifest.json 46 份來源裡,有 13 份是 browser-text／manual（瀏覽器抽出
的純文字,前 3 行是 SOURCE_URL／FETCHED_AT／METHOD 標頭）與 html-text,跟線上 raw
bytes 永遠對不上;線上 HTML 每次抓都可能因 nonce／時間戳／廣告位變,raw sha 比對
＝天天假警報,警報疲勞後沒人看＝等於沒監測。站的唯一承諾是「每個數字都能回查原
文」,改版真正會傷到的是「判準列引用的那句話從線上版消失了」,所以監測定在這一
層(D6:驗在缺陷顯現那層),而不是位元組層。

做的事
------
  1. 讀 manifest 每一列 + data/criteria/*.json,收出每個 doc_id 被引用到的所有引句
     (quote／quote_extra／corroboration),沿用 check-receipts.py 的
     _datasets()／quotes_of()／norm() 邏輯(import,正規化規則保證一致)。
  2. 對每列 url 用 curl 重抓(UA 與攔截判定沿用 fetch-health-source.py 的
     curl()／blocked_reason() 同一套指紋),另外抓 ETag／Last-Modified。
  3. 抽文字:doc_type=pdf 用 pdftotext -layout;html／html-text 去
     <script>/<style>、去 tag、entity unescape,再正規化空白比對。
  4. 每份文件算出 remote_sha256／text_sha256／quotes_total／quotes_found／
     quotes_missing(前 3 句、截 60 字)／http_code／etag／last_modified／checked_at。
  5. 跟 baseline 比對,判定狀態(見下)。
  6. --update-baseline 才寫 data/sources/drift-baseline.json;平常執行只讀不寫
     (CI 不能 commit)。

不做的事:不解析判準值、不做統計、不自動改 criteria/manifest——那些是人的判斷。

狀態語意(一個欄位一種語意,不准混)
----------------------------------
  ok                     可抓、所有引句都在、text_sha256 與 baseline 相同。
  changed-quotes-intact  raw／text sha 與 baseline 不同,但引句全在——資訊級,不算 drift。
                          (PDF 的 raw sha 常因來源端塞時間戳／流水號等雜訊而在內容
                          沒變時就跳動,見下方 classify() 內的實測記錄,所以 PDF 只看
                          raw sha 沒用,一律落這一格,不算 drift。)
  drift                  baseline 裡驗過在的引句現在找不到;或 PDF 的 text_sha256
                          (pdftotext 抽出、正規化後的正文)與 baseline 不同
                          (正文真的變了,不是位元組雜訊,一定要人看)。
  never-verified         baseline 當初就沒驗到的引句(或本次新增、baseline 沒有記錄
                          的引句)仍然找不到——不納入 drift,但要單獨列出,不准吞掉。
  blocked                403／WAF 頁——「無法確認,需瀏覽器」,不是 ok。
  unreachable            網路錯誤／逾時。
  no-quotes              manifest 有列、但沒有任何判準引用它——只比 sha,sha 變了會
                          在報告的總結行併入「changed」(sha 沒變則併入「ok」;真實
                          狀態仍完整保留在逐筆明細與 baseline 裡,不是被吞掉)。

用法
----
    python3 scripts/check-source-drift.py                 # 全量檢查,印摘要表,寫報告
    python3 scripts/check-source-drift.py --only <id>     # 單份
    python3 scripts/check-source-drift.py --update-baseline
    python3 scripts/check-source-drift.py --report PATH.md --json PATH.json
    python3 scripts/check-source-drift.py --timeout 60 --workers 4

exit code:0 無 drift;1 至少一份 drift;2 全部 unreachable／blocked(監測本身失效,
不准當綠燈);3 設定錯(baseline 缺、manifest 壞、--only 指到不存在的 id)。
exit code 不准經 pipe(tail 會吃掉)。
"""
import argparse
import concurrent.futures as cf
import datetime
import hashlib
import html as html_mod
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
SOURCES = ROOT / "data" / "sources" / "manifest.json"
BASELINE = ROOT / "data" / "sources" / "drift-baseline.json"
DEFAULT_OUT_DIR = ROOT / ".drift"


def _load_sibling(modname: str, filename: str):
    """import 檔名有連字號的同目錄腳本(不能用一般 import)。"""
    spec = importlib.util.spec_from_file_location(modname, SCRIPT_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_fetch = _load_sibling("_fetch_health_source_for_drift", "fetch-health-source.py")
_receipts = _load_sibling("_check_receipts_for_drift", "check-receipts.py")

UA = _fetch.UA
blocked_reason = _fetch.blocked_reason
norm = _receipts.norm
_datasets = _receipts._datasets
quotes_of = _receipts.quotes_of

TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def curl_with_headers(url: str, timeout: int) -> tuple:
    """回 (http_code, body_bytes, headers_dict)。

    UA／攔截判定沿用 fetch-health-source.py 的同一套指紋(見 blocked_reason)；
    這裡另外用 -D 抓標頭、-o 抓 body 到暫存檔,分流避免 header／body 混在同一個
    stdout 裡難以切開。headers 只留跟隨 redirect 後最後一組回應標頭,鍵統一小寫。
    """
    with tempfile.TemporaryDirectory() as td:
        hdr_path = pathlib.Path(td) / "headers"
        body_path = pathlib.Path(td) / "body"
        r = subprocess.run(
            ["curl", "-sSL", "--max-time", str(timeout), "-A", UA,
             "-D", str(hdr_path), "-o", str(body_path),
             "-w", "%{http_code}", url],
            capture_output=True)
        if r.returncode != 0:
            raise OSError(f"curl exit {r.returncode}: "
                          f"{r.stderr.decode('utf-8', 'replace').strip()}")
        code = r.stdout.decode("ascii", "replace").strip()
        body = body_path.read_bytes() if body_path.exists() else b""
        headers = {}
        if hdr_path.exists():
            raw = hdr_path.read_text(encoding="utf-8", errors="replace")
            blocks = re.split(r"\r?\n\r?\n", raw.strip())
            last = blocks[-1] if blocks else ""
            for line in last.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    headers[k.strip().lower()] = v.strip()
        return code, body, headers


def extract_text(doc_type: str, body: bytes) -> str:
    if doc_type == "pdf":
        return _pdf_text(body)
    return _html_text(body)


def _pdf_text(body: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(body)
        f.flush()
        r = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True)
        if r.returncode != 0:
            return ""
        return r.stdout.decode("utf-8", "replace")


def _html_text(body: bytes) -> str:
    text = body.decode("utf-8", "replace")
    text = SCRIPT_STYLE_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    text = html_mod.unescape(text)
    return text


def quotes_by_doc() -> dict:
    """doc_id → {引句集合}。和 check-receipts.py 主迴圈同規則:errata 沒填 doc_id
    的列跳過(那是選填,沒依據文件本來就沒有承諾引句)。"""
    out: dict = {}
    for rel, id_field, label in _datasets():
        path = ROOT / rel
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            if label == "errata" and not row.get("doc_id"):
                continue
            for doc_id, quote, field in quotes_of(row):
                out.setdefault(doc_id, set()).add(quote)
    return out


def check_source(src: dict, required: set, timeout: int) -> dict:
    """對一份來源實跑一次,回內部結果(含 _found/_missing 供 classify 用)。"""
    doc_id = src["id"]
    url = src["url"]
    doc_type = src["doc_type"]
    result = {
        "id": doc_id, "title": src.get("title", ""), "url": url,
        "doc_type": doc_type, "checked_at": now_iso(),
        "http_code": None, "etag": None, "last_modified": None,
        "remote_sha256": None, "text_sha256": None,
        "quotes_total": len(required), "quotes_found": 0,
        "_found": set(), "_missing": set(),
        "fetch_status": None, "error": "",
    }
    try:
        code, body, headers = curl_with_headers(url, timeout)
    except OSError as e:
        result["fetch_status"] = "unreachable"
        result["error"] = str(e)
        return result

    result["http_code"] = code
    result["etag"] = headers.get("etag")
    result["last_modified"] = headers.get("last-modified")

    reason = blocked_reason(code, body)
    if reason:
        result["fetch_status"] = "blocked"
        result["error"] = reason
        return result

    if not body:
        result["fetch_status"] = "unreachable"
        result["error"] = "回應是空的"
        return result

    result["remote_sha256"] = hashlib.sha256(body).hexdigest()
    text = extract_text(doc_type, body)
    norm_text = norm(text)
    result["text_sha256"] = hashlib.sha256(norm_text.encode("utf-8")).hexdigest()

    found = {q for q in required if norm(q) in norm_text}
    missing = required - found
    result["quotes_found"] = len(found)
    result["_found"] = found
    result["_missing"] = missing
    result["fetch_status"] = "reached"
    return result


def classify(cur: dict, baseline_entry, building: bool) -> str:
    """依 cur(本次結果)與 baseline_entry(上次 --update-baseline 的紀錄,可能是
    None)判定最終狀態。building=True 表示這次就是要寫 baseline 的那一輪——
    這一輪沒有「上一版」可比,所以不會判 drift／changed-quotes-intact。"""
    if cur["fetch_status"] == "unreachable":
        return "unreachable"
    if cur["fetch_status"] == "blocked":
        return "blocked"

    if cur["quotes_total"] == 0:
        if not building and baseline_entry:
            base_sha = baseline_entry.get("remote_sha256")
            if base_sha and cur.get("remote_sha256") and base_sha != cur["remote_sha256"]:
                return "changed-quotes-intact"
        return "no-quotes"

    missing_now = cur["_missing"]
    if building or baseline_entry is None:
        return "never-verified" if missing_now else "ok"

    verified_before = set(baseline_entry.get("quotes_verified", []))
    drift_missing = missing_now & verified_before
    # ☠️ 2026-08-28 實測推翻了「PDF raw sha 變＝一定要人看」：對同一份
    # eular-gout-recommendations-2016 PDF 連續 curl 三次，size 完全一樣但出現兩種
    # 不同的 raw sha256——bytes 本身不穩定（八成是發布方在頁尾／中繼資料塞了時間戳
    # 或流水號一類的東西），但三次 pdftotext -layout 抽出來正規化後的文字 sha256
    # 完全相同。用 raw sha 當 PDF 的 drift 訊號會在這份文件上天天假警報，
    # 正是本檔開頭那條「raw sha 比對＝警報疲勞」的教訓，只是換成 PDF 而已。
    # 所以 PDF 的 drift 訊號改用 text_sha256（跟 HTML 同一種「找得到的引句消失」
    # 邏輯的加強版）：text_sha 變了(代表抽出來的正文變了，不只是不可控的位元組雜訊)
    # 才算 drift；raw sha 變但 text_sha 沒變＝changed-quotes-intact（資訊級)。
    pdf_text_changed = (
        cur["doc_type"] == "pdf"
        and baseline_entry.get("text_sha256")
        and cur.get("text_sha256")
        and baseline_entry["text_sha256"] != cur["text_sha256"]
    )
    if drift_missing or pdf_text_changed:
        return "drift"

    nv_missing = missing_now - drift_missing
    if nv_missing:
        return "never-verified"

    base_sha = baseline_entry.get("remote_sha256")
    base_text_sha = baseline_entry.get("text_sha256")
    if base_sha and cur.get("remote_sha256") and base_sha != cur["remote_sha256"]:
        return "changed-quotes-intact"
    if base_text_sha and cur.get("text_sha256") and base_text_sha != cur["text_sha256"]:
        return "changed-quotes-intact"
    return "ok"


def build_baseline_entry(cur: dict, status: str) -> dict:
    """把一次 check_source 的結果折成 baseline 要存的形狀。
    quotes_verified＝這次找到的引句(下次拿來跟 missing 比,決定是不是 drift);
    quotes_never_verified＝這次沒找到的引句,單純留紀錄方便人工核對。
    可達性差(blocked／unreachable)時兩邊都是空的——沒驗到任何東西,不能宣稱驗過。"""
    verified = sorted(cur["_found"]) if cur["fetch_status"] == "reached" else []
    never = sorted(cur["_missing"]) if cur["fetch_status"] == "reached" else []
    return {
        "id": cur["id"],
        "url": cur["url"],
        "doc_type": cur["doc_type"],
        "checked_at": cur["checked_at"],
        "http_code": cur["http_code"],
        "status": status,
        "etag": cur["etag"],
        "last_modified": cur["last_modified"],
        "remote_sha256": cur["remote_sha256"],
        "text_sha256": cur["text_sha256"],
        "quotes_total": cur["quotes_total"],
        "quotes_verified": verified,
        "quotes_never_verified": never,
    }


def missing_sample(missing: set) -> list:
    """前 3 句、每句截 60 字——報告與 JSON 都用這個精簡版,避免整份引句灌爆輸出。"""
    out = []
    for q in sorted(missing)[:3]:
        out.append(q if len(q) <= 60 else q[:60] + "…")
    return out


def run(manifest: list, baseline_map: dict, timeout: int, workers: int,
        building: bool) -> list:
    required_by_doc = quotes_by_doc()
    rows = []
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {
            ex.submit(check_source, src, required_by_doc.get(src["id"], set()), timeout): src
            for src in manifest
        }
        for fut in cf.as_completed(futs):
            rows.append(fut.result())
    rows.sort(key=lambda r: r["id"])

    out = []
    for cur in rows:
        baseline_entry = baseline_map.get(cur["id"])
        status = classify(cur, baseline_entry, building)
        entry = {
            "id": cur["id"], "title": cur["title"], "url": cur["url"],
            "doc_type": cur["doc_type"], "checked_at": cur["checked_at"],
            "http_code": cur["http_code"], "etag": cur["etag"],
            "last_modified": cur["last_modified"],
            "remote_sha256": cur["remote_sha256"], "text_sha256": cur["text_sha256"],
            "quotes_total": cur["quotes_total"], "quotes_found": cur["quotes_found"],
            "quotes_missing": missing_sample(cur["_missing"]),
            "status": status, "error": cur["error"],
            "baseline_checked_at": baseline_entry.get("checked_at") if baseline_entry else None,
            "_baseline_entry_for_write": build_baseline_entry(cur, status),
        }
        out.append(entry)
    return out


def write_baseline(results: list):
    rows = [r["_baseline_entry_for_write"] for r in results]
    rows.sort(key=lambda r: r["id"])
    BASELINE.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


def render_report(results: list, total_in_manifest: int) -> str:
    def n(status):
        return sum(1 for r in results if r["status"] == status)

    n_ok = n("ok") + n("no-quotes")
    n_changed = n("changed-quotes-intact")
    n_drift = n("drift")
    n_nv = n("never-verified")
    n_blocked = n("blocked")
    n_unreachable = n("unreachable")

    lines = []
    lines.append(f"# 來源改版監測報告 — {datetime.date.today().isoformat()}")
    lines.append("")
    lines.append(f"{total_in_manifest} 份：ok {n_ok}／changed {n_changed}／"
                  f"drift {n_drift}／never-verified {n_nv}／"
                  f"blocked {n_blocked}／unreachable {n_unreachable}")
    if n("no-quotes"):
        lines.append(f"（其中 no-quotes {n('no-quotes')} 份併入 ok 計數——manifest "
                      f"有列、但目前沒有判準引用它，只比對 sha，狀態明細見下。）")
    lines.append("")

    drift_rows = [r for r in results if r["status"] == "drift"]
    lines.append(f"## drift 明細（{len(drift_rows)} 份，需要人看）")
    if drift_rows:
        for r in drift_rows:
            lines.append(f"- **{r['id']}**「{r['title']}」")
            lines.append(f"  - url：{r['url']}")
            lines.append(f"  - baseline checked_at → 現在：{r['baseline_checked_at']} → {r['checked_at']}")
            if r["doc_type"] == "pdf":
                lines.append(f"  - PDF raw sha 改變（改版）")
            if r["quotes_missing"]:
                lines.append(f"  - 缺的引句（前 3 句）：")
                for q in r["quotes_missing"]:
                    lines.append(f"    - {q!r}")
    else:
        lines.append("（無）")
    lines.append("")

    blocked_rows = [r for r in results if r["status"] == "blocked"]
    lines.append(f"## blocked 清單（{len(blocked_rows)} 份，需要人拿瀏覽器去看）")
    if blocked_rows:
        for r in blocked_rows:
            lines.append(f"- **{r['id']}**「{r['title']}」：{r['url']}（{r['error']}）")
    else:
        lines.append("（無）")
    lines.append("")

    unreachable_rows = [r for r in results if r["status"] == "unreachable"]
    if unreachable_rows:
        lines.append(f"## unreachable 清單（{len(unreachable_rows)} 份，網路錯誤／逾時）")
        for r in unreachable_rows:
            lines.append(f"- **{r['id']}**：{r['url']}（{r['error']}）")
        lines.append("")

    nv_rows = [r for r in results if r["status"] == "never-verified"]
    lines.append(f"## never-verified 明細（{len(nv_rows)} 份，第一次就驗不到的引句——"
                  f"不算 drift，但不准默默吞掉）")
    if nv_rows:
        for r in nv_rows:
            lines.append(f"- **{r['id']}**「{r['title']}」：{r['quotes_found']}/{r['quotes_total']} "
                         f"句驗到")
            for q in r["quotes_missing"]:
                lines.append(f"    - {q!r}")
    else:
        lines.append("（無）")
    lines.append("")

    nq_rows = [r for r in results if r["status"] == "no-quotes"]
    if nq_rows:
        lines.append(f"## no-quotes（{len(nq_rows)} 份，manifest 有列但沒有判準引用，"
                      f"只比對 sha）")
        for r in nq_rows:
            lines.append(f"- **{r['id']}**「{r['title']}」：{r['url']}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="來源改版監測：判準列引用的那句話，線上版還在不在")
    ap.add_argument("--only", default=None, help="只檢查這個 id")
    ap.add_argument("--update-baseline", action="store_true",
                    help="寫 data/sources/drift-baseline.json（平常執行不寫）")
    ap.add_argument("--report", default=None, help="報告 markdown 輸出路徑（預設 ROOT/.drift/report.md）")
    ap.add_argument("--json", default=None, dest="json_out",
                    help="報告 JSON 輸出路徑（預設 ROOT/.drift/report.json）")
    ap.add_argument("--timeout", type=int, default=60, help="每個請求逾時秒數（預設 60）")
    ap.add_argument("--workers", type=int, default=4, help="並行請求數（預設 4）")
    args = ap.parse_args()

    if not SOURCES.exists():
        print("❌ 找不到 data/sources/manifest.json", file=sys.stderr)
        return 3
    try:
        manifest = json.loads(SOURCES.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"❌ manifest.json 壞了：{e}", file=sys.stderr)
        return 3

    if args.only:
        filtered = [s for s in manifest if s["id"] == args.only]
        if not filtered:
            print(f"❌ manifest 裡沒有 id「{args.only}」", file=sys.stderr)
            return 3
        manifest = filtered

    baseline_map = {}
    if BASELINE.exists():
        try:
            baseline_rows = json.loads(BASELINE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"❌ drift-baseline.json 壞了：{e}", file=sys.stderr)
            return 3
        baseline_map = {r["id"]: r for r in baseline_rows}
    elif not args.update_baseline:
        print("❌ 找不到 data/sources/drift-baseline.json，先跑 "
              "--update-baseline 建立首次 baseline。", file=sys.stderr)
        return 3

    results = run(manifest, baseline_map, args.timeout, args.workers,
                  building=args.update_baseline)

    if args.update_baseline:
        write_baseline(results)
        print(f"✅ 已寫入 {BASELINE.relative_to(ROOT)}（{len(results)} 份）")

    out_dir = DEFAULT_OUT_DIR
    report_path = pathlib.Path(args.report) if args.report else out_dir / "report.md"
    json_path = pathlib.Path(args.json_out) if args.json_out else out_dir / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    report_md = render_report(results, len(manifest))
    report_path.write_text(report_md, encoding="utf-8")

    json_rows = []
    for r in results:
        row = {k: v for k, v in r.items() if k != "_baseline_entry_for_write"}
        json_rows.append(row)
    json_path.write_text(json.dumps(json_rows, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")

    print(report_md)
    print(f"（報告已寫入 {report_path}／{json_path}）")

    n_drift = sum(1 for r in results if r["status"] == "drift")
    n_reachable = sum(1 for r in results if r["status"] not in ("blocked", "unreachable"))

    if n_reachable == 0:
        print("🔴 全部 blocked／unreachable：監測本身失效，不是綠燈。", file=sys.stderr)
        return 2
    if n_drift:
        print(f"🔴 有 {n_drift} 份 drift，需要人看。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
