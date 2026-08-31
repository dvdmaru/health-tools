#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build-sitemap.py — 從 data/sitemap-parts/<owner>.txt 組出 public-health/sitemap.xml。

sitemap manifest 模式：build-articles.py 與後續各 gen-*.py 各自只寫自己擁有的 part 檔
（data/sitemap-parts/<owner>.txt，一行一 URL），不再靠字串比對 read-modify-write 整個
sitemap.xml（舊做法跑序敏感、易踩踏）。本腳本依固定 owner 順序讀取全部 part、去重保序、
輸出最終 sitemap.xml。

某 owner 的 part 檔這次沒被重寫（該 generator 沒跑）→ 印警告、跳過；沿用磁碟上既有內容
（parts 檔進 git 即是保留機制）。parts 目錄整個不存在 → exit 1，不生成殘缺 sitemap。

跑序：build-articles.py 與各 generator 之後、部署 hard gate 之前。
用法：python3 scripts/build-sitemap.py
"""
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("healthlib", ROOT / "scripts" / "healthlib.py")
hl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hl)

# 固定 owner 序＝sitemap.xml 的頁面分組順序。M0 只有 articles（首頁＋文章索引＋各篇）；
# indicators／worksheet 由後續里程碑的生成器擁有，part 檔不存在時自然跳過。
# 2026-08-31 加 worksheet（scripts/gen-worksheet.py 的 /worksheet/ 列印工作表）。
OWNERS = ["articles", "indicators", "worksheet"]
# 單一 sitemap.xml 的上限（sitemaps.org 慣例 50,000，取保守值防邊界）。
MAX_PER_SITEMAP = 45000


def _urlset_xml(urls) -> str:
    body = "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}</urlset>\n")


def _read_part(p: pathlib.Path) -> list:
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def collect_urls(parts_dir: pathlib.Path) -> list:
    """依 OWNERS 序讀 part；**未列名的 part 一律照收並告警**，絕不靜默丟棄。

    ☠️ 姊妹站實際事故：新的生成器確實寫出了 part 檔，但本檔的 OWNERS 名單沒跟著加，
    collect_urls() 照著名單讀 → 那一整條線的頁面一頁都沒進 sitemap，而且全程零錯誤訊息。
    建置全綠、part 檔躺在磁碟上、sitemap 少了九成頁面，沒有任何一層會叫。

    所以這裡的預設方向是**收不是擋**：part 檔存在，就代表某支生成器刻意宣告「這些 URL
    要進 sitemap」。名單沒列到是名單的問題，不是那些 URL 的問題。未列名者附在已列名者
    之後（順序不確定但內容不漏），並印醒目告警要求補進 OWNERS。

    ⚠️ 反過來說，這裡**不能**改成 default-deny（只收名單內的）——那正是該次事故的成因。
    default-deny 該用在「例外清單」那種每筆都要具名理由的地方，不該用在辨識層。
    """
    urls, seen = [], set()
    for owner in OWNERS:
        p = parts_dir / f"{owner}.txt"
        if not p.exists():
            print(f"⚠️  sitemap part 缺席：{owner}（略過；沿用磁碟上既有內容——parts 進 git 即是保留機制）")
            continue
        seen.add(p.name)
        urls.extend(_read_part(p))

    stray = sorted(p for p in parts_dir.glob("*.txt")
                   if p.name not in seen and p.stem not in OWNERS)
    for p in stray:
        n = len(_read_part(p))
        print(f"🔴 sitemap part「{p.stem}」不在 OWNERS 名單裡（{n} 個 URL）——已照收，"
              f"但請把它加進 OWNERS 以固定排序。名單漏列曾讓整條線靜默缺席。")
        urls.extend(_read_part(p))

    return list(dict.fromkeys(urls))  # 去重保序


def main():
    parts_dir = ROOT / "data" / "sitemap-parts"
    if not parts_dir.exists():
        print(f"❌ {parts_dir} 不存在；先跑 scripts/build-articles.py 產生 sitemap parts",
              file=sys.stderr)
        sys.exit(1)

    urls = collect_urls(parts_dir)
    hl.PUB.mkdir(parents=True, exist_ok=True)

    if len(urls) <= MAX_PER_SITEMAP:
        (hl.PUB / "sitemap.xml").write_text(_urlset_xml(urls), encoding="utf-8")
        print(f"🗺️  sitemap.xml → {len(urls)} URLs（manifest 合併：{'、'.join(OWNERS)}）")
        return

    chunks = [urls[i:i + MAX_PER_SITEMAP] for i in range(0, len(urls), MAX_PER_SITEMAP)]
    index_entries = []
    for i, chunk in enumerate(chunks, start=1):
        fname = f"sitemap-{i}.xml"
        (hl.PUB / fname).write_text(_urlset_xml(chunk), encoding="utf-8")
        index_entries.append(f"  <sitemap><loc>{hl.BASE}/{fname}</loc></sitemap>\n")
    (hl.PUB / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{''.join(index_entries)}</sitemapindex>\n", encoding="utf-8")
    print(f"🗺️  sitemap index → {len(chunks)} 個子 sitemap（總 {len(urls)} URLs，"
          f"超過單檔 {MAX_PER_SITEMAP} 上限）")


if __name__ == "__main__":
    main()
