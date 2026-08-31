import ccxt
import requests
import os
import time
import pandas as pd
import pandas_ta as ta
from datetime import datetime

# ==========================================
# 1. 讀取環境變數金鑰 (GitHub Actions 會自動帶入)
# ==========================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

# ==========================================
# 2. 設定監控參數
# ==========================================
SCAN_TOP_N = 30             # 自動掃描全市場成交量前 30 大幣種
FUNDING_THRESHOLD = 0.0005  # 資金費率門檻 (0.05%)
TIMEFRAME = '1h'            # 技術分析 K 線週期 (1小時線)

# ==========================================
# 3. 定義板塊與代表幣種 (板塊分類字典)
# ==========================================
SECTORS = {
    "🐶 迷因幣 (Meme)": ["DOGE", "SHIB", "PEPE", "WIF", "BOME", "FLOKI", "BONK"],
    "🤖 人工智慧 (AI)": ["FET", "RNDR", "WLD", "TAO", "AR", "NEAR", "GRT"],
    "🚀 公鏈 (Layer 1)": ["BTC", "ETH", "SOL", "AVAX", "SUI", "APT", "SEI"],
    "🎮 遊戲 (GameFi)": ["GALA", "PIXEL", "IMX", "RON", "YGG", "BIGTIME"],
    "🏦 去中心化金融 (DeFi)": ["UNI", "LINK", "AAVE", "MKR", "CRV", "RUNE"]
}

# ==========================================
# 發送 Telegram 訊息函數
# ==========================================
def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("尚未設定 Telegram 金鑰，無法發送訊息")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"發送 Telegram 失敗: {e}")

# ==========================================
# 主監控程式
# ==========================================
def main():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 啟動全方位監控 (資金費率 + 技術分析 + 板塊流向)...")
    
    try:
        # 抓取全市場 24H 行情
        tickers = exchange.fetch_tickers()
        
        # ------------------------------------------------
        # 任務一：計算並發送「板塊資金流向」報告
        # ------------------------------------------------
        sector_stats = []
        for sector_name, coins in SECTORS.items():
            total_volume = 0
            total_change = 0
            valid_coin_count = 0
            
            for coin in coins:
                sym = f"{coin}/USDT:USDT" # 組合成 BingX 合約交易對格式
                if sym in tickers:
                    data = tickers[sym]
                    if data.get('quoteVolume') and data.get('percentage') is not None:
                        total_volume += data['quoteVolume']
                        total_change += data['percentage']
                        valid_coin_count += 1
            
            if valid_coin_count > 0:
                avg_change = total_change / valid_coin_count
                sector_stats.append({
                    'name': sector_name,
                    'volume': total_volume,
                    'avg_change': avg_change
                })
        
        # 依照平均漲跌幅排序
        sector_stats = sorted(sector_stats, key=lambda x: x['avg_change'], reverse=True)
        
        # 組合 Telegram 報告訊息
        sector_msg_lines = ["🌍 *當前市場板塊熱度排行* 🌍\n"]
        for i, stat in enumerate(sector_stats):
            vol_millions = stat['volume'] / 1_000_000
            emoji = "🔥" if stat['avg_change'] > 0 else "❄️"
            sector_msg_lines.append(
                f"{i+1}. {stat['name']}\n"
                f"   {emoji} 平均漲跌: *{stat['avg_change']:.2f}%* | 💰 資金量: {vol_millions:.0f}M"
            )
            
        send_telegram_message("\n\n".join(sector_msg_lines))
        
        # ------------------------------------------------
        # 任務二：動態篩選熱門山寨幣 (Top 30)
        # ------------------------------------------------
        symbol_vol = []
        for sym, data in tickers.items():
            if sym.endswith(':USDT') and data.get('quoteVolume') is not None:
                symbol_vol.append({'symbol': sym, 'volume': data['quoteVolume']})
                
        # 依成交量排序，取出前 30 大幣種
        top_symbols = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:SCAN_TOP_N]
        watch_list = [item['symbol'] for item in top_symbols]
        print(f"✅ 篩選完成！即將監控以下幣種：\n{', '.join([s.split('/')[0] for s in watch_list])}\n")

    except Exception as e:
        print(f"取得全市場行情或計算失敗: {e}")
        return

    # ------------------------------------------------
    # 任務三：開始逐一監控 (資金費率 + 爆量/超賣)
    # ------------------------------------------------
    for symbol in watch_list:
        print(f"正在分析 {symbol} ...")
        try:
            # 檢查 1: 資金費率
            funding_info = exchange.fetch_funding_rate(symbol)
            funding_rate = funding_info.get('fundingRate', 0)
            
            if funding_rate > FUNDING_THRESHOLD:
                rate_pct = funding_rate * 100
                apr = rate_pct * 3 * 365
                msg = (
                    f"💰 *高資金費率警報* 💰\n\n"
                    f"🪙 幣種：`{symbol}`\n"
                    f"🔥 當前費率：*{rate_pct:.4f}%*\n"
                    f"📈 預估年化：*{apr:.1f}%*\n"
                    f"💡 狀態：多軍情緒過熱，適合評估期現套利！"
                )
                send_telegram_message(msg)

            # 檢查 2: RSI 超賣與成交量爆量
            ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            if len(df) >= 30: # 確保新幣上市時間夠長
                df.ta.rsi(length=14, append=True)
                df['Vol_MA20'] = df['volume'].rolling(window=20).mean()
                
                latest = df.iloc[-1]
                alerts = []
                
                if latest['RSI_14'] < 30:
                    alerts.append(f"🟢 *RSI 超賣*：數值為 {latest['RSI_14']:.1f}")
                    
                if latest['volume'] > (latest['Vol_MA20'] * 2):
                    if latest['close'] > latest['open']:
                        alerts.append(f"🔥 *爆量上漲*：買盤積極介入")
                    else:
                        alerts.append(f"⚠️ *爆量下跌*：賣壓沉重")
                
                if len(alerts) > 0:
                    alert_text = "\n".join(alerts)
                    tech_msg = (
                        f"📊 *技術面訊號觸發* 📊\n\n"
                        f"🪙 幣種：`{symbol}`\n"
                        f"⏱ 週期：{TIMEFRAME}\n"
                        f"💵 當前價格：*{latest['close']}*\n\n"
                        f"{alert_text}"
                    )
                    send_telegram_message(tech_msg)

        except Exception as e:
            print(f"分析 {symbol} 時發生錯誤: {e}")
            
        # 強制暫停 1 秒，避免被交易所阻擋連線
        time.sleep(1) 

if __name__ == '__main__':
    main()