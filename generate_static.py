#!/usr/bin/env python3
"""Pre-render MOPS monthly-revenue treemaps to static JSON for site/.

Idempotent: fetches only months missing from site/data/, from 102/1 up to the
latest published month (published by the 10th of the following month).
Run with no args for the monthly refresh; --start/--end (ROC y_m) to override.
"""
import argparse
import datetime
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import requests

SITE = Path(__file__).resolve().parent / "site"
DATA = SITE / "data"
START = (102, 1)
COLS = ["產業別", "公司名稱", "營業收入-當月營收", "營業收入-上月營收",
        "累計營業收入-當月累計營收", "累計營業收入-去年累計營收"]


def latest_published(today=None):
    today = today or datetime.date.today()
    d = today.replace(day=1) - datetime.timedelta(days=1)
    if today.day < 11:
        d = d.replace(day=1) - datetime.timedelta(days=1)
    return d.year - 1911, d.month


def month_range(start, end):
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def new_session():
    # mops.twse.com.tw blocks this endpoint; the legacy mopsov host still
    # serves it but needs a session cookie from a prior GET
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    s.get("https://mopsov.twse.com.tw/mops/web/index", timeout=30)
    return s


def fetch_csv(s, year, month):
    payload = {
        "step": "9",
        "functionName": "show_file2",
        "filePath": "/t21/sii/",
        "fileName": f"t21sc03_{year}_{month}.csv",
    }
    r = s.post("https://mopsov.twse.com.tw/server-java/FileDownLoad", data=payload, timeout=60)
    r.encoding = "utf-8"
    if r.text.lstrip().startswith("<"):
        raise ValueError("MOPS returned error page (month not published yet?)")
    return pd.read_csv(io.StringIO(r.text))


def build_payload(df):
    df = df.copy()
    df["公司名稱"] = df["公司名稱"].astype(str) + "<br>" + df["公司代號"].astype(str)
    f = df[df["營業收入-當月營收"] > 0][COLS].copy()
    for col in COLS[2:]:
        f[col] = (f[col] / 100000).round(2)  # 千元 → 億元
    f["月營收增減"] = ((f["營業收入-當月營收"] - f["營業收入-上月營收"]) / f["營業收入-上月營收"].abs()).round(4)
    f["累計營收增減"] = ((f["累計營業收入-當月累計營收"] - f["累計營業收入-去年累計營收"]) / f["累計營業收入-去年累計營收"].abs()).round(4)
    limit = 0.5
    f["月營收變動"] = np.where(f["月營收增減"] > limit, limit,
                   np.where(f["月營收增減"] < -limit, -limit, f["月營收增減"]))

    fig = px.treemap(f,
                     path=[px.Constant("月營收"), "產業別", "公司名稱"],
                     values="營業收入-當月營收",
                     color="月營收變動",
                     color_continuous_scale="RdYlBu_r",
                     color_continuous_midpoint=0,
                     custom_data=["月營收增減", "累計營收增減",
                                  "累計營業收入-當月累計營收", "累計營業收入-去年累計營收"])
    fig.update_layout(autosize=True, margin=dict(t=30, l=10, r=10, b=5))
    fig.update_traces(hovertemplate="當月營收(億)：%{value:.0f}<br>營收增減: %{customdata[0]:.1%}<br>當年累計營收: %{customdata[2]:.0f}<br>累計營收增減: %{customdata[1]:.1%}")
    fig.update_traces(textinfo="label+percent entry", textfont_size=16)
    return {"count": int(len(f)), "fig": json.loads(fig.to_json())}


def rebuild_manifest():
    months = sorted((p.stem for p in DATA.glob("*.json")),
                    key=lambda k: (int(k.split("_")[0]), int(k.split("_")[1])))
    manifest = {
        "months": months,
        "latest": months[-1] if months else None,
        "updated": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    (SITE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
    return manifest


def parse_ym(s):
    y, m = s.split("_")
    return int(y), int(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=parse_ym, default=START, help="ROC y_m, e.g. 102_1")
    ap.add_argument("--end", type=parse_ym, default=latest_published(), help="ROC y_m")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    targets = [(y, m) for y, m in month_range(args.start, args.end)
               if not (DATA / f"{y}_{m}.json").exists()]
    print(f"{len(targets)} months to fetch (through {args.end[0]}_{args.end[1]})", flush=True)

    session, fetched, failed = None, 0, []
    for y, m in targets:
        if session is None or fetched % 24 == 0:
            session = new_session()
        try:
            payload = build_payload(fetch_csv(session, y, m))
            (DATA / f"{y}_{m}.json").write_text(json.dumps(payload, ensure_ascii=False))
            fetched += 1
            print(f"ok {y}_{m} ({payload['count']} companies)", flush=True)
        except Exception as e:
            failed.append(f"{y}_{m}")
            print(f"FAIL {y}_{m}: {e}", flush=True)
            session = None
        time.sleep(0.5)

    manifest = rebuild_manifest()
    print(f"done: {fetched} fetched, {len(failed)} failed {failed if failed else ''}; latest={manifest['latest']}", flush=True)
    return 1 if (failed and not fetched) else 0


if __name__ == "__main__":
    sys.exit(main())
