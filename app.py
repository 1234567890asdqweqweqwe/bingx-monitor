import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="AI 5分鐘極速雷達 (含整體S/R防護)", layout="centered")
st.title("🎯 5分鐘極速雷達 ＋ 結構防護")
st.write("每 60 秒掃描全市場 5 分鐘 K 線，尋找高頻交易機會，並以 1H 歷史防線確保利潤空間。")

# 設定網頁每 60 秒自動更新
count = st_autorefresh(interval=60000, limit=None, key="auto_refresh")

def get_overall_sr(df_1h, current_price):
    """計算 1H 級別的大戶整體波段壓力與支撐"""
    df_1h['swing_high'] = df_1h['high'] == df_1h['high'].rolling(window=11, center=True).max()
    df_1h['swing_low'] = df_1h['low'] == df_1h['low'].rolling(window=11, center=True).min()
    swing_highs = df_1h[df_1h['swing_high']]['high'].dropna().tolist()
    swing_lows = df_1h[df_1h['swing_low']]['low'].dropna().tolist()
    res_list = [h for h in swing_highs if h > current_price]
    sup_list = [l for l in swing_lows if l < current_price]
    return (min(res_list) if res_list else df_1h['high'].max(), 
            max(sup_list) if sup_list else df_1h['low'].min())

@st.cache_data(ttl=50)
def scan_market():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try: 
        tickers = exchange.fetch_tickers()
    except Exception: 
        return pd.DataFrame(), []

    all_coins, symbol_vol = [], []
    # 嚴格過濾傳統股市、指數
    blacklist = ['NVDA', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'COIN', 'SP500', 'NDX', 'DJI', 'GOLD', 'SILVER', 'NQ', 'BABA']
    
    for sym, data in tickers.items():
        if sym.endswith(':USDT') and data.get('quoteVolume') and data.get('percentage') is not None:
            if sym.split('/')[0].split('-')[0].split(':')[0] in blacklist: continue
            all_coins.append({'幣種': sym.split(':')[0], '最新價格': data['last'], '24H漲跌(%)': data['percentage']})
            symbol_vol.append({'symbol': sym, 'volume': data['quoteVolume']})
            
    df_all_market = pd.DataFrame(all_coins).sort_values(by='24H漲跌(%)', ascending=False)
    top_40 = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:40]
    signals = []
    
    for item in top_40:
        sym = item['symbol']
        try:
            # 獲取 4H 每日區間數據
            ohlcv_4h = exchange.fetch_ohlcv(sym, '4h', limit=10)
            df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_4h['datetime'] = pd.to_datetime(df_4h['timestamp'], unit='ms')
            
            # 獲取 1H 數據 (用於 S/R 大戶防線)
            ohlcv_1h = exchange.fetch_ohlcv(sym, '1h', limit=210)
            df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # 核心判斷：改回 5M 極速級別
            ohlcv_5m = exchange.fetch_ohlcv(sym, '5m', limit=100)
            df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_close_5m = df_5m['close'].iloc[-2]
            current_now_5m = df_5m['close'].iloc[-1]
            prev_close_5m = df_5m['close'].iloc[-3]

            # 🛡️ 取得 1H 級別大戶壓力與支撐
            resistance_level, support_level = get_overall_sr(df_1h, current_now_5m)

            # --- 引擎 A：4H 區間假突破 (5M 觸發) ---
            today_date = datetime.now(timezone.utc).date()
            first_4h = df_4h[(df_4h['datetime'].dt.date == today_date) & (df_4h['datetime'].dt.hour == 0)]
            range_high = first_4h['high'].values[0] if not first_4h.empty else None
            range_low = first_4h['low'].values[0] if not first_4h.empty else None
            
            if range_high and range_low:
                # 5M 假跌破做多
                if prev_close_5m < range_low and current_close_5m > range_low:
                    sl_price = df_5m['low'].iloc[-5:-1].min()
                    risk = current_now_5m - sl_price
                    if risk > 0 and (risk / current_now_5m) <= 0.02:
                        tp_price = min(current_now_5m + (2.5 * risk), resistance_level * 0.998)
                        if (tp_price - current_now_5m) > (risk * 1.2):
                            signals.append({
                                '幣種': sym.split(':')[0],
                                '方向': '🟢 5M 極速做多 (Long)',
                                '進場': f"`{range_low:.4f}` ~ `{current_now_5m:.4f}`",
                                '停損': sl_price, '停利': tp_price,
                                '建議': f"⚡ 5M 假跌破。上方 1H 壓力為 {resistance_level:.4f}，空間充足！"
                            })
                # 5M 假突破做空
                elif prev_close_5m > range_high and current_close_5m < range_high:
                    sl_price = df_5m['high'].iloc[-5:-1].max()
                    risk = sl_price - current_now_5m
                    if risk > 0 and (risk / current_now_5m) <= 0.02:
                        tp_price = max(current_now_5m - (2.5 * risk), support_level * 1.002)
                        if (current_now_5m - tp_price) > (risk * 1.2):
                            signals.append({
                                '幣種': sym.split(':')[0],
                                '方向': '🔴 5M 極速做空 (Short)',
                                '進場': f"`{current_now_5m:.4f}` ~ `{range_high:.4f}`",
                                '停損': sl_price, '停利': tp_price,
                                '建議': f"⚡ 5M 假突破。下方 1H 支撐為 {support_level:.4f}，空間充足！"
                            })

            # --- 引擎 B：5M 淺回撤動能預測 ---
            macd = df_5m.ta.macd(fast=12, slow=26, signal=9)
            macd_line = macd.iloc[-2, 0]
            signal_line = macd.iloc[-2, 2]
            
            if macd_line > signal_line and current_close_5m > df_5m['high'].iloc[-15:-2].max():
                swing_high = df_5m['high'].iloc[-3:].max()
                e_0382 = swing_high - 0.382 * (swing_high - df_5m['low'].iloc[-15:-2].min())
                e_0618 = swing_high - 0.618 * (swing_high - df_5m['low'].iloc[-15:-2].min())
                sl_price = df_5m['low'].iloc[-15:-2].min() * 0.998
                tp_price = min(e_0382 + (2.5 * (e_0382 - sl_price)), resistance_level * 0.998)
                if (tp_price - e_0382) > ((e_0382 - sl_price) * 1.2):
                    signals.append({
                        '幣種': sym.split(':')[0], '方向': '🟢 5M 突破回踩 (Long)',
                        '進場': f"`{e_0618:.4f}` ~ `{e_0382:.4f}`", '停損': sl_price, '停利': tp_price,
                        '建議': f"🌟 5M 動能突破，等待回踩區間。已過濾上方壓力。"
                    })
            elif macd_line < signal_line and current_close_5m < df_5m['low'].iloc[-15:-2].min():
                swing_low = df_5m['low'].iloc[-3:].min()
                e_0382 = swing_low + 0.382 * (df_5m['high'].iloc[-15:-2].max() - swing_low)
                e_0618 = swing_low + 0.618 * (df_5m['high'].iloc[-15:-2].max() - swing_low)
                sl_price = df_5m['high'].iloc[-15:-2].max() * 1.002
                tp_price = max(e_0382 - (2.5 * (sl_price - e_0382)), support_level * 1.002)
                if (e_0382 - tp_price) > ((sl_price - e_0382) * 1.2):
                    signals.append({
                        '幣種': sym.split(':')[0], '方向': '🔴 5M 跌破反彈 (Short)',
                        '進場': f"`{e_0382:.4f}` ~ `{e_0618:.4f}`", '停損': sl_price, '停利': tp_price,
                        '建議': f"🌟 5M 支撐跌破，等待反彈區間。已過濾下方支撐。"
                    })

        except Exception:
            pass
        time.sleep(0.05)
        
    return df_all_market, signals

