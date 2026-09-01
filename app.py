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
st.write("系統每 60 秒自動掃描一次市場，為您尋找最佳的進出場時機。")

# 設定每 60000 毫秒 (60秒) 自動重整網頁，免手動點擊
count = st_autorefresh(interval=60000, limit=None, key="auto_refresh")

# ==========================================
# 核心掃描演算法
# ==========================================
@st.cache_data(ttl=50) # 快取 50 秒，配合 60 秒刷新
def scan_market_and_ta():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    
    try:
        # 1. 抓取全市場即時行情
        tickers = exchange.fetch_tickers()
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame()

    all_coins = []
    symbol_vol = []
    
    # 整理全市場清單
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
    
    # 2. 篩選前 80 大熱門幣種進行深度技術分析 (避免被交易所封鎖 API)
    top_80 = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:80]
    
    signals = []
    
    for item in top_80:
        sym = item['symbol']
        try:
            # 抓取 1 小時 K 線
            ohlcv = exchange.fetch_ohlcv(sym, '1h', limit=50)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            if len(df) >= 35:
                # 計算 RSI (14)
                df.ta.rsi(length=14, append=True)
                rsi_val = df['RSI_14'].iloc[-1]
                
                # 計算 MACD
                macd = df.ta.macd(fast=12, slow=26, signal=9)
                macd_line = macd.iloc[-1, 0]
                signal_line = macd.iloc[-1, 2]
                prev_macd = macd.iloc[-2, 0]
                prev_signal = macd.iloc[-2, 2]
                
                # 計算 布林通道 (Bollinger Bands)
                bbands = df.ta.bbands(length=20, std=2)
                lower_band = bbands.iloc[-1, 0] # BBL
                upper_band = bbands.iloc[-1, 2] # BBU
                
                # 計算成交量均線
                vol_ma20 = df['volume'].rolling(20).mean().iloc[-1]
                current_vol = df['volume'].iloc[-1]
                current_close = df['close'].iloc[-1]
                
                # ---- 判斷買入/賣出訊號與原因 ----
                action = None
                reason = None
                
                # 【買入條件 1】底層反彈：RSI 超賣 + 價格跌破布林下軌
                if rsi_val < 30 and current_close <= lower_band:
                    action = "🟢 建議買入 (做多)"
                    reason = "恐慌拋售已達極值：RSI 嚴重超賣且觸及布林下軌，極易出現報復性反彈。"
                
                # 【買入條件 2】動能爆發：MACD 黃金交叉 + 成交量放大
                elif (macd_line > signal_line) and (prev_macd <= prev_signal) and (current_vol > vol_ma20 * 1.5):
                    action = "🟢 建議買入 (做多)"
                    reason = "主力資金進場：MACD 剛形成黃金交叉，且伴隨資金爆量流入，上漲動能強勁。"
                
                # 【賣出條件 1】短線過熱：RSI 超買 + 價格突破布林上軌
                elif rsi_val > 70 and current_close >= upper_band:
                    action = "🔴 建議賣出 (做空)"
                    reason = "多頭情緒過熱：RSI 嚴重超買且突破布林上軌，隨時面臨獲利了結賣壓。"
                
                # 【賣出條件 2】動能衰竭：MACD 死亡交叉
                elif (macd_line < signal_line) and (prev_macd >= prev_signal):
                    action = "🔴 建議賣出 (做空)"
                    reason = "上漲動能衰竭：MACD 形成死亡交叉，趨勢可能面臨反轉向下。"
                
                if action:
                    signals.append({
                        '幣種': sym.split(':')[0],
                        '最新價格': current_close,
                        '狀態': action,
                        'AI 判斷原因 (技術分析)': reason
                    })
        except Exception:
            pass
        
        # 微小延遲保護 API
        time.sleep(0.05)
        
    df_signals = pd.DataFrame(signals)
    return df_all_market, df_signals

# ==========================================
# 畫面渲染區塊
# ==========================================
st.markdown(f"*(最後更新時間：{time.strftime('%Y-%m-%d %H:%M:%S')}，系統運作中...)*")
st.markdown("---")

df_market, df_signals = scan_market_and_ta()

if df_market.empty:
    st.error("無法連線至交易所，請稍後再試。")
else:
    # 區塊 1：AI 主動推薦清單
    st.subheader("💡 AI 即時潛力幣推薦 (依據 MACD、RSI、布林通道)")
    if not df_signals.empty:
        # 將 DataFrame 顯示優化，隱藏左側數字索引
        st.dataframe(df_signals, use_container_width=True, hide_index=True)
    else:
        st.info("⚪ 目前市場前 80 大熱門幣種中，無明顯的極端買賣訊號，建議耐心空手等待。")
        
    st.markdown("---")
    
    # 區塊 2：全市場漲跌榜 (左邊漲幅榜，右邊跌幅榜)
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
