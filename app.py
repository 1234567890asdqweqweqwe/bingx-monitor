import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="AI 5M 極速雷達與專屬操盤顧問", layout="centered")
st.title("🎯 AI 操盤系統 (終極山寨幣防護版)")

# ==========================================
# 共用核心演算法 & 智慧小數點
# ==========================================
def fmt_p(p):
    """智慧價格格式化：解決山寨幣小數點過多問題"""
    if pd.isna(p) or p is None: return "0"
    if p < 0.0001: return f"{p:.8f}"
    elif p < 1: return f"{p:.6f}"
    else: return f"{p:.4f}"

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
    
    # ⛔ 終極黑名單：封殺大盤、傳產、主流幣，與「黃金代幣/穩定幣」
    blacklist = [
        'GOLD', 'SILVER', 'XAU', 'XAG', 'WTI', 'BRENT', 'OIL', 'DXY', 
        'NVDA', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'COIN', 'BABA', 'MSTR',
        'SP500', 'NDX', 'DJI', 'NQ', 'US30', 'BTC', 'ETH',
        'XAUT', 'PAXG', 'USDC', 'FDUSD', 'TUSD', 'USDD', 'EURT', 'BUSD'
    ]
    
    for sym, data in tickers.items():
        vol = data.get('quoteVolume', 0)
        if sym.endswith(':USDT') and vol > 0:
            base = sym.split('/')[0].split('-')[0].split(':')[0]
            
            # 🛡️ 名稱與黑名單雙重過濾
            if base in blacklist or 'NCSK' in base or 'MSTR' in base:
                continue
            if len(base) > 8 and not base.startswith('100'):
                continue
            # 🌊 千萬級流動性硬門檻 (排除容易被插針的死水幣)
            if vol < 10000000:
                continue
                
            all_symbols.append(sym)
            symbol_vol.append({'symbol': sym, 'volume': vol, 'last': data['last'], 'pct': data.get('percentage', 0)})
    
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
                    # 🛡️ 5M 防插針限制：停損距離最少 0.5%
                    if risk > 0 and 0.005 <= (risk / c_now_5m) <= 0.02:
                        tp = min(c_now_5m + (2.5 * risk), res_level * 0.998)
                        if (tp - c_now_5m) > (risk * 1.2):
                            coin_signals.append({'幣': sym, '方向': '🟢 做多', '進場': f"`{fmt_p(range_low)}` ~ `{fmt_p(c_now_5m)}`", '停損': fmt_p(sl), '停利': fmt_p(tp), '建議': f"🛡️ 4H 假跌破，上方壓力 {fmt_p(res_level)}。"})
                elif c_prev2_5m > range_high and c_prev_5m < range_high:
                    sl = df_5m['high'].iloc[-5:-1].max()
                    risk = sl - c_now_5m
                    if risk > 0 and 0.005 <= (risk / c_now_5m) <= 0.02:
                        tp = max(c_now_5m - (2.5 * risk), sup_level * 1.002)
                        if (c_now_5m - tp) > (risk * 1.2):
                            coin_signals.append({'幣': sym, '方向': '🔴 做空', '進場': f"`{fmt_p(c_now_5m)}` ~ `{fmt_p(range_high)}`", '停損': fmt_p(sl), '停利': fmt_p(tp), '建議': f"🛡️ 4H 假突破，下方支撐 {fmt_p(sup_level)}。"})

            macd = df_5m.ta.macd(fast=12, slow=26, signal=9)
            if macd.iloc[-2, 0] > macd.iloc[-2, 2] and c_prev_5m > df_5m['high'].iloc[-15:-2].max():
                swing_high = df_5m['high'].iloc[-3:].max()
                e_0382 = swing_high - 0.382 * (swing_high - df_5m['low'].iloc[-15:-2].min())
                sl = df_5m['low'].iloc[-15:-2].min() * 0.998
                risk = e_0382 - sl
                if risk > 0 and 0.005 <= (risk / e_0382) <= 0.02:
                    tp = min(e_0382 + (2.5 * risk), res_level * 0.998)
                    if (tp - e_0382) > (risk * 1.2):
                        coin_signals.append({'幣': sym, '方向': '🟢 做多', '進場': f"`{fmt_p(e_0382)}` 回踩", '停損': fmt_p(sl), '停利': fmt_p(tp), '建議': "🌟 5M 動能突破，等待回踩。"})
            elif macd.iloc[-2, 0] < macd.iloc[-2, 2] and c_prev_5m < df_5m['low'].iloc[-15:-2].min():
                swing_low = df_5m['low'].iloc[-3:].min()
                e_0382 = swing_low + 0.382 * (df_5m['high'].iloc[-15:-2].max() - swing_low)
                sl = df_5m['high'].iloc[-15:-2].max() * 1.002
                risk = sl - e_0382
                if risk > 0 and 0.005 <= (risk / e_0382) <= 0.02:
                    tp = max(e_0382 - (2.5 * risk), sup_level * 1.002)
                    if (e_0382 - tp) > (risk * 1.2):
                        coin_signals.append({'幣': sym, '方向': '🔴 做空', '進場': f"`{fmt_p(e_0382)}` 反彈", '停損': fmt_p(sl), '停利': fmt_p(tp), '建議': "🌟 5M 動能破底，等待反彈。"})
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
        ema200_5m = df_5m['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        
        res_1h, sup_1h = get_overall_sr(df_1h, current_price)
        res_5m = df_5m['high'].iloc[-20:-1].max()
        sup_5m = df_5m['low'].iloc[-20:-1].min()
        
        macd = df_5m.ta.macd(fast=12, slow=26, signal=9)
        macd_line = macd.iloc[-1, 0]
        signal_line = macd.iloc[-1, 2]
        df_5m.ta.adx(length=14, append=True)
        adx_val = df_5m['ADX_14'].iloc[-1] if 'ADX_14' in df_5m.columns else 0
        
        return {
            'price': current_price,
            'trend_1h': 'BULLISH' if current_price > ema200_1h else 'BEARISH',
            'res_1h': res_1h, 'sup_1h': sup_1h,
            'trend_5m': 'BULLISH' if current_price > ema200_5m else 'BEARISH',
            'res_5m': res_5m, 'sup_5m': sup_5m,
            'macd_bullish': macd_line > signal_line,
            'adx': adx_val
        }
    except:
        return None

# ==========================================
# 介面渲染區塊
# ==========================================
all_symbols, top_50_market = fetch_market_data()

tab1, tab2 = st.tabs(["📡 前50大極速雷達", "🤖 AI 專屬操盤顧問"])

with tab2:
    st.subheader("🤖 問問 AI：雙重時間框架深度解析")
    ai_btn_clicked = False
    
    if all_symbols:
        st.write("結合 1H 大戶防線與 5M 短線動能，SMC 專家為你即時健檢。")
        col1, col2 = st.columns(2)
        with col1:
            target_coin = st.selectbox("你想操作哪個幣？(可輸入搜尋)", all_symbols)
        with col2:
            user_intent = st.selectbox("你的計畫是？", ["我想做多 (Long) 🟢", "我想做空 (Short) 🔴"])
            
        ai_btn = st.button("🧠 產出 SMC 專家報告")
        
        if ai_btn:
            ai_btn_clicked = True 
            with st.spinner(f"⚡ AI 顧問啟動！正在為您即時解析 {target_coin} 的 1H 與 5M 結構..."):
                analysis = analyze_single_coin(target_coin)
                
            if analysis:
                st.divider()
                p = analysis['price']
                r_1h, s_1h = analysis['res_1h'], analysis['sup_1h']
                r_5m, s_5m = analysis['res_5m'], analysis['sup_5m']
                t_1h, t_5m = analysis['trend_1h'], analysis['trend_5m']
                macd_up, adx = analysis['macd_bullish'], analysis['adx']
                
                is_long = "做多" in user_intent
                room_up_1h = ((r_1h - p) / p) * 100
                room_down_1h = ((p - s_1h) / p) * 100
                
                score = 0
                st.markdown(f"### 🪙 {target_coin} | 當前價格: `{fmt_p(p)}`")
                
                st.markdown("#### 📊 【宏觀 1H：大戶流動性與防線】")
                st.write(f"在 SMC 邏輯中，1 小時線代表華爾街大戶的真實防守位置。")
                st.write(f"- 📈 **1H 趨勢**：{'🟢 多頭順風' if t_1h == 'BULLISH' else '🔴 空頭弱勢'}")
                st.write(f"- 🛡️ **上方大戶壓力位 (Supply)**：`{fmt_p(r_1h)}` (距離 {room_up_1h:.2f}%)")
                st.write(f"- 🛡️ **下方大戶支撐位 (Demand)**：`{fmt_p(s_1h)}` (距離 {room_down_1h:.2f}%)")
                
                if is_long:
                    if t_1h == 'BULLISH': score += 2
                    if room_up_1h > 2.0: score += 2
                else:
                    if t_1h == 'BEARISH': score += 2
                    if room_down_1h > 2.0: score += 2

                st.markdown("#### ⚡ 【微觀 5M：短線趨勢與散戶動能】")
                st.write(f"Data Trader 強調：進場前必須確認短線沒有牆壁擋路，且動能必須支持你的方向。")
                st.write(f"- 📈 **5M 趨勢**：{'🟢 短線強勢' if t_5m == 'BULLISH' else '🔴 短線偏弱'}")
                st.write(f"- 🧱 **短線近距離壓力**：`{fmt_p(r_5m)}`")
                st.write(f"- 🧱 **短線近距離支撐**：`{fmt_p(s_5m)}`")
                st.write(f"- 🌪️ **短線 MACD 動能**：{'🟢 向上爆發中' if macd_up else '🔴 向下摜壓中'}")
                
                if is_long and t_5m == 'BULLISH' and macd_up: score += 2
                if not is_long and t_5m == 'BEARISH' and not macd_up: score += 2

                st.markdown("---")
                if score >= 5:
                    st.success(f"### 🏆 SMC 綜合判定：完美共振 (極高勝率)")
                    st.write("✅ **AI 戰術建議**：這是一張 1H 與 5M 完全順風的黃金單！上方沒有大戶壓力擋道，短線動能也完美配合。")
                elif score >= 3:
                    st.warning(f"### ⚖️ SMC 綜合判定：空間受限或趨勢衝突 (需謹慎)")
                    st.write("⚠️ **AI 戰術建議**：1H 與 5M 方向可能衝突，或距離壓力位太近。主力極可能進行假突破洗盤，建議耐心等待。")
                else:
                    st.error(f"### 🛑 SMC 綜合判定：絞肉機行情 (嚴格禁止進場)")
                    st.write("❌ **AI 戰術建議**：完全逆勢！正前方就是大戶流動性牆壁。管好你的手，放棄這張單。")

                st.info("💡 **風控官叮嚀**：無論分數多高，單筆保證金請嚴格設定為 **10 USDT**！配合 10x~20x 槓桿控制風險。")
            else:
                st.error("無法取得即時數據，請稍後再試。")

with tab1:
    count = st_autorefresh(interval=60000, limit=None, key="auto_refresh")
    st.caption(f"🔄 網頁每 60 秒自動更新 | 當前共監控成交量前 50 大強勢山寨幣")
    
    if len(top_50_market) > 0:
        if ai_btn_clicked:
            st.warning("⏳ 已優先解析 AI 顧問，雷達將暫停一回合以確保順暢體驗，下一分鐘將自動恢復全域掃描！")
        else:
            with st.spinner('📡 雷達正在背景啟動【多執行緒】高速運算中...'):
                signals = run_radar_scan_multithread(top_50_market)
                
            if len(signals) > 0:
                st.subheader(f"💡 發現 {len(signals)} 個 AI 推薦進場機會")
                for sig in signals:
                    card = st.success if "多" in sig['方向'] else st.error
                    card(f"**{sig['幣']}** | {sig['方向']}\n\n"
                         f"🎯 **推薦進場**：{sig['進場']}\n\n"
                         f"🛑 **停損**：`{sig['停損']}` | 💰 **停利**：`{sig['停利']}`\n\n"
                         f"💡 {sig['建議']}")
            else:
                st.info("⚪ 目前前 50 大強勢山寨幣皆無合適進場訊號。安全第一，請耐心等待。")