# ==========================================
# 畫面渲染區塊
# ==========================================
st.caption(f"🔄 最後掃描時間：{time.strftime('%Y-%m-%d %H:%M:%S')}")
st.divider()

with st.spinner('📡 正在以 5M 級別掃描全市場...'):
    df_market, active_signals = scan_market()

if not df_market.empty:
    st.subheader(f"💡 5 分鐘極速雷達 (已過濾高風險壓力位)")
    if len(active_signals) > 0:
        for sig in active_signals:
            card_color = st.success if "多" in sig['方向'] else st.error
            card_color(f"**{sig['幣種']}** | {sig['方向']}\n\n"
                       f"🎯 **推薦進場**：{sig['進場']}\n\n"
                       f"🛑 **停損價**：`{sig['停損']:.4f}` | 💰 **停利價**：`{sig['停利']:.4f}`\n\n"
                       f"💡 **AI 策略點評**：{sig['建議']}")
    else:
        st.info("⚪ 目前 5 分鐘線無充足盈虧比的好訊號。請隨時留意網頁更新狀態！")
        
    st.divider()
    
    st.subheader("📊 幣圈 24H 漲跌排行榜")
    tab1, tab2 = st.tabs(["🔥 漲幅榜", "❄️ 跌幅榜"])
    
    with tab1:
        df_gainers = df_market.head(10).copy()
        df_gainers['24H漲跌(%)'] = df_gainers['24H漲跌(%)'].apply(lambda x: f"+{x:.2f}%")
        st.dataframe(df_gainers[['幣種', '最新價格', '24H漲跌(%)']], use_container_width=True, hide_index=True)
        
    with tab2:
        df_losers = df_market.tail(10).sort_values(by='24H漲跌(%)', ascending=True).copy()
        df_losers['24H漲跌(%)'] = df_losers['24H漲跌(%)'].apply(lambda x: f"{x:.2f}%")
        st.dataframe(df_losers[['幣種', '最新價格', '24H漲跌(%)']], use_container_width=True, hide_index=True)
