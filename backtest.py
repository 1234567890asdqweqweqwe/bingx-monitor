import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timedelta

# ==========================================
# 參數設定區
# ==========================================
RISK_PER_TRADE = 10.0  # 每筆交易固定承擔 10 USDT 的風險 (停損就是虧 10U)
DAYS_TO_TEST = 30      # 回測過去 30 天
# 挑選 5 支最具代表性的高爆發山寨幣進行測試
TEST_SYMBOLS = ['SOL/USDT', 'PEPE/USDT', 'WIF/USDT', 'SUI/USDT', 'DOGE/USDT']

print(f"🚀 啟動 SMC 策略歷史回測 (過去 {DAYS_TO_TEST} 天)...")
print(f"💰 風控設定：每筆交易固定風險 {RISK_PER_TRADE} USDT\n")

exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

def fetch_historical_data(symbol, timeframe, days):
    """抓取歷史 K 線資料 (處理分頁避免被限制)"""
    since = exchange.parse8601((datetime.utcnow() - timedelta(days=days)).isoformat())
    all_ohlcv = []
    while since < exchange.milliseconds():
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
            if not ohlcv:
                break
            since = ohlcv[-1][0] + 1
            all_ohlcv.extend(ohlcv)
            time.sleep(0.1)
        except Exception as e:
            print(f"抓取資料錯誤: {e}")
            break
    
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df.drop_duplicates(subset=['timestamp']).reset_index(drop=True)

# ==========================================
# 回測主迴圈
# ==========================================
total_trades = 0
winning_trades = 0
total_pnl = 0.0
trade_log = []

for sym in TEST_SYMBOLS:
    print(f"📥 正在下載 {sym} 歷史數據並計算指標...")
    df_15m = fetch_historical_data(sym, '15m', DAYS_TO_TEST)
    if df_15m.empty: continue
        
    # 計算 15M 指標
    df_15m.ta.macd(fast=12, slow=26, signal=9, append=True)
    df_15m.ta.adx(length=14, append=True)
    
    # 模擬 1H 大趨勢 (為簡化回測速度，用 15M 轉換 1H EMA200)
    df_15m['ema200_1h_proxy'] = df_15m['close'].ewm(span=200*4, adjust=False).mean() 
    
    in_trade = False
    entry_price, sl_price, tp1_price, tp2_price = 0, 0, 0, 0
    trade_direction = ""
    tp1_hit = False

    # 逐根 K 線進行歷史回放 (略過前面幾百根讓指標有時間計算)
    for i in range(800, len(df_15m)):
        current = df_15m.iloc[i]
        
        # -------------------------
        # 1. 檢查是否在交易中 (平倉邏輯)
        # -------------------------
        if in_trade:
            if trade_direction == "LONG":
                # 碰到停損
                if current['low'] <= sl_price:
                    loss = 0 if tp1_hit else -RISK_PER_TRADE # 若已到 TP1，停損設為保本
                    total_pnl += loss
                    trade_log.append(loss)
                    in_trade = False
                # 碰到 TP1 (1R)
                elif current['high'] >= tp1_price and not tp1_hit:
                    total_pnl += (RISK_PER_TRADE * 1.0 * 0.5) # 平倉一半，賺 0.5R
                    sl_price = entry_price # 停損移至保本
                    tp1_hit = True
                # 碰到 TP2 (2R)
                elif current['high'] >= tp2_price:
                    total_pnl += (RISK_PER_TRADE * 2.0 * 0.5) # 剩下的一半賺 2R
                    winning_trades += 1
                    in_trade = False
                    
            elif trade_direction == "SHORT":
                if current['high'] >= sl_price:
                    loss = 0 if tp1_hit else -RISK_PER_TRADE
                    total_pnl += loss
                    trade_log.append(loss)
                    in_trade = False
                elif current['low'] <= tp1_price and not tp1_hit:
                    total_pnl += (RISK_PER_TRADE * 1.0 * 0.5)
                    sl_price = entry_price
                    tp1_hit = True
                elif current['low'] <= tp2_price:
                    total_pnl += (RISK_PER_TRADE * 2.0 * 0.5)
                    winning_trades += 1
                    in_trade = False
            continue

        # -------------------------
        # 2. 尋找進場訊號 (進場邏輯)
        # -------------------------
        macd_line = df_15m['MACD_12_26_9'].iloc[i-1]
        signal_line = df_15m['MACDs_12_26_9'].iloc[i-1]
        adx_val = df_15m['ADX_14'].iloc[i-1]
        trend_up = current['close'] > current['ema200_1h_proxy']
        
        # 簡化版動能突破邏輯 (與你的 Telegram 邏輯相近)
        bos_bull = df_15m['close'].iloc[i-1] > df_15m['high'].iloc[i-15:i-2].max()
        bos_bear = df_15m['close'].iloc[i-1] < df_15m['low'].iloc[i-15:i-2].min()

        if adx_val > 20:
            # 多頭動能突破
            if macd_line > signal_line and bos_bull and trend_up:
                entry = current['close']
                sl = df_15m['low'].iloc[i-15:i-1].min() * 0.998
                risk = entry - sl
                if risk > 0 and 0.006 <= (risk / entry) <= 0.03: # 0.6% ~ 3% 停損防插針限制
                    in_trade = True
                    trade_direction = "LONG"
                    entry_price = entry
                    sl_price = sl
                    tp1_price = entry + (1.0 * risk)
                    tp2_price = entry + (2.0 * risk)
                    tp1_hit = False
                    total_trades += 1

            # 空頭動能跌破
            elif macd_line < signal_line and bos_bear and not trend_up:
                entry = current['close']
                sl = df_15m['high'].iloc[i-15:i-1].max() * 1.002
                risk = sl - entry
                if risk > 0 and 0.006 <= (risk / entry) <= 0.03:
                    in_trade = True
                    trade_direction = "SHORT"
                    entry_price = entry
                    sl_price = sl
                    tp1_price = entry - (1.0 * risk)
                    tp2_price = entry - (2.0 * risk)
                    tp1_hit = False
                    total_trades += 1

# ==========================================
# 輸出回測報告
# ==========================================
print("\n" + "="*40)
print("📊 SMC 山寨幣策略 - 30天歷史回測報告")
print("="*40)
print(f"🔹 測試幣種: {', '.join([s.split('/')[0] for s in TEST_SYMBOLS])}")
print(f"🔹 總交易次數: {total_trades} 次")

if total_trades > 0:
    win_rate = (winning_trades / total_trades) * 100
    print(f"🔹 完美獲利次數 (打到2R): {winning_trades} 次")
    print(f"🔹 勝率 (2R完全勝率): {win_rate:.2f}%")
    print(f"💰 預估總淨利 (Net Profit): {total_pnl:.2f} USDT")
    
    if total_pnl > 0:
        print("\n✅ 結論：策略具備正向數學期望值，能在市場中獲利！")
    else:
        print("\n❌ 結論：市場盤整期耗損過大，需考慮調整濾網或減少交易頻率。")
else:
    print("\n⚪ 結論：過去 30 天內沒有出現符合 S 級嚴格標準的交易機會。")
print("="*40)
