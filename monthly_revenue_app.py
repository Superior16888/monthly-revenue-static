import datetime
import io

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="上市公司每月營收", layout="wide")
st.title("上市公司每月營收")

# Latest published month: revenue for month M is published by the 10th of M+1
_today = datetime.date.today()
_latest = _today.replace(day=1) - datetime.timedelta(days=1) if _today.day >= 11 else (
    _today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1) - datetime.timedelta(days=1)
_latest_roc_year = _latest.year - 1911

year = st.slider("選擇年度 (民國)", 102, _latest_roc_year, _latest_roc_year)
month = st.slider("選擇月份", 1, 12, _latest.month if year == _latest_roc_year else 12)


@st.cache_data(ttl=3600, show_spinner="下載 MOPS 月營收資料中…")
def monthly_revenue(year, month):
    # mops.twse.com.tw blocks this endpoint now; the legacy mopsov host still
    # serves it but requires a session cookie from a prior GET
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    s.get("https://mopsov.twse.com.tw/mops/web/index", timeout=30)
    url = "https://mopsov.twse.com.tw/server-java/FileDownLoad"
    payload = {
        "step": "9",
        "functionName": "show_file2",
        "filePath": "/t21/sii/",
        "fileName": f"t21sc03_{year}_{month}.csv",
    }
    response = s.post(url, data=payload, timeout=60)
    response.encoding = "utf-8"
    if response.text.lstrip().startswith("<"):
        raise ValueError("MOPS 回傳錯誤頁（該月份資料可能尚未公布）")
    df = pd.read_csv(io.StringIO(response.text))

    df["公司名稱"] = df["公司名稱"] + "<br>" + df["公司代號"].astype(str)
    df_filtered = df[df["營業收入-當月營收"] > 0]
    df_filtered = df_filtered[["產業別", "公司名稱", "營業收入-當月營收", "營業收入-上月營收",
                               "累計營業收入-當月累計營收", "累計營業收入-去年累計營收"]].copy()
    df_filtered["營業收入-當月營收"] = df_filtered["營業收入-當月營收"] / 100000
    df_filtered["營業收入-上月營收"] = df_filtered["營業收入-上月營收"] / 100000
    df_filtered["月營收增減"] = (df_filtered["營業收入-當月營收"] - df_filtered["營業收入-上月營收"]) / df_filtered["營業收入-上月營收"].abs()
    df_filtered["月營收變動"] = df_filtered["月營收增減"]
    df_filtered["累計營業收入-當月累計營收"] = df_filtered["累計營業收入-當月累計營收"] / 100000
    df_filtered["累計營業收入-去年累計營收"] = df_filtered["累計營業收入-去年累計營收"] / 100000
    df_filtered["累計營收增減"] = (df_filtered["累計營業收入-當月累計營收"] - df_filtered["累計營業收入-去年累計營收"]) / df_filtered["累計營業收入-去年累計營收"].abs()
    return df_filtered


try:
    df_filtered = monthly_revenue(year, month)
except Exception as e:
    st.error(f"無法取得 {year} 年 {month} 月資料：{e}")
    st.stop()

st.caption(f"民國 {year} 年 {month} 月 · 共 {len(df_filtered)} 家公司 · 單位：億元 · 資料來源：公開資訊觀測站")

limit = 0.5
df_filtered["月營收變動"] = np.where(df_filtered["月營收變動"] > limit, limit,
              np.where(df_filtered["月營收變動"] < -limit, -limit, df_filtered["月營收變動"]))
fig = px.treemap(df_filtered,
                 path=[px.Constant("月營收"), "產業別", "公司名稱"],
                 values="營業收入-當月營收",
                 color="月營收變動",
                 color_continuous_scale="RdYlBu_r",
                 width=1200, height=700,
                 color_continuous_midpoint=0,
                 custom_data=["月營收增減", "累計營收增減", "累計營業收入-當月累計營收", "累計營業收入-去年累計營收"])
fig.update_layout(autosize=True)
fig.update_layout(margin=dict(t=30, l=10, r=10, b=5))
fig.update_traces(hovertemplate="當月營收(億)：%{value:.0f}<br>營收增減: %{customdata[0]:.1%}<br>當年累計營收: %{customdata[2]:.0f}<br>累計營收增減: %{customdata[1]:.1%}")
fig.update_traces(textinfo="label+percent entry")
fig.update_traces(textfont_size=16)

st.plotly_chart(fig, use_container_width=True)
