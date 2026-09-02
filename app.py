import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="AI 5M 極速雷達與專屬操盤顧問", layout="centered")
st.title("🎯 AI 操盤系統 (山寨幣極速版)")

# ==========================================
# 共用核心演算法
# ==========================================
def get_overall_sr(df_1h, current_price):
    df_1h['swing_high'] = df_1h['high'] == df_1h['high'].rolling(window=11, center=True).max()
    df_1h['swing_low'] = df_1h['low'] == df_1h['low'].rolling(window=11, center=True).min()
    swing_highs = df_1h[df_1h['swing_high']]['high'].dropna().tolist()
    swing_lows = df_1h[df_1h['swing_low']]['low'].dropna().tolist()
    res_list = [h for h in swing_highs if h > current_price]
    sup_list = [l for l in swing_lows if l < current_price]
    return (min(res_list) if res_list else df_1h['high'].max(), 
            max(sup_list) if sup_list else df_1h['low'].min())

@st.cache_data(ttl=60, show_spinner=False)
def fetch_market_data():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try: tickers = exchange.fetch_tickers()
    except: return [], []
    
    all_symbols = []
    symbol_vol = []
    
    # ⛔ 終極黑名單：徹底封殺傳統金融與老大哥，專注高爆發山寨幣
    blacklist = [
        'GOLD', 'SILVER', 'XAU', 'XAG', 'WTI', 'BRENT', 'OIL', 'DXY', 
        'NVDA', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'COIN', 'BABA', 
        'SP500', 'NDX', 'DJI', 'NQ', 'US30', 'BTC', 'ETH'
    ]
    
    for sym, data in tickers.items():
        if sym.endswith(':USDT') and data.get('quoteVolume'):
            base = sym.split('/')[0].split('-')[0].split(':')[0]
            if base not in blacklist:
                all_symbols.append(sym)
                symbol_vol.append({'symbol': sym, 'volume': data['quoteVolume'], 'last': data['last'], 'pct': data.get('percentage', 0)})
    
    all_symbols = sorted(all_symbols)
    # 動態抓取全市場資金最集中的前 50 大山寨幣
    top_50 = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:50] 
    return all_symbols, top_50

