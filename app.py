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
st.set_page_config(page_title="AI 5分鐘極速狙擊儀表板", layout="centered")
st.title("🎯 5分鐘極短線 ＋ 動態進場 (純幣圈)")
st.write("完全採用 Data Trader 與 SMC 核心策略。每 60 秒掃描全市場 5 分鐘 K 線，精準預測反轉。")

count = st_autorefresh(interval=60000, limit=None, key="auto_refresh")

@st.cache_data(ttl=50)
def scan_market():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    
    try:
        tickers = exchange.fetch_tickers()
    except Exception:
        return pd.DataFrame(), []

    all_coins = []
    symbol_vol = []
    
    # 嚴格黑名單
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
    top_40 = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:40]
    signals = []
    
    for item in top_40:
        sym = item['symbol']
        try:
            # 獲取 4H 數據 (用於每日區間)
            ohlcv_4h = exchange.fetch_ohlcv(sym, '4h', limit=10)
            df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_4h['datetime'] = pd.to_datetime(df_4h['timestamp'], unit='ms')
            
            # 獲取 15M 數據 (僅作大趨勢方向防守，不作進場觸發)
            ohlcv_15m = exchange.fetch_ohlcv(sym, '15m', limit=100)
            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            close_15m = df_15m['close'].iloc[-1]
            ema200_15m = df_15m['close'].ewm(span=200, adjust=False).mean().iloc[-1] if len(df_15m) >= 50 else close_15m
            htf_trend = "BULLISH" if close_15m > ema200_15m else "BEARISH"

            # 獲取 5M 數據 (★★★ 全部改用 5M 作為核心分析 ★★★)
            ohlcv_5m = exchange.fetch_ohlcv(sym, '5m', limit=250)
            df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_close_5m = df_5m['close'].iloc[-2]
            current_now_5m = df_5m['close'].iloc[-1]
            prev_close_5m = df_5m['close'].iloc[-3]

            # --- 引擎 A：4H 區間假突破 (5M 觸發) ---
            today_date = datetime.now(timezone.utc).date()
            first_4h = df_4h[(df_4h['datetime'].dt.date == today_date) & (df_4h['datetime'].dt.hour == 0)]
            range_high = first_4h['high'].values[0] if not first_4h.empty else None
            range_low = first_4h['low'].values[0] if not first_4h.empty else None
            
            if range_high and range_low:
                if prev_close_5m < range_low and current_close_5m > range_low:
                    sl_price = df_5m['low'].iloc[-5:-1].min()
                    risk = current_now_5m - sl_price
                    if risk > 0 and (risk / current_now_5m) <= 0.02:
                        signals.append({
                            '幣種': sym.split(':')[0],
                            '方向': '🟢 5M 極速做多 (Long)',
                            '預測': '⚡ 4H 誘空結束，準備強勢上漲',
                            '進場': f"`{range_low:.4f}` ~ `{current_now_5m:.4f}`",
                            '停損': sl_price,
                            '停利': current_now_5m + (2.5 * risk),
                            '建議': 'Data Trader 建議：一半倉位現價進，一半掛在區間下緣。'
                        })
                elif prev_close_5m > range_high and current_close_5m < range_high:
                    sl_price = df_5m['high'].iloc[-5:-1].max()
                    risk = sl_price - current_now_5m
                    if risk > 0 and (risk / current_now_5m) <= 0.02:
                        signals.append({
                            '幣種': sym.split(':')[0],
                            '方向': '🔴 5M 極速做空 (Short)',
                            '預測': '⚡ 4H 誘多結束，準備暴跌回調',
                            '進場': f"`{current_now_5m:.4f}` ~ `{range_high:.4f}`",
                            '停損': sl_price,
                            '停利': current_now_5m - (2.5 * risk),
                            '建議': 'Data Trader 建議：一半倉位現價進，一半掛在區間上緣。'
                        })

            # --- 引擎 B：淺回撤動能預測 (改為 5M 分析) ---
            macd = df_5m.ta.macd(fast=12, slow=26, signal=9)
            macd_line = macd.iloc[-2, 0]
            signal_line = macd.iloc[-2, 2]
            
            # 抓取 5M 前高前低
            recent_high = df_5m['high'].iloc[-15:-2].max()
            recent_low = df_5m['low'].iloc[-15:-2].min()
            bos_bull = current_close_5m > recent_high
            bos_bear = current_close_5m < recent_low
            
            if macd_line > signal_line and bos_bull:
                swing_high = df_5m['high'].iloc[-3:].max()
                e_0382 = swing_high - 0.382 * (swing_high - recent_low)
                e_0618 = swing_high - 0.618 * (swing_high - recent_low)
                sl_price = recent_low * 0.998
                signals.append({
                    '幣種': sym.split(':')[0],
                    '方向': '🟢 5M 極速做多 (Long)',
                    '預測': '🌟 5分鐘動能突破 (SMC BOS)，首波回踩後將創高',
                    '進場': f"`{e_0618:.4f}` ~ `{e_0382:.4f}`",
                    '停損': sl_price,
                    '停利': e_0382 + (2.5 * (e_0382 - sl_price)),
                    '建議': '現價若在區間內，直接市價 50% 不怕錯過。'
                })
            elif macd_line < signal_line and bos_bear:
                swing_low = df_5m['low'].iloc[-3:].min()
                e_0382 = swing_low + 0.382 * (recent_high - swing_low)
                e_0618 = swing_low + 0.618 * (recent_high - swing_low)
                sl_price = recent_high * 1.002
                signals.append({
                    '幣種': sym.split(':')[0],
                    '方向': '🔴 5M 極速做空 (Short)',
                    '預測': '🌟 5分鐘支撐跌破 (SMC BOS)，首波反彈後將破底',
                    '進場': f"`{e_0382:.4f}` ~ `{e_0618:.4f}`",
                    '停損': sl_price,
                    '停利': e_0382 - (2.5 * (sl_price - e_0382)),
                    '建議': '現價若在區間內，直接市價 50% 保證上車。'
                })

            # --- 引擎 C：7 星全指標大共振 (改為 5M 計算) ---
            df_5m.ta.adx(length=14, append=True)
            df_5m.ta.psar(append=True)
            bbands = df_5m.ta.bbands(length=20, std=2)
            df_5m.ta.atr(length=14, append=True)
            
            adx = df_5m['ADX_14'].iloc[-2] if 'ADX_14' in df_5m.columns else 0
            dips = df_5m['DMP_14'].iloc[-2] if 'DMP_14' in df_5m.columns else 0
            dins = df_5m['DMN_14'].iloc[-2] if 'DMN_14' in df_5m.columns else 0
            psar_col = [c for c in df_5m.columns if c.startswith('PSARl')]
            psars_col = [c for c in df_5m.columns if c.startswith('PSARs')]
            psar_bull = pd.notna(df_5m[psar_col[0]].iloc[-2]) if psar_col else False
            psar_bear = pd.notna(df_5m[psars_col[0]].iloc[-2]) if psars_col else False
            upper_band = bbands.iloc[-2, 2]
            lower_band = bbands.iloc[-2, 0]
            atr = df_5m['ATRr_14'].iloc[-2]
            
            # SMC FVG 缺口 (5M)
            fvg_bull = (df_5m['high'].iloc[-5] < df_5m['low'].iloc[-3]) and (df_5m['close'].iloc[-4] > df_5m['open'].iloc[-4])
            fvg_bear = (df_5m['low'].iloc[-5] > df_5m['high'].iloc[-3]) and (df_5m['close'].iloc[-4] < df_5m['open'].iloc[-4])
            dow_bull = (df_5m['high'].iloc[-2] > df_5m['high'].iloc[-10:-3].max()) and (df_5m['low'].iloc[-2] > df_5m['low'].iloc[-10:-3].min())
            dow_bear = (df_5m['low'].iloc[-2] < df_5m['low'].iloc[-10:-3].min()) and (df_5m['high'].iloc[-2] < df_5m['high'].iloc[-10:-3].max())

            bull_factors = sum([htf_trend=="BULLISH", dow_bull, macd_line>signal_line and macd_line>0, adx>20 and dips>dins, psar_bull, current_close_5m>=upper_band, fvg_bull])
            bear_factors = sum([htf_trend=="BEARISH", dow_bear, macd_line<signal_line and macd_line<0, adx>20 and dins>dips, psar_bear, current_close_5m<=lower_band, fvg_bear])

            if bull_factors >= 6:
                signals.append({
                    '幣種': sym.split(':')[0],
                    '方向': '🟢 5M 強勢做多 (Long)',
                    '預測': f'🏆 5分鐘極短線強烈共振 ({bull_factors}/7)，極高機率單邊暴漲',
                    '進場': f"`{current_now_5m:.4f}` (市價直接買入)",
                    '停損': current_now_5m - (atr * 1.5),
                    '停利': current_now_5m + (atr * 2.5),
                    '建議': '動能過強，絕對不要等回調，直接上車！'
                })
            elif bear_factors >= 6:
                signals.append({
                    '幣種': sym.split(':')[0],
                    '方向': '🔴 5M 強勢做空 (Short)',
                    '預測': f'🏆 5分鐘極短線強烈共振 ({bear_factors}/7)，極高機率單邊暴跌',
                    '進場': f"`{current_now_5m:.4f}` (市價直接做空)",
                    '停損': current_now_5m + (atr * 1.5),
                    '停利': current_now_5m - (atr * 2.5),
                    '建議': '動能過強，絕對不要等反彈，直接上車！'
                })

        except Exception:
            pass
        
        time.sleep(0.05)
        
    return df_all_market, signals

