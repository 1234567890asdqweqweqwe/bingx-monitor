import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="AI 1H 狙擊雷達與專屬操盤顧問", layout="centered")
st.title("🎯 AI 操盤系統 (1H 狙擊手級)")

# ==========================================
# 共用核心演算法 & 智慧小數點
# ==========================================
def fmt_p(p):
    if pd.isna(p) or p is None: return "0"
    if p < 0.0001: return f"{p:.8f}"
    elif p < 1: return f"{p:.6f}"
    else: return f"{p:.4f}"

@st.cache_data(ttl=60, show_spinner=False)
def fetch_market_data():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    try: tickers = exchange.fetch_tickers()
    except: return [], []
    
    all_symbols, symbol_vol = [], []
    # ⛔ 終極黑名單 (包含黃金與穩定幣)
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
            if base in blacklist or 'NCSK' in base or 'MSTR' in base: continue
            if len(base) > 8 and not base.startswith('100'): continue
            if vol < 10000000: continue # 🌊 千萬級流動性硬門檻
            
            all_symbols.append(sym)
            symbol_vol.append({'symbol': sym, 'volume': vol, 'last': data['last']})
            
    return sorted(all_symbols), sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:50]

@st.cache_data(ttl=60, show_spinner=False)
def run_radar_scan_multithread(top_50_market):
    signals = []
    def process_coin(item):
        sym = item['symbol']
        exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
        coin_signals = []
        try:
            ohlcv_1h = exchange.fetch_ohlcv(sym, '1h', limit=150)
            df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            df_1h.ta.macd(fast=12, slow=26, signal=9, append=True)
            df_1h.ta.adx(length=14, append=True)
            df_1h['ema200'] = df_1h['close'].ewm(span=200, adjust=False).mean()
            df_1h['ema50'] = df_1h['close'].ewm(span=50, adjust=False).mean()
            
            c_now = df_1h['close'].iloc[-1]
            macd_line = df_1h['MACD_12_26_9'].iloc[-2]
            signal_line = df_1h['MACDs_12_26_9'].iloc[-2]
            adx_val = df_1h['ADX_14'].iloc[-2]
            
            trend_up = c_now > df_1h['ema200'].iloc[-1] and df_1h['ema50'].iloc[-1] > df_1h['ema200'].iloc[-1]
            trend_down = c_now < df_1h['ema200'].iloc[-1] and df_1h['ema50'].iloc[-1] < df_1h['ema200'].iloc[-1]
            
            bos_bull = df_1h['close'].iloc[-2] > df_1h['high'].iloc[-11:-3].max()
            bos_bear = df_1h['close'].iloc[-2] < df_1h['low'].iloc[-11:-3].min()
            
            if adx_val > 25: # 嚴格動能濾網
                if macd_line > signal_line and bos_bull and trend_up:
                    sl = df_1h['low'].iloc[-6:-2].min() * 0.995
                    risk = c_now - sl
                    if risk > 0 and 0.01 <= (risk / c_now) <= 0.05: # 1% ~ 5% 停損防護
                        tp1 = c_now + risk
                        tp2 = c_now + (2.0 * risk)
                        coin_signals.append({'幣': sym, '方向': '🟢 1H 做多', '進場': fmt_p(c_now), '停損': fmt_p(sl), '停利1R': fmt_p(tp1), '停利2R': fmt_p(tp2), '建議': "🌟 1H 大級別動能突破 (勝率極高)"})
                        
                elif macd_line < signal_line and bos_bear and trend_down:
                    sl = df_1h['high'].iloc[-6:-2].max() * 1.005
                    risk = sl - c_now
                    if risk > 0 and 0.01 <= (risk / c_now) <= 0.05:
                        tp1 = c_now - risk
                        tp2 = c_now - (2.0 * risk)
                        coin_signals.append({'幣': sym, '方向': '🔴 1H 做空', '進場': fmt_p(c_now), '停損': fmt_p(sl), '停利1R': fmt_p(tp1), '停利2R': fmt_p(tp2), '建議': "🌟 1H 大級別動能跌破 (勝率極高)"})
            return coin_signals
        except: return []

    with ThreadPoolExecutor(max_workers=5) as executor:
        for future in as_completed([executor.submit(process_coin, item) for item in top_50_market]):
            result = future.result()
            if result: signals.extend(result)
    return signals