@st.cache_data(ttl=60, show_spinner=False)
def run_radar_scan_multithread(top_50_market):
    signals = []
    
    def process_coin(item):
        sym = item['symbol']
        exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
        coin_signals = []
        try:
            ohlcv_4h = exchange.fetch_ohlcv(sym, '4h', limit=10)
            df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_4h['datetime'] = pd.to_datetime(df_4h['timestamp'], unit='ms')
            
            ohlcv_1h = exchange.fetch_ohlcv(sym, '1h', limit=210)
            df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            ohlcv_5m = exchange.fetch_ohlcv(sym, '5m', limit=100)
            df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            c_now_5m = df_5m['close'].iloc[-1]
            c_prev_5m = df_5m['close'].iloc[-2]
            c_prev2_5m = df_5m['close'].iloc[-3]
            
            res_level, sup_level = get_overall_sr(df_1h, c_now_5m)
            
            today_date = datetime.now(timezone.utc).date()
            first_4h = df_4h[(df_4h['datetime'].dt.date == today_date) & (df_4h['datetime'].dt.hour == 0)]
            range_high = first_4h['high'].values[0] if not first_4h.empty else None
            range_low = first_4h['low'].values[0] if not first_4h.empty else None
            
            if range_high and range_low:
                if c_prev2_5m < range_low and c_prev_5m > range_low:
                    sl = df_5m['low'].iloc[-5:-1].min()
                    risk = c_now_5m - sl
                    if risk > 0 and (risk / c_now_5m) <= 0.02:
                        tp = min(c_now_5m + (2.5 * risk), res_level * 0.998)
                        if (tp - c_now_5m) > (risk * 1.2):
                            coin_signals.append({'幣': sym, '方向': '🟢 做多', '進場': f"`{range_low:.4f}` ~ `{c_now_5m:.4f}`", '停損': sl, '停利': tp, '建議': f"🛡️ 4H 假跌破，上方壓力 {res_level:.4f}。"})
                elif c_prev2_5m > range_high and c_prev_5m < range_high:
                    sl = df_5m['high'].iloc[-5:-1].max()
                    risk = sl - c_now_5m
                    if risk > 0 and (risk / c_now_5m) <= 0.02:
                        tp = max(c_now_5m - (2.5 * risk), sup_level * 1.002)
                        if (c_now_5m - tp) > (risk * 1.2):
                            coin_signals.append({'幣': sym, '方向': '🔴 做空', '進場': f"`{c_now_5m:.4f}` ~ `{range_high:.4f}`", '停損': sl, '停利': tp, '建議': f"🛡️ 4H 假突破，下方支撐 {sup_level:.4f}。"})

            macd = df_5m.ta.macd(fast=12, slow=26, signal=9)
            macd_line = macd.iloc[-2, 0]
            signal_line = macd.iloc[-2, 2]
            
            if macd_line > signal_line and c_prev_5m > df_5m['high'].iloc[-15:-2].max():
                swing_high = df_5m['high'].iloc[-3:].max()
                e_0382 = swing_high - 0.382 * (swing_high - df_5m['low'].iloc[-15:-2].min())
                sl = df_5m['low'].iloc[-15:-2].min() * 0.998
                tp = min(e_0382 + (2.5 * (e_0382 - sl)), res_level * 0.998)
                if (tp - e_0382) > ((e_0382 - sl) * 1.2):
                    coin_signals.append({'幣': sym, '方向': '🟢 做多', '進場': f"`{e_0382:.4f}` 回踩", '停損': sl, '停利': tp, '建議': "🌟 動能向上突破，等待回踩。"})
            elif macd_line < signal_line and c_prev_5m < df_5m['low'].iloc[-15:-2].min():
                swing_low = df_5m['low'].iloc[-3:].min()
                e_0382 = swing_low + 0.382 * (df_5m['high'].iloc[-15:-2].max() - swing_low)
                sl = df_5m['high'].iloc[-15:-2].max() * 1.002
                tp = max(e_0382 - (2.5 * (sl - e_0382)), sup_level * 1.002)
                if (e_0382 - tp) > ((sl - e_0382) * 1.2):
                    coin_signals.append({'幣': sym, '方向': '🔴 做空', '進場': f"`{e_0382:.4f}` 反彈", '停損': sl, '停利': tp, '建議': "🌟 動能向下破底，等待反彈。"})
            return coin_signals
        except:
            return []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process_coin, item) for item in top_50_market]
        for future in as_completed(futures):
            result = future.result()
            if result:
                signals.extend(result)
                
    return signals

