import streamlit as st
import ccxt
import pandas as pd
import pandas_ta as ta
import time
from datetime import datetime, timezone
from streamlit_autorefresh import st_autorefresh

# ==========================================
# 網頁基本設定
# ==========================================
st.set_page_config(page_title="AI 狙擊手儀表板", layout="centered")
st.title("🎯 Data Trader 雙核心監控 (純幣圈)")
st.write("每 60 秒自動掃描全市場，尋找「4H 假突破」與「0.618 黃金回撤」機會。")

# 設定每 60 秒網頁自動更新一次
count = st_autorefresh(interval=60000, limit=None, key="auto_refresh")

# ==========================================
# 核心掃描演算法 (與 Telegram 機器人邏輯同步)
# ==========================================
@st.cache_data(ttl=50) # 快取 50 秒，避免過度頻繁呼叫 API
def scan_market():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    
    try:
        tickers = exchange.fetch_tickers()
    except Exception:
        return pd.DataFrame(), []

    all_coins = []
    symbol_vol = []
    
    # 🎯 嚴格黑名單：過濾掉非虛擬貨幣的標的
    blacklist = ['NVDA', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'COIN', 'SP500', 'NDX', 'DJI', 'GOLD', 'SILVER', 'NQ', 'BABA']
    
    for sym, data in tickers.items():
        if sym.endswith(':USDT') and data.get('quoteVolume') and data.get('percentage') is not None:
            base_coin = sym.split('/')[0].split('-')[0].split(':')[0]
            if base_coin in blacklist:
                continue
                
            all_coins.append({
                '幣種': sym.split(':')[0],
                '最新價格': data['last'],
                '24H漲跌(%)': data['percentage'],
                '24H 成交額': data['quoteVolume']
            })
            symbol_vol.append({'symbol': sym, 'volume': data['quoteVolume']})
            
    df_all_market = pd.DataFrame(all_coins).sort_values(by='24H漲跌(%)', ascending=False)
    
    # 為了維持網頁掃描速度，取成交量前 40 大幣種進行深度分析
    top_40 = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:40]
    signals = []
    
    for item in top_40:
        sym = item['symbol']
        try:
            # --- 策略 A：4H 區間假突破 (極短線 5M) ---
            ohlcv_4h = exchange.fetch_ohlcv(sym, '4h', limit=10)
            df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_4h['datetime'] = pd.to_datetime(df_4h['timestamp'], unit='ms')
            
            today_date = datetime.now(timezone.utc).date()
            first_4h = df_4h[(df_4h['datetime'].dt.date == today_date) & (df_4h['datetime'].dt.hour == 0)]
            
            range_high = first_4h['high'].values[0] if not first_4h.empty else None
            range_low = first_4h['low'].values[0] if not first_4h.empty else None
            
            ohlcv_5m = exchange.fetch_ohlcv(sym, '5m', limit=50)
            df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            current_close_5m = df_5m['close'].iloc[-2]
            prev_close_5m = df_5m['close'].iloc[-3]
            
            if range_high and range_low:
                # 假跌破做多
                if prev_close_5m < range_low and current_close_5m > range_low:
                    sl_price = df_5m['low'].iloc[-5:-1].min()
                    risk = current_close_5m - sl_price
                    if risk > 0 and (risk / current_close_5m) <= 0.02:
                        signals.append({
                            '幣種': sym.split(':')[0],
                            '策略': '⚡ 4H 假跌破 (5M 剝頭皮)',
                            '方向': '🟢 做多 (Long)',
                            '進場價': current_close_5m,
                            '停損價': sl_price,
                            '停利價': current_close_5m + (2 * risk),
                            '說明': f"跌破 4H 低點 ({range_low}) 誘空後，強勢收回。"
                        })
                
                # 假突破做空
                elif prev_close_5m > range_high and current_close_5m < range_high:
                    sl_price = df_5m['high'].iloc[-5:-1].max()
                    risk = sl_price - current_close_5m
                    if risk > 0 and (risk / current_close_5m) <= 0.02:
                        signals.append({
                            '幣種': sym.split(':')[0],
                            '策略': '⚡ 4H 假突破 (5M 剝頭皮)',
                            '方向': '🔴 做空 (Short)',
                            '進場價': current_close_5m,
                            '停損價': sl_price,
                            '停利價': current_close_5m - (2 * risk),
                            '說明': f"突破 4H 高點 ({range_high}) 誘多後，弱勢跌回。"
                        })

            # --- 策略 B：首波回撤 0.618 (中短線 15M) ---
            ohlcv_15m = exchange.fetch_ohlcv(sym, '15m', limit=100)
            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            macd = df_15m.ta.macd(fast=12, slow=26, signal=9)
            macd_line = macd.iloc[-2, 0]
            signal_line = macd.iloc[-2, 2]
            
            recent_high = df_15m['high'].iloc[-15:-2].max()
            recent_low = df_15m['low'].iloc[-15:-2].min()
            current_close_15m = df_15m['close'].iloc[-2]
            
            bos_bull = current_close_15m > recent_high
            bos_bear = current_close_15m < recent_low
            
            # 做多 0.618
            if macd_line > signal_line and bos_bull:
                swing_high = df_15m['high'].iloc[-3:].max()
                swing_low = recent_low
                entry_price = swing_high - 0.618 * (swing_high - swing_low)
                stop_loss = swing_low * 0.998
                risk = entry_price - stop_loss
                
                signals.append({
                    '幣種': sym.split(':')[0],
                    '策略': '🌟 首波回撤 (0.618 掛單)',
                    '方向': '🟢 做多 (Long)',
                    '進場價': entry_price,
                    '停損價': stop_loss,
                    '停利價': entry_price + (2 * risk),
                    '說明': "MACD 翻多且 15M 突破前高。請掛限價單等待價格回撤至 0.618。"
                })
                
            # 做空 0.618
            elif macd_line < signal_line and bos_bear:
                swing_low = df_15m['low'].iloc[-3:].min()
                swing_high = recent_high
                entry_price = swing_low + 0.618 * (swing_high - swing_low)
                stop_loss = swing_high * 1.002
                risk = stop_loss - entry_price
                
                signals.append({
                    '幣種': sym.split(':')[0],
                    '策略': '🌟 首波回撤 (0.618 掛單)',
                    '方向': '🔴 做空 (Short)',
                    '進場價': entry_price,
                    '停損價': stop_loss,
                    '停利價': entry_price - (2 * risk),
                    '說明': "MACD 翻空且 15M 跌破前低。請掛限價單等待價格反彈至 0.618。"
                })

        except Exception:
            pass
        
        # 避免觸發交易所 API 頻率限制
        time.sleep(0.05)
        
    return df_all_market, signals

