#!/bin/bash
# 把 site/data/ 備份到 VPS。
#
# 這是**純備份**，不是部署 —— VPS 上沒有任何服務會讀這個目錄。
# 目的單純是讓這份資料不再是單點：
#   site/data/ 是 326 個 JSON、54 MB，被 .gitignore 排除在版控之外
#   （二進位／大量 JSON 進 git 一年會膨脹好幾 GB，那個決定是對的），
#   所以在此之前它**只存在於這台 Mac**。硬碟掛掉就沒了，而且是重爬不回來的
#   歷史月營收。程式碼有 GitHub，資料沒有。
#
# 資料只在每月 11/12/13 日 10:40 由 com.paulhsu.monthly-revenue-update
# 更新（月營收公布日），所以每天跑一次綽綽有餘；沒變動的日子 rsync 只比對
# 不傳輸，成本接近零。
#
# 設定（可用環境變數覆寫，或寫進 deploy/sync-data-to-vps.conf）：
VPS_HOST="${VPS_HOST:-}"                       # 例如 admin@203.0.113.10
VPS_BACKUP_DIR="${VPS_BACKUP_DIR:-/home/admin/backup/monthly-revenue}"
SRC="${SRC:-$HOME/Desktop/Blogger/monthly_revenue/site/data}"
LOG="${LOG:-/tmp/monthly_revenue_vps_sync.log}"

set -uo pipefail

_conf="$(dirname "$0")/sync-data-to-vps.conf"
[ -f "$_conf" ] && . "$_conf"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

if [ -z "$VPS_HOST" ]; then
    log "❌ 未設定 VPS_HOST（見 deploy/sync-data-to-vps.conf.example）"
    exit 1
fi

# 同一時間只跑一份。Mac 常在睡眠中錯過排程，醒來後 launchd 可能連續補跑。
LOCK=/tmp/monthly_revenue_vps_sync.lock
if ! mkdir "$LOCK" 2>/dev/null; then
    log "⏭️  上一次同步還在進行，略過"
    exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

[ -d "$SRC" ] || { log "❌ 找不到來源 $SRC"; exit 1; }

# VPS 連不上是常態（斷網／剛從睡眠醒來），安靜結束即可。
if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$VPS_HOST" true 2>/dev/null; then
    log "⏭️  VPS 連不上（$VPS_HOST），略過這次同步"
    exit 0
fi

ssh "$VPS_HOST" "mkdir -p '$VPS_BACKUP_DIR'" 2>>"$LOG" || {
    log "❌ 無法在遠端建立 $VPS_BACKUP_DIR"; exit 1; }

# --delete 讓備份與來源一致（舊月份若被重新命名，備份不留孤兒）。
# 這裡安全，因為整個目錄由 generate_static.py 產生，VPS 端不會自己寫。
# 刻意**不加** --update：這是備份，來源永遠是唯一真相。
if rsync -az --delete --timeout=300 "$SRC/" "$VPS_HOST:$VPS_BACKUP_DIR/" >>"$LOG" 2>&1; then
    n=$(ls -1 "$SRC" | wc -l | tr -d ' ')
    log "✅ 已備份 site/data（$n 個檔，$(du -sh "$SRC" | cut -f1)）"
else
    log "❌ rsync 失敗"; exit 1
fi