def analyze_single_coin(sym):
    exchange = ccxt.bingx({'enableRateLimit': False, 'timeout': 5000, 'options': {'defaultType': 'swap'}})
    try:
        ohlcv_1h = exchange.fetch_ohlcv(sym, '1h', limit=210)
        df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        ema200_1h = df_1h['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        
        ohlcv_5m = exchange.fetch_ohlcv(sym, '5m', limit=100)
        df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        current_price = df_5m['close'].iloc[-1]
        
        res, sup = get_overall_sr(df_1h, current_price)
        
        macd = df_5m.ta.macd(fast=12, slow=26, signal=9)
        macd_line = macd.iloc[-1, 0]
        signal_line = macd.iloc[-1, 2]
        
        return {
            'price': current_price,
            'trend_1h': 'BULLISH' if current_price > ema200_1h else 'BEARISH',
            'res': res, 'sup': sup,
            'macd_bullish': macd_line > signal_line
        }
    except:
        return None

# ==========================================
# 介面渲染區塊
# ==========================================
all_symbols, top_50_market = fetch_market_data()

tab1, tab2 = st.tabs(["📡 前50大極速雷達", "🤖 AI 專屬操盤顧問"])

with tab2:
    st.subheader("🤖 問問 AI：這張單該不該下？")
    ai_btn_clicked = False
    
    if all_symbols:
        st.write("選擇全市場**任何**幣種，AI 會立刻為你做最速盤面健檢。")
        col1, col2 = st.columns(2)
        with col1:
            target_coin = st.selectbox("你想操作哪個幣？(可輸入搜尋)", all_symbols)
        with col2:
            user_intent = st.selectbox("你的計畫是？", ["我想做多 (Long) 🟢", "我想做空 (Short) 🔴"])
            
        ai_btn = st.button("🧠 請 AI 顧問分析")
        
        if ai_btn:
            ai_btn_clicked = True 
            with st.spinner(f"⚡ AI 顧問啟動！正在為您即時解析 {target_coin} ..."):
                analysis = analyze_single_coin(target_coin)
                
            if analysis:
                st.divider()
                p = analysis['price']
                r = analysis['res']
                s = analysis['sup']
                trend = analysis['trend_1h']
                macd_up = analysis['macd_bullish']
                is_long = "做多" in user_intent
                
                room_up = ((r - p) / p) * 100
                room_down = ((p - s) / p) * 100
                score = 0
                feedback = []
                
                if is_long:
                    if trend == 'BULLISH':
                        score += 2
                        feedback.append("✅ **【大級別順風】** 1H 趨勢向上，做多安全。")
                    else:
                        feedback.append("⚠️ **【逆勢警告】** 1H 趨勢偏空，做多屬於逆勢接刀。")
                else:
                    if trend == 'BEARISH':
                        score += 2
                        feedback.append("✅ **【大級別順風】** 1H 趨勢向下，做空安全。")
                    else:
                        feedback.append("⚠️ **【逆勢警告】** 1H 趨勢偏多，做空等於阻擋火車。")
                        
                if is_long:
                    if room_up > 2.0:
                        score += 2
                        feedback.append(f"✅ **【空間充足】** 距上方壓力 `{r:.4f}` 還有 +{room_up:.2f}%。")
                    else:
                        feedback.append(f"❌ **【撞牆風險】** 距上方壓力 `{r:.4f}` 僅剩 +{room_up:.2f}%，極易被打停損！")
                else:
                    if room_down > 2.0:
                        score += 2
                        feedback.append(f"✅ **【空間充足】** 距下方支撐 `{s:.4f}` 還有 -{room_down:.2f}%。")
                    else:
                        feedback.append(f"❌ **【撞地風險】** 距下方支撐 `{s:.4f}` 僅剩 -{room_down:.2f}%，極易軋空反彈！")
                        
                if is_long and macd_up:
                    score += 1
                    feedback.append("✅ **【動能充沛】** 短線多頭動能正在爆發，易脫離成本區。")
                elif is_long and not macd_up:
                    feedback.append("⏳ **【動能衰退】** 短線動能偏弱，建議等待企穩再進。")
                elif not is_long and not macd_up:
                    score += 1
                    feedback.append("✅ **【動能充沛】** 短線空頭動能強勁。")
                elif not is_long and macd_up:
                    feedback.append("⏳ **【動能衰退】** 短線動能偏多，此時做空極易遭遇反彈。")

                if score >= 4:
                    st.success(f"### 📈 評分：強烈推薦 (高勝率)")
                    st.write("符合 SMC 邏輯的完美進場點！趨勢、空間與動能皆有利。")
                elif score >= 2:
                    st.warning(f"### ⚖️ 評分：中性偏弱 (需謹慎)")
                    st.write("條件好壞參半，極可能面臨上下洗盤，請嚴格設定停損。")
                else:
                    st.error(f"### 🛑 評分：極度危險 (建議放棄)")
                    st.write("盤面極差，切勿進場送錢。")

                st.markdown("---")
                for f in feedback: st.markdown(f)
                st.markdown("---")
                st.info("💡 **風控叮嚀**：單筆保證金請固定輸入 **10 USDT**！")
            else:
                st.error("無法取得即時數據，請稍後再試。")

with tab1:
    count = st_autorefresh(interval=60000, limit=None, key="auto_refresh")
    st.caption(f"🔄 網頁每 60 秒自動更新 | 當前共監控成交量前 50 大強勢山寨幣")
    
    if len(top_50_market) > 0:
        if ai_btn_clicked:
            st.warning("⏳ 正在為您優先解析 AI 顧問的需求，雷達掃描暫停一回合以確保速度！")
        else:
            with st.spinner('📡 雷達正在背景啟動【多執行緒】高速運算中...'):
                signals = run_radar_scan_multithread(top_50_market)
                
            if len(signals) > 0:
                st.subheader(f"💡 發現 {len(signals)} 個 AI 推薦進場機會")
                for sig in signals:
                    card = st.success if "多" in sig['方向'] else st.error
                    card(f"**{sig['幣']}** | {sig['方向']}\n\n"
                         f"🎯 **推薦進場**：{sig['進場']}\n\n"
                         f"🛑 **停損**：`{sig['停損']:.4f}` | 💰 **停利**：`{sig['停利']:.4f}`\n\n"
                         f"💡 {sig['建議']}")
            else:
                st.info("⚪ 目前前 50 大強勢山寨幣皆無合適進場訊號。安全第一，請耐心等待。")
