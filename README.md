# 上市公司每月營收 Treemap

台灣上市公司每月營收互動 treemap（產業別 → 公司），資料來自公開資訊觀測站（MOPS）。

線上版：https://monthly-revenue.super168.work/

## 架構

完全靜態，沒有後端應用程式：

- `generate_static.py` — 抓取 MOPS 月營收 CSV，為每個月份預先產生 Plotly figure JSON 到 `site/data/{民國年}_{月}.json`（約 180KB/月），並重建 `site/manifest.json`。**冪等**：只補缺少的月份，可重複執行。
- `site/index.html` — 純前端：讀 manifest 填年/月下拉選單，fetch 對應 JSON 後 `Plotly.newPlot` 繪圖。支援 URL hash 直連月份（如 `#115_5`）。
- `site/plotly.min.js` — 自帶 plotly.js（來自 pip `plotly` 套件的 `package_data`）。

月營收每月 10 日前公布，所以排程在每月 11–13 日跑 `generate_static.py` 即可自動補上新月份（多跑幾天是因為 MOPS 偶爾拒絕請求；冪等所以安全）。

## 使用

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 回補 102/1 至最新已公布月份（缺哪月抓哪月）
./venv/bin/python generate_static.py

# 本機預覽
python3 -m http.server 5200 --directory site
```

macOS launchd 部署範例（常駐 server + 每月自動更新）見 `deploy/`。

## MOPS 資料來源備註

- `mops.twse.com.tw/server-java/FileDownLoad` 已被擋（回傳安全性錯誤頁）；改走舊站 `mopsov.twse.com.tw`，且需先 GET 首頁取得 session cookie 再 POST 下載。
- CSV 檔名 `t21sc03_{民國年}_{月}.csv`，金額單位千元（除以 100000 = 億元）。
- 連續大量抓取時 MOPS 會隨機拒絕部分請求；`generate_static.py` 每 24 次請求換一個 session，失敗的月份重跑一次腳本即可補齊。

## 舊版

`monthly_revenue_app.py` 是原本的 Streamlit 版（已修正 MOPS 來源），保留參考用，現行部署不使用。
