import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 網頁基本設定與自動刷新
# ==========================================
st.set_page_config(page_title="AI 極簡看盤系統", layout="wide")
st.title("🎯 AI 全市場動態監控系統")
st.write("系統每 60 秒自動掃描一次市場，為您尋找最佳的「方向性買賣點」與「無風險套利機會」。")

# 自動重整網頁 (每 60 秒)
count = st_autorefresh(interval=60000, limit=None, key="auto_refresh")

# ==========================================
# 新增：時間週期下拉選單
# ==========================================
col_time, _ = st.columns([1, 3]) # 切割畫面，讓選單不要太寬
with col_time:
    timeframe_label = st.selectbox(
        "⏳ 選擇 K 線時間週期",
        ["15 分鐘 (激進短線)", "1 小時 (穩健波段)", "4 小時 (大趨勢)", "日線 (長線投資)"],
        index=1 # 預設停留在 1 小時
    )

# 將中文標籤轉換為 BingX 看得懂的代碼
timeframe_map = {
    "15 分鐘 (激進短線)": "15m",
    "1 小時 (穩健波段)": "1h",
    "4 小時 (大趨勢)": "4h",
    "日線 (長線投資)": "1d"
}
selected_timeframe = timeframe_map[timeframe_label]

# ==========================================
# 核心掃描演算法 (現在會接收你選擇的時間)
# ==========================================
@st.cache_data(ttl=50) 
def scan_market_and_ta(timeframe):
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    
    try:
        tickers = exchange.fetch_tickers()
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

    all_coins = []
    symbol_vol = []
    
    for sym, data in tickers.items():
        if sym.endswith(':USDT') and data.get('quoteVolume') and data.get('percentage') is not None:
            all_coins.append({
                '幣種': sym.split(':')[0],
                '最新價格': data['last'],
                '24H 漲跌幅(%)': data['percentage'],
                '24H 成交額': data['quoteVolume']
            })
            symbol_vol.append({'symbol': sym, 'volume': data['quoteVolume']})
            
    df_all_market = pd.DataFrame(all_coins).sort_values(by='24H 漲跌幅(%)', ascending=False)
    
    # 篩選前 80 大熱門幣種
    top_80 = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:80]
    
    signals = []
    
    for item in top_80:
        sym = item['symbol']
        try:
            # 1. 判斷高額資金費率 (套利無關 K 線週期，隨時抓取)
            funding_info = exchange.fetch_funding_rate(sym)
            funding_rate = funding_info.get('fundingRate', 0)
            current_close = tickers[sym]['last']
            
            if funding_rate > 0.0005: 
                rate_pct = funding_rate * 100
                apr = rate_pct * 3 * 365 
                signals.append({
                    '幣種': sym.split(':')[0],
                    '最新價格': current_close,
                    '狀態': "🟡 建議套利 (期現對沖)",
                    'AI 判斷原因': f"💰 高額資金費率 ({rate_pct:.4f}%)，預估年化 {apr:.1f}%：多軍情緒狂熱，適合買入現貨並做空1倍合約，穩賺利息。"
                })

            # 2. 依照你選擇的時間週期抓取 K 線
            ohlcv = exchange.fetch_ohlcv(sym, timeframe, limit=50)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            if len(df) >= 35:
                df.ta.rsi(length=14, append=True)
                rsi_val = df['RSI_14'].iloc[-1]
                
                macd = df.ta.macd(fast=12, slow=26, signal=9)
                macd_line = macd.iloc[-1, 0]
                signal_line = macd.iloc[-1, 2]
                prev_macd = macd.iloc[-2, 0]
                prev_signal = macd.iloc[-2, 2]
                
                bbands = df.ta.bbands(length=20, std=2)
                lower_band = bbands.iloc[-1, 0] 
                upper_band = bbands.iloc[-1, 2] 
                
                vol_ma20 = df['volume'].rolling(20).mean().iloc[-1]
                current_vol = df['volume'].iloc[-1]
                
                action = None
                reason = None
                
                if rsi_val < 30 and current_close <= lower_band:
                    action = "🟢 建議買入 (做多)"
                    reason = f"恐慌拋售 ({timeframe_label})：RSI 嚴重超賣且觸及布林下軌，極易出現報復性反彈。"
                
                elif (macd_line > signal_line) and (prev_macd <= prev_signal) and (current_vol > vol_ma20 * 1.5):
                    action = "🟢 建議買入 (做多)"
                    reason = f"主力進場 ({timeframe_label})：MACD 剛形成黃金交叉，且伴隨資金爆量流入。"
                
                elif rsi_val > 70 and current_close >= upper_band:
                    action = "🔴 建議賣出 (做空)"
                    reason = f"多頭過熱 ({timeframe_label})：RSI 嚴重超買且突破布林上軌，隨時面臨獲利了結。"
                
                elif (macd_line < signal_line) and (prev_macd >= prev_signal):
                    action = "🔴 建議賣出 (做空)"
                    reason = f"動能衰竭 ({timeframe_label})：MACD 形成死亡交叉，趨勢可能反轉。"
                
                if action:
                    signals.append({
                        '幣種': sym.split(':')[0],
                        '最新價格': current_close,
                        '狀態': action,
                        'AI 判斷原因': reason
                    })
        except Exception:
            pass
        
        time.sleep(0.05)
        
    df_signals = pd.DataFrame(signals)
    return df_all_market, df_signals

# ==========================================
# 畫面渲染區塊
# ==========================================
st.markdown(f"*(最後更新時間：{time.strftime('%Y-%m-%d %H:%M:%S')}，系統運作中...)*")
st.markdown("---")

# 將選擇的時間週期傳入函數中
df_market, df_signals = scan_market_and_ta(selected_timeframe)

if df_market.empty:
    st.error("無法連線至交易所，請稍後再試。")
else:
    st.subheader(f"💡 AI 即時潛力幣與套利推薦 (當前基準：{timeframe_label})")
    if not df_signals.empty:
        st.dataframe(df_signals, use_container_width=True, hide_index=True)
    else:
        st.info(f"⚪ 依據【{timeframe_label}】掃描前 80 大幣種，目前無明顯買賣訊號，建議空手等待。")
        
    st.markdown("---")
    
    st.subheader("📊 BingX 全市場漲跌排行榜")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**🔥 24H 漲幅排行榜 (Top 15)**")
        df_gainers = df_market.head(15).copy()
        df_gainers['24H 漲跌幅(%)'] = df_gainers['24H 漲跌幅(%)'].apply(lambda x: f"+{x:.2f}%")
        st.dataframe(df_gainers[['幣種', '最新價格', '24H 漲跌幅(%)']], use_container_width=True, hide_index=True)
        
    with col2:
        st.markdown("**❄️ 24H 跌幅排行榜 (Top 15)**")
        df_losers = df_market.tail(15).sort_values(by='24H 漲跌幅(%)', ascending=True).copy()
        df_losers['24H 漲跌幅(%)'] = df_losers['24H 漲跌幅(%)'].apply(lambda x: f"{x:.2f}%")
        st.dataframe(df_losers[['幣種', '最新價格', '24H 漲跌幅(%)']], use_container_width=True, hide_index=True)