def analyze_single_coin(sym):
    exchange = ccxt.bingx({'enableRateLimit': False, 'timeout': 5000, 'options': {'defaultType': 'swap'}})
    try:
        ohlcv_1h = exchange.fetch_ohlcv(sym, '1h', limit=150)
        df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        c_now = df_1h['close'].iloc[-1]
        df_1h['ema200'] = df_1h['close'].ewm(span=200, adjust=False).mean()
        df_1h['ema50'] = df_1h['close'].ewm(span=50, adjust=False).mean()
        df_1h.ta.macd(fast=12, slow=26, signal=9, append=True)
        df_1h.ta.adx(length=14, append=True)
        
        return {
            'price': c_now,
            'ema200': df_1h['ema200'].iloc[-1], 'ema50': df_1h['ema50'].iloc[-1],
            'macd_bullish': df_1h['MACD_12_26_9'].iloc[-1] > df_1h['MACDs_12_26_9'].iloc[-1],
            'adx': df_1h['ADX_14'].iloc[-1]
        }
    except: return None

# ==========================================
# 介面渲染區塊
# ==========================================
all_symbols, top_50_market = fetch_market_data()
tab1, tab2 = st.tabs(["📡 1H 狙擊雷達", "🤖 AI 專屬操盤顧問"])

with tab2:
    st.subheader("🤖 問問 AI：1H 大級別動能解析")
    ai_btn_clicked = False
    
    if all_symbols:
        col1, col2 = st.columns(2)
        with col1: target_coin = st.selectbox("你想操作哪個幣？", all_symbols)
        with col2: user_intent = st.selectbox("計畫？", ["做多 (Long) 🟢", "做空 (Short) 🔴"])
            
        if st.button("🧠 產出 SMC 專家報告"):
            ai_btn_clicked = True 
            with st.spinner(f"⚡ 解析 {target_coin} 1H 結構中..."):
                analysis = analyze_single_coin(target_coin)
                
            if analysis:
                st.divider()
                p = analysis['price']
                trend_up = p > analysis['ema200'] and analysis['ema50'] > analysis['ema200']
                trend_down = p < analysis['ema200'] and analysis['ema50'] < analysis['ema200']
                is_long = "做多" in user_intent
                score = 0
                
                st.markdown(f"### 🪙 {target_coin} | 當前價格: `{fmt_p(p)}`")
                st.write(f"- 📈 **雙均線趨勢**：{'🟢 大順風 (多)' if trend_up else '🔴 大順風 (空)' if trend_down else '⚪ 盤整震盪中'}")
                st.write(f"- 🌪️ **ADX 動能 (需>25)**：`{analysis['adx']:.2f}`")
                st.write(f"- 📊 **MACD 狀態**：{'🟢 多頭' if analysis['macd_bullish'] else '🔴 空頭'}")
                
                if is_long and trend_up: score += 2
                if not is_long and trend_down: score += 2
                if analysis['adx'] > 25: score += 2
                if (is_long and analysis['macd_bullish']) or (not is_long and not analysis['macd_bullish']): score += 1

                st.markdown("---")
                if score >= 5: st.success("### 🏆 SMC 判定：完美共振 (極高勝率)\n大級別趨勢與強動能完全配合，請果斷分批進場！")
                elif score >= 3: st.warning("### ⚖️ SMC 判定：動能不足或趨勢衝突\n目前為盤整洗盤期，不符合狙擊手標準，建議觀望。")
                else: st.error("### 🛑 SMC 判定：完全逆勢\n方向錯誤或陷入死水，嚴格禁止進場。")
            else: st.error("取得數據失敗。")

with tab1:
    st_autorefresh(interval=60000, key="auto_refresh")
    if top_50_market and not ai_btn_clicked:
        with st.spinner('📡 1H 狙擊雷達掃描中...'):
            signals = run_radar_scan_multithread(top_50_market)
            if signals:
                st.subheader(f"💡 發現 {len(signals)} 個 S 級機會")
                for sig in signals:
                    card = st.success if "多" in sig['方向'] else st.error
                    card(f"**{sig['幣']}** | {sig['方向']}\n\n🎯 **進場**：`{sig['進場']}`\n\n🛑 **停損**：`{sig['停損']}`\n\n💰 **保守 (1R)**：`{sig['停利1R']}` | 💰 **標準 (2R)**：`{sig['停利2R']}`")
            else: st.info("⚪ 目前無 1H 級別極端訊號。狙擊手請耐心等待。")
