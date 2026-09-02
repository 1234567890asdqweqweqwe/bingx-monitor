import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="AI 5M 極速雷達與量化操盤顧問", layout="centered")
st.title("🎯 AI 操盤系統 (多執行緒 ＋ 機構級量化顧問)")

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
    blacklist = ['NVDA', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'COIN', 'SP500', 'NDX', 'DJI', 'GOLD', 'SILVER', 'NQ', 'BABA']
    
    for sym, data in tickers.items():
        if sym.endswith(':USDT') and data.get('quoteVolume'):
            base = sym.split('/')[0].split('-')[0].split(':')[0]
            if base not in blacklist:
                all_symbols.append(sym)
                symbol_vol.append({'symbol': sym, 'volume': data['quoteVolume'], 'last': data['last'], 'pct': data.get('percentage', 0)})
    
    all_symbols = sorted(all_symbols)
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
            if macd.iloc[-2, 0] > macd.iloc[-2, 2] and c_prev_5m > df_5m['high'].iloc[-15:-2].max():
                swing_high = df_5m['high'].iloc[-3:].max()
                e_0382 = swing_high - 0.382 * (swing_high - df_5m['low'].iloc[-15:-2].min())
                sl = df_5m['low'].iloc[-15:-2].min() * 0.998
                tp = min(e_0382 + (2.5 * (e_0382 - sl)), res_level * 0.998)
                if (tp - e_0382) > ((e_0382 - sl) * 1.2):
                    coin_signals.append({'幣': sym, '方向': '🟢 做多', '進場': f"`{e_0382:.4f}` 回踩", '停損': sl, '停利': tp, '建議': "🌟 動能向上突破，等待回踩。"})
            elif macd.iloc[-2, 0] < macd.iloc[-2, 2] and c_prev_5m < df_5m['low'].iloc[-15:-2].min():
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