# ==========================================
# 畫面渲染區塊
# ==========================================
st.caption(f"🔄 最後掃描時間：{time.strftime('%Y-%m-%d %H:%M:%S')} (每分鐘自動更新)")
st.divider()

with st.spinner('📡 正在執行 Data Trader 雙核心策略掃描中...'):
    df_market, active_signals = scan_market()

if df_market.empty:
    st.error("連線異常，請稍後再試。")
else:
    st.subheader(f"💡 當前精準狙擊訊號")
    
    if len(active_signals) > 0:
        for sig in active_signals:
            # 依據做多或做空顯示不同顏色的卡片
            if "做多" in sig['方向']:
                st.success(f"**{sig['幣種']}** | {sig['策略']}\n\n"
                           f"**方向**：{sig['方向']}\n\n"
                           f"🎯 **進場價**：`{sig['進場價']:.4f}`\n\n"
                           f"🛑 **停損價**：`{sig['停損價']:.4f}`\n\n"
                           f"💰 **停利價**：`{sig['停利價']:.4f}`\n\n"
                           f"📝 **邏輯**：{sig['說明']}")
            else:
                st.error(f"**{sig['幣種']}** | {sig['策略']}\n\n"
                           f"**方向**：{sig['方向']}\n\n"
                           f"🎯 **進場價**：`{sig['進場價']:.4f}`\n\n"
                           f"🛑 **停損價**：`{sig['停損價']:.4f}`\n\n"
                           f"💰 **停利價**：`{sig['停利價']:.4f}`\n\n"
                           f"📝 **邏輯**：{sig['說明']}")
    else:
        st.info("⚪ 目前市場沒有符合【4H 假突破】或【0.618 首波回撤】的完美訊號。Data Trader 說過：『錯過交易不等於虧損』，請耐心等待獵物上鉤！")
        
    st.divider()
    
    st.subheader("📊 幣圈 24H 漲跌排行榜 (全市場)")
    tab1, tab2 = st.tabs(["🔥 漲幅榜", "❄️ 跌幅榜"])
    
    with tab1:
        df_gainers = df_market.head(10).copy()
        df_gainers['24H漲跌(%)'] = df_gainers['24H漲跌(%)'].apply(lambda x: f"+{x:.2f}%")
        st.dataframe(df_gainers[['幣種', '最新價格', '24H漲跌(%)']], use_container_width=True, hide_index=True)
        
    with tab2:
        df_losers = df_market.tail(10).sort_values(by='24H漲跌(%)', ascending=True).copy()
        df_losers['24H漲跌(%)'] = df_losers['24H漲跌(%)'].apply(lambda x: f"{x:.2f}%")
        st.dataframe(df_losers[['幣種', '最新價格', '24H漲跌(%)']], use_container_width=True, hide_index=True)
