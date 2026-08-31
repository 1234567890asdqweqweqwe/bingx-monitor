import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
import time

# ==========================================
# 網頁基本設定
# ==========================================
st.set_page_config(page_title="BingX 交易監控面板", layout="wide")
st.title("🚀 BingX 新手專屬監控儀表板")

# ==========================================
# 定義板塊與代表幣種字典
# ==========================================
SECTORS = {
    "🐶 迷因幣 (Meme)": ["DOGE", "SHIB", "PEPE", "WIF", "BOME", "FLOKI", "BONK"],
    "🤖 人工智慧 (AI)": ["FET", "RNDR", "WLD", "TAO", "AR", "NEAR", "GRT"],
    "🚀 公鏈 (Layer 1)": ["BTC", "ETH", "SOL", "AVAX", "SUI", "APT", "SEI"],
    "🎮 遊戲 (GameFi)": ["GALA", "PIXEL", "IMX", "RON", "YGG", "BIGTIME"],
    "🏦 去中心化金融 (DeFi)": ["UNI", "LINK", "AAVE", "MKR", "CRV", "RUNE"]
}

# ==========================================
# 側邊欄設定
# ==========================================
st.sidebar.header("設定參數")
symbol = st.sidebar.selectbox("選擇交易對", ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"])
timeframe = st.sidebar.selectbox("選擇 K 線週期", ["15m", "1h", "4h", "1d"], index=2)
refresh_btn = st.sidebar.button("🔄 立即刷新數據")

# ==========================================
# 資料抓取函數 (設定快取)
# ==========================================
@st.cache_data(ttl=60)
def get_market_data(symbol, timeframe):
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    ticker = exchange.fetch_ticker(symbol)
    funding_info = exchange.fetch_funding_rate(symbol)
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms') + pd.Timedelta(hours=8)
    
    # 計算指標
    df.ta.ema(length=20, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.rsi(length=14, append=True)
    df['Vol_MA20'] = df['volume'].rolling(window=20).mean()
    df['Volume_Spike'] = df['volume'] > (df['Vol_MA20'] * 2)
    return df, ticker, funding_info

@st.cache_data(ttl=60)
def get_sector_data():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    tickers = exchange.fetch_tickers()
    sector_stats = []
    
    for sector_name, coins in SECTORS.items():
        total_volume = 0
        total_change = 0
        valid_count = 0
        for coin in coins:
            sym = f"{coin}/USDT:USDT"
            if sym in tickers:
                data = tickers[sym]
                if data.get('quoteVolume') and data.get('percentage') is not None:
                    total_volume += data['quoteVolume']
                    total_change += data['percentage']
                    valid_count += 1
                    
        if valid_count > 0:
            sector_stats.append({
                'Sector': sector_name,
                'Volume': total_volume,
                'Avg_Change': total_change / valid_count
            })
            
    df_sector = pd.DataFrame(sector_stats).sort_values(by='Avg_Change', ascending=True)
    return df_sector

# ==========================================
# 主畫面渲染
# ==========================================
try:
    with st.spinner('正在從 BingX 讀取最新行情...'):
        df, ticker, funding_info = get_market_data(symbol, timeframe)
    
    latest = df.iloc[-1]
    
    # --- 區塊一：核心數據看板 ---
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("最新價格 (USDT)", f"{ticker.get('last'):,}")
    col2.metric("24H 漲跌幅", f"{ticker.get('percentage'):.2f}%")
    f_rate = funding_info.get('fundingRate', 0) * 100
    col3.metric("當前資金費率", f"{f_rate:.4f}%")
    col4.metric("即時 RSI (14)", f"{latest['RSI_14']:.2f}")

    st.markdown("---")
    
    # --- 區塊二：板塊資金流向圖表 ---
    st.subheader("🌍 當前市場板塊熱度與資金流向")
    try:
        df_sector = get_sector_data()
        df_sector['Volume_M'] = df_sector['Volume'] / 1_000_000 
        col_bar, col_scatter = st.columns(2)
        
        # 左邊長條圖
        with col_bar:
            colors = ['#00cc96' if val >= 0 else '#ef553b' for val in df_sector['Avg_Change']]
            fig_sector = go.Figure(go.Bar(
                x=df_sector['Avg_Change'], y=df_sector['Sector'],
                orientation='h', marker_color=colors,
                text=[f"{val:.2f}%" for val in df_sector['Avg_Change']], textposition='auto'
            ))
            fig_sector.update_layout(title="📊 板塊平均漲跌幅", height=400, margin=dict(l=0, r=0, t=40, b=0), xaxis_title="平均漲跌幅 (%)")
            st.plotly_chart(fig_sector, use_container_width=True)

        # 右邊氣泡圖
        with col_scatter:
            fig_scatter = px.scatter(
                df_sector, x='Avg_Change', y='Volume_M', text='Sector', size='Volume_M',
                color='Avg_Change', color_continuous_scale=['#ef553b', '#cccccc', '#00cc96'],
                color_continuous_midpoint=0, labels={'Avg_Change': '平均漲跌幅 (%)', 'Volume_M': '成交資金 (百萬 USDT)'}
            )
            fig_scatter.update_layout(title="🎈 板塊資金量 vs 漲跌幅", height=400, margin=dict(l=0, r=0, t=40, b=0), coloraxis_showscale=False)
            fig_scatter.update_traces(textposition='top center')
            st.plotly_chart(fig_scatter, use_container_width=True)
            
    except Exception as e:
        st.warning(f"板塊資料讀取中... {e}")

    st.markdown("---")

    # --- 區塊三：策略訊號指示燈 ---
    st.subheader("💡 當前策略訊號判斷")
    s_col1, s_col2, s_col3 = st.columns(3)
    
    with s_col1:
        if latest['RSI_14'] < 30: st.success("🟢 RSI 處於超賣區 (跌深可能反彈)")
        elif latest['RSI_14'] > 70: st.error("🔴 RSI 處於超買區 (短線過熱注意)")
        else: st.info("⚪ RSI 處於中性區間")
        
    with s_col2:
        if latest['EMA_20'] > latest['EMA_50']: st.success("🟢 均線多頭排列 (短線強勢)")
        else: st.error("🔴 均線空頭排列 (短線弱勢)")
        
    with s_col3:
        if latest['Volume_Spike']:
            if latest['close'] > latest['open']: st.warning("🔥 出現爆量上漲！(買盤積極介入)")
            else: st.error("⚠️ 出現爆量下跌！(賣盤大舉倒貨)")
        else: st.info("⚪ 正常成交量")

    st.markdown("---")

    # --- 區塊四：互動式 K 線圖 ---
    st.subheader("📈 互動式行情圖表")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])

    fig.add_trace(go.Candlestick(x=df['datetime'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name="K線"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['datetime'], y=df['EMA_20'], line=dict(color='orange', width=2), name="EMA 20"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['datetime'], y=df['EMA_50'], line=dict(color='blue', width=2), name="EMA 50"), row=1, col=1)

    colors_vol = ['green' if row['close'] >= row['open'] else 'red' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(x=df['datetime'], y=df['volume'], marker_color=colors_vol, name="成交量"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['datetime'], y=df['Vol_MA20'], line=dict(color='purple', width=2), name="20均量"), row=2, col=1)

    fig.update_layout(xaxis_rangeslider_visible=False, height=600, margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # --- 區塊五：全市場掃描 ---
    st.subheader("🔍 全市場超賣潛力幣種掃描 (Top 20 主流幣)")
    st.caption("自動掃描當前成交量前 20 大的合約幣種，尋找 RSI < 30 的超賣機會。")

    if st.button("🚀 啟動掃描 (約需 10~15 秒)"):
        scan_exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
        tickers = scan_exchange.fetch_tickers()
        symbol_vol = []
        
        for sym, data in tickers.items():
            if ':' in sym and 'quoteVolume' in data and data['quoteVolume'] is not None:
                symbol_vol.append({'symbol': sym, 'volume': data['quoteVolume']})
                
        top_20_symbols = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:20]
        results = []
        progress_bar = st.progress(0, text="準備掃描...")
        
        for i, item in enumerate(top_20_symbols):
            sym = item['symbol']
            progress_bar.progress((i + 1) / 20, text=f"正在掃描 {sym} ({i+1}/20)...")
            
            try:
                ohlcv = scan_exchange.fetch_ohlcv(sym, timeframe, limit=30)
                scan_df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                if len(scan_df) >= 15:
                    scan_df.ta.rsi(length=14, append=True)
                    latest_rsi = scan_df['RSI_14'].iloc[-1]
                    latest_close = scan_df['close'].iloc[-1]
                    
                    if latest_rsi < 30:
                        results.append({
                            '幣種': sym.split(':')[0],
                            '最新價格 (USDT)': latest_close,
                            'RSI (14)': round(latest_rsi, 2),
                            '24H 成交額 (USDT)': f"{item['volume']:,.0f}"
                        })
            except Exception as e:
                continue
                
            time.sleep(0.1) 
            
        progress_bar.empty()
        
        if len(results) > 0:
            st.success(f"掃描完成！在 Top 20 主流幣中，共發現 {len(results)} 個超賣標的：")
            st.dataframe(pd.DataFrame(results), use_container_width=True)
        else:
            st.info("掃描完成！目前市場情緒正常，前 20 大主流幣中沒有發現 RSI < 30 的標的。")

except Exception as e:
    st.error(f"讀取資料時發生錯誤：{e}")