def analyze_single_coin_pro(sym):
    """🚀 機構級量化分析引擎：加入 ATR, RSI, ADX 與盈虧比精算"""
    exchange = ccxt.bingx({'enableRateLimit': False, 'timeout': 5000, 'options': {'defaultType': 'swap'}})
    try:
        ohlcv_1h = exchange.fetch_ohlcv(sym, '1h', limit=210)
        df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        ema200_1h = df_1h['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        
        ohlcv_5m = exchange.fetch_ohlcv(sym, '5m', limit=100)
        df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        current_price = df_5m['close'].iloc[-1]
        
        # S/R 流動性
        res, sup = get_overall_sr(df_1h, current_price)
        
        # 專業量化指標計算
        df_5m.ta.macd(fast=12, slow=26, signal=9, append=True)
        df_5m.ta.rsi(length=14, append=True)
        df_5m.ta.atr(length=14, append=True)
        df_5m.ta.adx(length=14, append=True)
        
        macd_line = df_5m['MACD_12_26_9'].iloc[-1]
        signal_line = df_5m['MACDs_12_26_9'].iloc[-1]
        rsi_val = df_5m['RSI_14'].iloc[-1]
        atr_val = df_5m['ATRr_14'].iloc[-1]
        adx_val = df_5m['ADX_14'].iloc[-1] if 'ADX_14' in df_5m.columns else 20
        
        return {
            'price': current_price,
            'trend_1h': 'BULLISH' if current_price > ema200_1h else 'BEARISH',
            'res': res, 'sup': sup,
            'macd_bullish': macd_line > signal_line,
            'rsi': rsi_val,
            'atr': atr_val,
            'adx': adx_val
        }
    except Exception as e:
        return None

# ==========================================
# 介面渲染區塊 (完美並行邏輯)
# ==========================================
all_symbols, top_50_market = fetch_market_data()

tab1, tab2 = st.tabs(["📡 前50大極速雷達", "🤖 量化機構級操盤顧問"])

with tab2:
    st.subheader("📊 專業量化健檢：客觀數據與盈虧比精算")
    ai_btn_clicked = False
    
    if all_symbols:
        st.write("輸入標的，AI 將調用 ATR, RSI, ADX 並計算真實 R:R 盈虧比。")
        col1, col2 = st.columns(2)
        with col1:
            target_coin = st.selectbox("請選擇交易標的：", all_symbols)
        with col2:
            user_intent = st.selectbox("計畫建倉方向：", ["做多 (Long) 🟢", "做空 (Short) 🔴"])
            
        ai_btn = st.button("🧠 產出專業量化評估報告")
        
        if ai_btn:
            ai_btn_clicked = True
            with st.spinner(f"⚡ 正在獲取 {target_coin} 的波動率與深度流動性數據..."):
                analysis = analyze_single_coin_pro(target_coin)
                
            if analysis:
                p = analysis['price']
                r = analysis['res']
                s = analysis['sup']
                trend = analysis['trend_1h']
                macd_up = analysis['macd_bullish']
                rsi = analysis['rsi']
                atr = analysis['atr']
                adx = analysis['adx']
                is_long = "做多" in user_intent
                
                # --- 核心風控與盈虧比 (R:R) 計算 ---
                # 專業操盤手停損法：做多停損設於現價減去 1.5 倍真實波動(ATR)；做空則加上 1.5 倍 ATR
                sl_price = p - (atr * 1.5) if is_long else p + (atr * 1.5)
                # 若整體支撐/壓力比 ATR 算出來的更近，採用結構防守
                if is_long and s > sl_price and s < p: sl_price = s * 0.998
                if not is_long and r < sl_price and r > p: sl_price = r * 1.002
                
                # 目標價：SMC 大戶流動性池 (壓力/支撐)
                tp_price = r * 0.998 if is_long else s * 1.002
                
                # 客觀空間計算 (以百分比顯示)
                risk_pct = abs(p - sl_price) / p * 100
                reward_pct = abs(tp_price - p) / p * 100
                rr_ratio = reward_pct / risk_pct if risk_pct > 0 else 0
                
                st.divider()
                st.markdown(f"### 📄 `{target_coin}` 專業量化評估報告")
                
                # 區塊 1：客觀指標數據
                st.markdown("#### 1️⃣ 客觀盤面數據 (Objective Metrics)")
                col_a, col_b, col_c, col_d = st.columns(4)
                col_a.metric("當前報價", f"{p:.4f}")
                col_b.metric("1H 大級別趨勢", "多頭順風 🟢" if trend == "BULLISH" else "空頭順風 🔴")
                
                rsi_status = "超買 (過熱)" if rsi > 70 else ("超賣 (過冷)" if rsi < 30 else "中性")
                col_c.metric("RSI (14)", f"{rsi:.1f} ({rsi_status})")
                
                adx_status = "趨勢強烈" if adx > 25 else "盤整死魚"
                col_d.metric("ADX (趨勢強度)", f"{adx:.1f} ({adx_status})")

                # 區塊 2：資金控管與點位計畫
                st.markdown("#### 2️⃣ 資金控管與盈虧精算 (Risk Management)")
                st.write(f"**目標方向**：{user_intent}")
                st.write(f"📍 **建議停損價 (SL)**：`{sl_price:.4f}` (根據 ATR 波動與結構計算，距離現價 {risk_pct:.2f}%)")
                st.write(f"📍 **建議停利價 (TP)**：`{tp_price:.4f}` (目標為 1H 大戶流動性，距離現價 {reward_pct:.2f}%)")
                
                # 針對使用者的 10U 紀律給予專業評估
                st.info(f"💼 **10 USDT 固定倉位風控試算**：\n"
                        f"若以此點位建倉 10 USDT (無槓桿)，觸發停損預計虧損約 **{10 * (risk_pct/100):.2f} USDT**；\n"
                        f"觸發停利預計獲利約 **{10 * (reward_pct/100):.2f} USDT**。")

                # 區塊 3：機構級綜合診斷
                st.markdown("#### 3️⃣ 專業操盤建議 (Professional Verdict)")
                
                score = 0
                reasons = []
                
                # 評估盈虧比 (專業操盤手底線：大於 1.5)
                if rr_ratio >= 1.5:
                    score += 2
                    reasons.append(f"✅ **盈虧比優良 (R:R = {rr_ratio:.2f})**：潛在利潤是風險的 1.5 倍以上，這是一筆在數學上值得投資的交易。")
                elif rr_ratio >= 1.0:
                    score += 1
                    reasons.append(f"⚠️ **盈虧比普通 (R:R = {rr_ratio:.2f})**：利潤與風險大致打平，在專業領域屬於次等機會，不建議重倉。")
                else:
                    reasons.append(f"❌ **盈虧比劣勢 (R:R = {rr_ratio:.2f})**：潛在獲利小於承擔風險，專業操盤手**絕對不會**執行此交易。")

                # 評估趨勢
                if (is_long and trend == 'BULLISH') or (not is_long and trend == 'BEARISH'):
                    score += 1
                    reasons.append("✅ **趨勢對齊**：交易方向與大級別 (1H) 趨勢一致，阻力最小。")
                else:
                    reasons.append("❌ **逆勢交易**：交易方向與大級別趨勢相悖，有如接落下的飛刀。")
                    
                # 評估指標
                if is_long and rsi > 70: reasons.append("❌ **RSI 過熱**：目前處於超買區，做多極易買在短期高點。")
                elif not is_long and rsi < 30: reasons.append("❌ **RSI 過冷**：目前處於超賣區，做空極易遭遇劇烈反彈。")
                else: score += 1

                # 最終判決
                if score >= 4:
                    st.success("🏆 **【強烈建議進場】**：盈虧比極佳、順應大勢且指標健康。請嚴格掛好停損，果斷執行。")
                elif score >= 2:
                    st.warning("⚖️ **【觀望或縮小部位】**：數據顯示這並非最完美的 A 級設定。若仍想進場，建議承受較小的風險。")
                else:
                    st.error("🛑 **【嚴格禁止進場】**：客觀數據顯示此筆交易在長期機率中必虧無疑。紀律就是保護本金。")

                st.markdown("---")
                st.write("**詳細指標分析：**")
                for r_text in reasons: st.write(r_text)
                
            else:
                st.error("無法取得即時數據，請稍後再試。")

# 接著處理 Tab 1 (雷達掃描)
with tab1:
    count = st_autorefresh(interval=60000, limit=None, key="auto_refresh")
    st.caption(f"🔄 網頁每 60 秒自動更新 | 當前共監控成交量前 50 大活躍幣種")
    
    if len(top_50_market) > 0:
        if ai_btn_clicked:
            st.warning("⏳ 已優先為您產出量化評估報告！雷達掃描將在背景無縫恢復。")
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
                st.info("⚪ 目前前 50 大幣種皆無合適進場訊號。安全第一，請耐心等待。")
