#!/usr/bin/env python3
"""Pre-render MOPS monthly-revenue treemaps to static JSON for site/.

Idempotent: fetches only months missing from site/data/, from 102/1 up to the
latest published month (published by the 10th of the following month).
Run with no args for the monthly refresh; --start/--end (ROC y_m) to override.

Each payload embeds four color arrays (signed-power scaled, 紅漲綠跌) so the
front-end can switch the momentum metric client-side:
  yoy 年增率 / acc 年增率加速(vs上月的年增率, pp) / mom 月增率 / cum 累計年增率
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
COLS = ["產業別", "公司名稱", "營業收入-當月營收", "營業收入-上月營收", "營業收入-去年當月營收",
        "累計營業收入-當月累計營收", "累計營業收入-去年累計營收"]
MONEY = COLS[2:]
CAPS = {"yoy": 0.5, "acc": 0.3, "mom": 0.5, "cum": 0.5}
GAMMA = 0.55  # signed-power scale: resolution near 0, ±cap saturates


def latest_published(today=None):
    today = today or datetime.date.today()
    d = today.replace(day=1) - datetime.timedelta(days=1)
    if today.day < 11:
        d = d.replace(day=1) - datetime.timedelta(days=1)
    return d.year - 1911, d.month


def prev_ym(y, m):
    return (y - 1, 12) if m == 1 else (y, m - 1)


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


def sratio(cur, base):
    if isinstance(base, pd.Series):
        return (cur - base) / base.where(base != 0).abs()
    if pd.isna(base) or float(base) == 0.0:
        return np.nan
    return (cur - base) / abs(base)


def spow(x, cap):
    if x is None or pd.isna(x) or np.isinf(x):
        return None
    return round(float(np.sign(x) * min(abs(x) / cap, 1.0) ** GAMMA), 3)


def fmt_pct(x):
    return "—" if x is None or pd.isna(x) or np.isinf(x) else f"{x:+.1%}"


def fmt_pp(x):
    return "—" if x is None or pd.isna(x) or np.isinf(x) else f"{x * 100:+.1f}pp"


def prev_view(prev_df):
    """Per-company / per-industry / total YoY of the PREVIOUS month (for acceleration)."""
    if prev_df is None:
        return None
    p = prev_df[["公司代號", "產業別", "營業收入-當月營收", "營業收入-去年當月營收"]].copy()
    ind = p.groupby("產業別")[["營業收入-當月營收", "營業收入-去年當月營收"]].sum()
    return {
        "by_co": dict(zip(p["公司代號"].astype(str),
                          sratio(p["營業收入-當月營收"], p["營業收入-去年當月營收"]))),
        "by_ind": dict(zip(ind.index,
                           sratio(ind["營業收入-當月營收"], ind["營業收入-去年當月營收"]))),
        "total": float(sratio(p["營業收入-當月營收"].sum(), p["營業收入-去年當月營收"].sum())),
    }


def node_metrics(row, prev_yoy):
    yoy = sratio(row["營業收入-當月營收"], row["營業收入-去年當月營收"])
    acc = yoy - prev_yoy if prev_yoy is not None and pd.notna(prev_yoy) and not np.isinf(prev_yoy) else np.nan
    return {
        "yoy": yoy,
        "acc": acc if pd.notna(yoy) and not np.isinf(yoy) else np.nan,
        "mom": sratio(row["營業收入-當月營收"], row["營業收入-上月營收"]),
        "cum": sratio(row["累計營業收入-當月累計營收"], row["累計營業收入-去年累計營收"]),
        "cumrev": row["累計營業收入-當月累計營收"],
    }


def build_payload(df, prev_df=None):
    df = df.copy()
    df["公司名稱"] = df["公司名稱"].astype(str)
    dup = df.duplicated(["產業別", "公司名稱"], keep=False)
    df.loc[dup, "公司名稱"] = df.loc[dup, "公司名稱"] + df.loc[dup, "公司代號"].astype(str)
    f = df[df["營業收入-當月營收"] > 0][COLS + ["公司代號"]].copy()
    for col in MONEY:
        f[col] = (f[col] / 100000).round(2)  # 千元 → 億元
    pv = prev_view(prev_df)

    f["_yoy"] = sratio(f["營業收入-當月營收"], f["營業收入-去年當月營收"])
    f["_c_default"] = pd.array([spow(x, CAPS["yoy"]) for x in f["_yoy"]], dtype="float64")

    fig = px.treemap(f,
                     path=[px.Constant("月營收"), "產業別", "公司名稱"],
                     values="營業收入-當月營收",
                     color="_c_default",
                     color_continuous_scale="RdYlGn_r",  # 紅漲綠跌
                     color_continuous_midpoint=0)
    fig.update_layout(autosize=True, margin=dict(t=30, l=10, r=10, b=5))
    fig.update_traces(hovertemplate=("當月營收(億)：%{value:.0f}"
                                     "<br>月增率: %{customdata[0]}"
                                     "<br>年增率: %{customdata[1]}"
                                     "<br>年增率加速: %{customdata[2]}"
                                     "<br>當年累計營收: %{customdata[4]}"
                                     "<br>累計年增率: %{customdata[3]}"
                                     "<extra>%{customdata[5]}</extra>"))
    # cells: name + share of WHOLE market only (no ticker codes); code moves to hover
    fig.update_traces(textinfo="label+percent root", textfont_size=16)

    # per-node metrics: leaves from rows, branches from industry/total sums
    # (px only aggregates `values` for branch nodes, not color/customdata)
    leaf = {f"月營收/{r['產業別']}/{r['公司名稱']}":
            node_metrics(r, pv["by_co"].get(str(r["公司代號"])) if pv else None)
            | {"code": str(r["公司代號"])}
            for _, r in f.iterrows()}
    sums = f.groupby("產業別")[MONEY].sum()
    ind = {name: node_metrics(r, pv["by_ind"].get(name) if pv else None)
           for name, r in sums.iterrows()}
    total = node_metrics(sums.sum(), pv["total"] if pv else None)

    tr = fig.data[0]
    colors = {k: [] for k in CAPS}
    cd = []
    for nid in tr.ids:
        parts = nid.split("/")
        v = total if len(parts) == 1 else ind.get(parts[1]) if len(parts) == 2 else leaf.get(nid)
        if v is None:  # industry name containing "/" etc. — leave uncolored
            v = {k: np.nan for k in CAPS} | {"cumrev": np.nan}
        for k in CAPS:
            colors[k].append(spow(v[k], CAPS[k]))
        cd.append([fmt_pct(v["mom"]), fmt_pct(v["yoy"]), fmt_pp(v["acc"]),
                   fmt_pct(v["cum"]), "—" if pd.isna(v["cumrev"]) else f"{v['cumrev']:,.0f}",
                   v.get("code", "")])
    tr.customdata = cd
    tr.marker.colors = colors["yoy"]
    fig.update_layout(coloraxis=dict(cmin=-1, cmax=1, cauto=False,
                                     colorbar=dict(title=dict(text="年增率"))))
    return {"count": int(len(f)), "colors": colors, "fig": json.loads(fig.to_json())}


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
    raw = {}  # (y, m) -> raw df, so sequential backfill reuses prev month

    def get_raw(s, y, m):
        if (y, m) not in raw:
            raw[(y, m)] = fetch_csv(s, y, m)
        return raw[(y, m)]

    for y, m in targets:
        if session is None or fetched % 24 == 0:
            session = new_session()
        try:
            cur = get_raw(session, y, m)
            try:
                prev = get_raw(session, *prev_ym(y, m))
            except Exception:
                prev = None  # acceleration column shows — for this month
            payload = build_payload(cur, prev)
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
