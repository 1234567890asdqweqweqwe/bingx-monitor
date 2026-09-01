import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 網頁基本設定 (改回置中排列，更像手機 APP)
# ==========================================
st.set_page_config(page_title="AI 極簡看盤系統", layout="centered")
st.title("🎯 AI 全市場動態監控")
st.write("每 60 秒自動掃描，為您尋找最佳買賣點與套利機會。")

count = st_autorefresh(interval=60000, limit=None, key="auto_refresh")

# ==========================================
# 時間週期下拉選單 (滿版顯示，方便手指點擊)
# ==========================================
timeframe_label = st.selectbox(
    "⏳ 選擇 K 線時間週期",
    ["15 分鐘 (激進短線)", "1 小時 (穩健波段)", "4 小時 (大趨勢)", "日線 (長線投資)"],
    index=1
)

timeframe_map = {
    "15 分鐘 (激進短線)": "15m",
    "1 小時 (穩健波段)": "1h",
    "4 小時 (大趨勢)": "4h",
    "日線 (長線投資)": "1d"
}
selected_timeframe = timeframe_map[timeframe_label]

# ==========================================
# 核心掃描演算法
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
                '24H漲跌(%)': data['percentage'],
                '24H 成交額': data['quoteVolume']
            })
            symbol_vol.append({'symbol': sym, 'volume': data['quoteVolume']})
            
    df_all_market = pd.DataFrame(all_coins).sort_values(by='24H漲跌(%)', ascending=False)
    
    top_80 = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:80]
    signals = []
    
    for item in top_80:
        sym = item['symbol']
        try:
            # 1. 判斷高額資金費率
            funding_info = exchange.fetch_funding_rate(sym)
            funding_rate = funding_info.get('fundingRate', 0)
            current_close = tickers[sym]['last']
            
            if funding_rate > 0.0005: 
                rate_pct = funding_rate * 100
                apr = rate_pct * 3 * 365 
                signals.append({
                    '幣種': sym.split(':')[0],
                    '最新價格': current_close,
                    'type': 'arbitrage',
                    '狀態': "🟡 建議套利 (期現對沖)",
                    'AI 判斷原因': f"高額資金費率 ({rate_pct:.4f}%)，預估年化 {apr:.1f}%：多軍情緒狂熱，適合買現貨+空合約。"
                })

            # 2. 技術分析
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
                sig_type = None
                
                if rsi_val < 30 and current_close <= lower_band:
                    sig_type = "buy"
                    action = "🟢 建議買入 (做多)"
                    reason = f"恐慌拋售 ({timeframe_label})：RSI 超賣且觸及布林下軌，極易反彈。"
                
                elif (macd_line > signal_line) and (prev_macd <= prev_signal) and (current_vol > vol_ma20 * 1.5):
                    sig_type = "buy"
                    action = "🟢 建議買入 (做多)"
                    reason = f"主力進場 ({timeframe_label})：MACD 黃金交叉，且伴隨資金爆量流入。"
                
                elif rsi_val > 70 and current_close >= upper_band:
                    sig_type = "sell"
                    action = "🔴 建議賣出 (做空)"
                    reason = f"多頭過熱 ({timeframe_label})：RSI 超買且突破布林上軌，面臨獲利了結。"
                
                elif (macd_line < signal_line) and (prev_macd >= prev_signal):
                    sig_type = "sell"
                    action = "🔴 建議賣出 (做空)"
                    reason = f"動能衰竭 ({timeframe_label})：MACD 死亡交叉，趨勢可能反轉向下。"
                
                if action:
                    signals.append({
                        '幣種': sym.split(':')[0],
                        '最新價格': current_close,
                        'type': sig_type,
                        '狀態': action,
                        'AI 判斷原因': reason
                    })
        except Exception:
            pass
        
        time.sleep(0.05)
        
    df_signals = pd.DataFrame(signals)
    return df_all_market, df_signals

# ==========================================
# 畫面渲染區塊 (專為手機優化)
# ==========================================
st.caption(f"🔄 最後更新：{time.strftime('%Y-%m-%d %H:%M:%S')}")
st.divider()

df_market, df_signals = scan_market_and_ta(selected_timeframe)

if df_market.empty:
    st.error("連線異常，請稍後再試。")
else:
    # 區塊 1：AI 推薦改用「手機卡片」顯示，拒絕左右滑動
    st.subheader(f"💡 AI 潛力幣與套利推薦")
    
    if not df_signals.empty:
        for idx, row in df_signals.iterrows():
            # 使用 markdown 組裝成漂亮的卡片文字
            card_text = f"**{row['幣種']}** | 價格: `{row['最新價格']}`\n\n**{row['狀態']}**\n\n📝 {row['AI 判斷原因']}"
            
            # 依照訊號類型給予不同的背景顏色
            if row['type'] == 'buy':
                st.success(card_text)
            elif row['type'] == 'sell':
                st.error(card_text)
            else:
                st.warning(card_text)
    else:
        st.info(f"⚪ 目前【{timeframe_label}】無極端買賣訊號，建議空手等待。")
        
    st.divider()
    
    # 區塊 2：漲跌榜改用「分頁 (Tabs)」顯示，縮短上下滑動距離
    st.subheader("📊 24H 漲跌排行榜 (Top 10)")
    tab1, tab2 = st.tabs(["🔥 漲幅榜", "❄️ 跌幅榜"])
    
    with tab1:
        df_gainers = df_market.head(10).copy()
        df_gainers['24H漲跌(%)'] = df_gainers['24H漲跌(%)'].apply(lambda x: f"+{x:.2f}%")
        # 移除不需要的成交額，讓手機畫面更乾淨
        st.dataframe(df_gainers[['幣種', '最新價格', '24H漲跌(%)']], use_container_width=True, hide_index=True)
        
    with tab2:
        df_losers = df_market.tail(10).sort_values(by='24H漲跌(%)', ascending=True).copy()
        df_losers['24H漲跌(%)'] = df_losers['24H漲跌(%)'].apply(lambda x: f"{x:.2f}%")
        st.dataframe(df_losers[['幣種', '最新價格', '24H漲跌(%)']], use_container_width=True, hide_index=True)