# ==========================================
# 畫面渲染區塊
# ==========================================
st.caption(f"🔄 最後掃描時間：{time.strftime('%Y-%m-%d %H:%M:%S')} (每分鐘自動更新)")
st.divider()

with st.spinner('📡 正在執行 5 分鐘全市場走勢預測掃描中...'):
    df_market, active_signals = scan_market()

if df_market.empty:
    st.error("連線異常，請稍後再試。")
else:
    st.subheader(f"💡 5 分鐘極速進場清單")
    
    if len(active_signals) > 0:
        for sig in active_signals:
            card_color = st.success if "多" in sig['方向'] else st.error
            card_color(f"**{sig['幣種']}** | {sig['方向']}\n\n"
                       f"**預測走勢**：{sig['預測']}\n\n"
                       f"🎯 **推薦進場**：{sig['進場']}\n\n"
                       f"🛑 **停損價**：`{sig['停損']:.4f}`\n\n"
                       f"💰 **停利價**：`{sig['停利']:.4f}`\n\n"
                       f"💡 **AI 建議**：{sig['建議']}")
    else:
        st.info("⚪ 目前 5 分鐘線沒有極端反轉或突破訊號。Data Trader 說過：等待才是最賺錢的部位，請耐心等獵物掉進陷阱！")
        
    st.divider()
    
    st.subheader("📊 幣圈 24H 漲跌排行榜")
    tab1, tab2 = st.tabs(["🔥 漲幅榜", "❄️ 跌幅榜"])
    
    with tab1:
        df_gainers = df_market.head(10).copy()
        df_gainers['24H漲跌(%)'] = df_gainers['24H漲跌(%)'].apply(lambda x: f"+{x:.2f}%")
        st.dataframe(df_gainers[['幣種', '最新價格', '24H漲跌(%)']], use_container_width=True, hide_index=True)
        
    with tab2:
        df_losers = df_market.tail(10).sort_values(by='24H漲跌(%)', ascending=True).copy()
        df_losers['24H漲跌(%)'] = df_losers['24H漲跌(%)'].apply(lambda x: f"{x:.2f}%")
        st.dataframe(df_losers[['幣種', '最新價格', '24H漲跌(%)']], use_container_width=True, hide_index=True)
