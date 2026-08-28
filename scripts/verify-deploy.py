#!/usr/bin/env python3
"""驗證線上內容 == repo 內容（整檔比對，不用人想的哨兵字串）。

為什麼存在
----------
「驗部署」這件事在本站群復發過 5 次以上，每次都是同一個根因的不同變種：
人挑一個字串當哨兵，而那個字串**在舊版本裡也存在** → 假陽性，以為驗過了。
歷次命中的其實是：CSS class 定義（舊版就有）、佔位符文字、404 fallback 頁的品牌字、
上一個 commit 已上線的卡片摘要、被 HTML 標籤截斷的字串。

HTTP 200 也不能當訊號：本站是決定性靜態產出，頁面幾乎永遠 200。

正解是**不要挑字串**：拿 repo 裡剛 build 出來的檔案跟線上整檔比對。
baseline 來自檔案，不來自人的記憶，所以沒有「挑錯哨兵」這個失敗模式。

用法
----
    python3 scripts/verify-deploy.py public-health/index.html
    python3 scripts/verify-deploy.py public-health/articles/*/index.html
    python3 scripts/verify-deploy.py --timeout 300 public-health/index.html
    python3 scripts/verify-deploy.py --site https://example.com public-health/index.html

站台解析順序：--site 或 SITE 環境變數 → config/site.json 的 base。

⚠️ 比對的 baseline 是「本機這一份檔案」，所以它必須是**剛 build 出來的那一份**。
   本站的排程是雲端重建後直接部署、產物不 commit 回 main，repo 裡那份可能是舊的；
   不先 build 就驗必然假警報。

不符時印出第一個差異點的前後文（診斷用，不是只給 pass/fail），
全部相符 exit 0，逾時仍不符 exit 1。
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
UA = "verify-deploy/1.0 (+twtools static site deploy check)"


def resolve_site(cli_site: str | None) -> str:
    """順序：--site / SITE env → config/site.json 的 base。
    先讀 config 是為了域名若異動時不必改這支腳本。"""
    if cli_site:
        return cli_site.rstrip("/")
    env = os.environ.get("SITE")
    if env:
        return env.rstrip("/")
    single = ROOT / "config" / "site.json"
    if single.exists():
        try:
            base = json.loads(single.read_text(encoding="utf-8")).get("base")
            if base:
                return base.rstrip("/")
        except (json.JSONDecodeError, OSError):
            pass
    print("❌ 認不出站台（config/site.json 讀不到 base），請用 --site 指定", file=sys.stderr)
    sys.exit(2)


SITE = ""  # 由 main() 解析後填入


def path_to_url(p: pathlib.Path) -> str:
    """public-health/indicators/index.html → <SITE>/indicators/ ；
    public-health/index.html → <SITE>/"""
    rel = p.resolve().relative_to(ROOT)
    parts = list(rel.parts)
    if not parts:
        raise ValueError(f"無法對應 URL：{p}")
    parts = parts[1:]  # 去掉 public-health/ 這層
    if parts and parts[-1] == "index.html":
        parts = parts[:-1]
        return f"{SITE}/" + ("/".join(parts) + "/" if parts else "")
    return f"{SITE}/" + "/".join(parts)


def fetch(url: str, cache_bust: bool) -> bytes:
    """用 curl 而不是 urllib：launchd 用的 framework Python 沒有系統憑證鏈，
    urllib 會在 CERTIFICATE_VERIFY_FAILED 掛掉。curl 在 macOS 與 GH Actions 都在。"""
    u = url
    if cache_bust:
        u += ("&" if "?" in u else "?") + f"cb={int(time.time() * 1000)}"
    r = subprocess.run(
        ["curl", "-sSL", "--max-time", "30", "-H", f"User-Agent: {UA}",
         "-H", "Cache-Control: no-cache", u],
        capture_output=True,
    )
    if r.returncode != 0:
        raise OSError(f"curl exit {r.returncode}: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout


def describe_diff(live: bytes, local: bytes, url: str) -> str:
    """指出第一個差異點在哪，附前後文——讓人看得出是『沒部署』還是『部署了但內容不同』。"""
    lines = [f"   線上 {len(live)} bytes / repo {len(local)} bytes"]
    n = min(len(live), len(local))
    i = next((k for k in range(n) if live[k] != local[k]), n)
    if i == n and len(live) != len(local):
        lines.append(f"   前 {n} bytes 相同，之後長度不同（可能是舊版被截斷或多了內容）")
        return "\n".join(lines)
    ctx = 90
    lo, hi = max(0, i - ctx), i + ctx
    lines.append(f"   第一個差異在 byte {i}：")
    lines.append(f"     線上… {live[lo:hi].decode('utf-8', 'replace')!r}")
    lines.append(f"     repo… {local[lo:hi].decode('utf-8', 'replace')!r}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="線上內容 == repo 內容 整檔比對")
    ap.add_argument("paths", nargs="+", help="repo 內已 build 的檔案路徑")
    ap.add_argument("--timeout", type=int, default=180,
                    help="等部署上線的總秒數（預設 180）")
    ap.add_argument("--interval", type=int, default=10, help="輪詢間隔秒數（預設 10）")
    ap.add_argument("--no-cache-bust", action="store_true", help="不加 ?cb= 查詢參數")
    ap.add_argument("--site", default=None, help="站台 base URL（預設自動解析）")
    args = ap.parse_args()

    global SITE
    SITE = resolve_site(args.site)

    targets = []
    for raw in args.paths:
        p = pathlib.Path(raw)
        if not p.is_file():
            print(f"❌ 檔案不存在：{raw}（要先 build）", file=sys.stderr)
            return 2
        targets.append((p, p.read_bytes(), path_to_url(p)))

    print(f"🔍 比對 {len(targets)} 個檔案 vs {SITE}（整檔 byte 比對，逾時 {args.timeout}s）")

    pending = list(targets)
    deadline = time.time() + args.timeout
    last_err = {}
    attempt = 0

    while pending:
        attempt += 1
        still = []
        for p, local, url in pending:
            try:
                live = fetch(url, not args.no_cache_bust)
            except OSError as e:
                last_err[url] = f"抓取失敗：{e}"
                still.append((p, local, url))
                continue
            if live == local:
                print(f"✅ {url}")
            else:
                last_err[url] = describe_diff(live, local, url)
                still.append((p, local, url))
        pending = still
        if not pending:
            break
        if time.time() >= deadline:
            break
        print(f"⏳ 尚有 {len(pending)} 個未同步（第 {attempt} 次），{args.interval}s 後重試…")
        time.sleep(args.interval)

    if pending:
        print(f"\n❌ 逾時仍不相符（{len(pending)} 個）：", file=sys.stderr)
        for _, _, url in pending:
            print(f" · {url}", file=sys.stderr)
            print(last_err.get(url, "   （無診斷資訊）"), file=sys.stderr)
        print("\n可能原因：部署尚未完成／部署未觸發（squash-merge 曾漏觸發）／"
              "本機產物不是最新（先跑 build）。", file=sys.stderr)
        return 1

    print(f"\n✅ 全部相符：線上內容與 repo 一致（{len(targets)} 個檔案）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
