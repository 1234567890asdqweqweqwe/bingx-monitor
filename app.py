import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="AI 15分鐘波段狙擊 (大戶防線版)", layout="centered")
st.title("🎯 15分鐘波段狙擊 ＋ 大戶防線")
st.write("嚴格追蹤 1H 級別大波段壓力與支撐，並在 15 分鐘級別精準預測進場區間。")

count = st_autorefresh(interval=60000, limit=None, key="auto_refresh")

def get_overall_sr(df_1h, current_price):
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
    try: tickers = exchange.fetch_tickers()
    except Exception: return pd.DataFrame(), []

    all_coins, symbol_vol = [], []
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
            ohlcv_4h = exchange.fetch_ohlcv(sym, '4h', limit=10)
            df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_4h['datetime'] = pd.to_datetime(df_4h['timestamp'], unit='ms')
            
            ohlcv_1h = exchange.fetch_ohlcv(sym, '1h', limit=210)
            df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # 核心邏輯切換至 15M
            ohlcv_15m = exchange.fetch_ohlcv(sym, '15m', limit=250)
            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_close_15m = df_15m['close'].iloc[-2]
            current_now_15m = df_15m['close'].iloc[-1]
            prev_close_15m = df_15m['close'].iloc[-3]

            resistance_level, support_level = get_overall_sr(df_1h, current_now_15m)

            # --- 引擎 A：4H 區間假突破 (15M 觸發) ---
            today_date = datetime.now(timezone.utc).date()
            first_4h = df_4h[(df_4h['datetime'].dt.date == today_date) & (df_4h['datetime'].dt.hour == 0)]
            range_high = first_4h['high'].values[0] if not first_4h.empty else None
            range_low = first_4h['low'].values[0] if not first_4h.empty else None
            
            if range_high and range_low:
                if prev_close_15m < range_low and current_close_15m > range_low:
                    sl_price = df_15m['low'].iloc[-5:-1].min()
                    risk = current_now_15m - sl_price
                    if risk > 0 and (risk / current_now_15m) <= 0.03:
                        tp_price = min(current_now_15m + (2.5 * risk), resistance_level * 0.998)
                        if (tp_price - current_now_15m) > (risk * 1.2):
                            signals.append({
                                '幣種': sym.split(':')[0],
                                '方向': '🟢 15M 強勢做多 (Long)',
                                '預測': '⚡ 4H 假跌破，15M 結構已確認反轉上漲',
                                '進場': f"`{range_low:.4f}` ~ `{current_now_15m:.4f}`",
                                '停損': sl_price, '停利': tp_price,
                                '建議': f"🛡️ 空間充足！上方 1H 壓力為 {resistance_level:.4f}。"
                            })
                elif prev_close_15m > range_high and current_close_15m < range_high:
                    sl_price = df_15m['high'].iloc[-5:-1].max()
                    risk = sl_price - current_now_15m
                    if risk > 0 and (risk / current_now_15m) <= 0.03:
                        tp_price = max(current_now_15m - (2.5 * risk), support_level * 1.002)
                        if (current_now_15m - tp_price) > (risk * 1.2):
                            signals.append({
                                '幣種': sym.split(':')[0],
                                '方向': '🔴 15M 強勢做空 (Short)',
                                '預測': '⚡ 4H 假突破，15M 結構已確認反轉暴跌',
                                '進場': f"`{current_now_15m:.4f}` ~ `{range_high:.4f}`",
                                '停損': sl_price, '停利': tp_price,
                                '建議': f"🛡️ 空間充足！下方 1H 支撐為 {support_level:.4f}。"
                            })

            # --- 引擎 B：淺回撤動能預測 (15M) ---
            macd = df_15m.ta.macd(fast=12, slow=26, signal=9)
            macd_line = macd.iloc[-2, 0]
            signal_line = macd.iloc[-2, 2]
            bos_bull = current_close_15m > df_15m['high'].iloc[-15:-2].max()
            bos_bear = current_close_15m < df_15m['low'].iloc[-15:-2].min()
            
            if macd_line > signal_line and bos_bull:
                swing_high = df_15m['high'].iloc[-3:].max()
                e_0382 = swing_high - 0.382 * (swing_high - df_15m['low'].iloc[-15:-2].min())
                e_0618 = swing_high - 0.618 * (swing_high - df_15m['low'].iloc[-15:-2].min())
                sl_price = df_15m['low'].iloc[-15:-2].min() * 0.998
                tp_price = min(e_0382 + (2.5 * (e_0382 - sl_price)), resistance_level * 0.998)
                if (tp_price - e_0382) > ((e_0382 - sl_price) * 1.2):
                    signals.append({
                        '幣種': sym.split(':')[0], '方向': '🟢 15M 回踩做多',
                        '預測': '🌟 動能突破，首波回踩後將再創高',
                        '進場': f"`{e_0618:.4f}` ~ `{e_0382:.4f}`", '停損': sl_price, '停利': tp_price,
                        '建議': f"若現價在區間內可直接進場。🛡️ 已避開上方壓力。"
                    })
        except Exception:
            pass
        time.sleep(0.05)
        
    return df_all_market, signals

st.caption(f"🔄 最後掃描時間：{time.strftime('%Y-%m-%d %H:%M:%S')}")
st.divider()

with st.spinner('📡 正在以 15M 級別掃描，過濾高風險交易...'):
    df_market, active_signals = scan_market()

if not df_market.empty:
    st.subheader(f"💡 15 分鐘波段進場 (已通過整體結構防護)")
    if len(active_signals) > 0:
        for sig in active_signals:
            card_color = st.success if "多" in sig['方向'] else st.error
            card_color(f"**{sig['幣種']}** | {sig['方向']}\n\n"
                       f"**預測走勢**：{sig['預測']}\n\n"
                       f"🎯 **推薦進場**：{sig['進場']}\n\n"
                       f"🛑 **停損價**：`{sig['停損']:.4f}` | 💰 **停利價**：`{sig['停利']:.4f}`\n\n"
                       f"💡 **AI 策略點評**：{sig['建議']}")
    else:
        st.info("⚪ 目前 15 分鐘線無充足盈虧比的好訊號。請保持紀律，等待安全機會！")
