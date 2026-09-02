import ccxt
import requests
import os
import time
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"})

def main():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 啟動【三引擎全限價掛單版：等待回踩進場】...")
    
    try:
        tickers = exchange.fetch_tickers()
        symbol_vol = [{'symbol': sym, 'volume': data['quoteVolume']} 
                      for sym, data in tickers.items() if sym.endswith(':USDT') and data.get('quoteVolume')]
        top_50 = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:50]
    except Exception as e:
        print(f"取得行情失敗: {e}")
        return

    blacklist = ['NVDA', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'COIN', 'SP500', 'NDX', 'DJI', 'GOLD', 'SILVER', 'NQ', 'BABA']

    for item in top_50:
        sym = item['symbol']
        base_coin = sym.split('/')[0].split('-')[0].split(':')[0]
        if base_coin in blacklist:
            continue
            
        try:
            # 獲取資料
            ohlcv_4h = exchange.fetch_ohlcv(sym, '4h', limit=10)
            df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_4h['datetime'] = pd.to_datetime(df_4h['timestamp'], unit='ms')
            
            ohlcv_1h = exchange.fetch_ohlcv(sym, '1h', limit=210)
            df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            close_1h = df_1h['close'].iloc[-1]
            ema200_1h = df_1h['close'].ewm(span=200, adjust=False).mean().iloc[-1]
            htf_trend = "BULLISH" if close_1h > ema200_1h else "BEARISH"

            ohlcv_15m = exchange.fetch_ohlcv(sym, '15m', limit=250)
            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_close_15m = df_15m['close'].iloc[-2]
            
            ohlcv_5m = exchange.fetch_ohlcv(sym, '5m', limit=50)
            df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_close_5m = df_5m['close'].iloc[-2]
            prev_close_5m = df_5m['close'].iloc[-3]

            # ==========================================
            # 引擎 A：4H 區間假突破 (改為：突破位回踩掛單)
            # ==========================================
            today_date = datetime.now(timezone.utc).date()
            first_4h = df_4h[(df_4h['datetime'].dt.date == today_date) & (df_4h['datetime'].dt.hour == 0)]
            range_high = first_4h['high'].values[0] if not first_4h.empty else None
            range_low = first_4h['low'].values[0] if not first_4h.empty else None
            
            if range_high and range_low:
                # 假跌破做多
                if prev_close_5m < range_low and current_close_5m > range_low:
                    sl_price = df_5m['low'].iloc[-5:-1].min()
                    
                    # 【核心修改】：進場價不追高，直接掛在 4H 的低點線上等它跌回來踩！
                    entry_price = range_low 
                    risk = entry_price - sl_price
                    
                    if risk > 0 and (risk / entry_price) <= 0.02:
                        tp_price = entry_price + (2 * risk)
                        msg = (f"⚡ **【引擎 A：4H 假跌破 做多】** ⚡\n"
                               f"🪙 `{sym}` | 狀態：等待回踩區間\n"
                               f"*(請直接打開交易所設定限價單，不要市價追！)*\n\n"
                               f"🎯 **掛單進場**：`{entry_price:.4f}`\n"
                               f"🛑 **停損**：`{sl_price:.4f}`\n"
                               f"💰 **停利 (1:2)**：`{tp_price:.4f}`\n\n"
                               f"⚠️ 取消條件：若價格未回踩並直接漲破 `{tp_price:.4f}`，請手動取消掛單。")
                        send_telegram_message(msg)
                        time.sleep(1)
                        
                # 假突破做空
                elif prev_close_5m > range_high and current_close_5m < range_high:
                    sl_price = df_5m['high'].iloc[-5:-1].max()
                    
                    # 【核心修改】：進場價直接掛在 4H 的高點線上等它反彈上來踩！
                    entry_price = range_high 
                    risk = sl_price - entry_price
                    
                    if risk > 0 and (risk / entry_price) <= 0.02:
                        tp_price = entry_price - (2 * risk)
                        msg = (f"⚡ **【引擎 A：4H 假突破 做空】** ⚡\n"
                               f"🪙 `{sym}` | 狀態：等待反彈測試\n"
                               f"*(請直接打開交易所設定限價單，不要市價追！)*\n\n"
                               f"🎯 **掛單進場**：`{entry_price:.4f}`\n"
                               f"🛑 **停損**：`{sl_price:.4f}`\n"
                               f"💰 **停利 (1:2)**：`{tp_price:.4f}`\n\n"
                               f"⚠️ 取消條件：若價格未反彈並直接跌破 `{tp_price:.4f}`，請手動取消掛單。")
                        send_telegram_message(msg)
                        time.sleep(1)

            # ==========================================
            # 引擎 B：0.618 首波回撤 (維持黃金比例掛單)
            # ==========================================
            macd = df_15m.ta.macd(fast=12, slow=26, signal=9)
            macd_line = macd.iloc[-2, 0]
            signal_line = macd.iloc[-2, 2]
            
            recent_high = df_15m['high'].iloc[-15:-2].max()
            recent_low = df_15m['low'].iloc[-15:-2].min()
            bos_bull = current_close_15m > recent_high
            bos_bear = current_close_15m < recent_low
            
            if macd_line > signal_line and bos_bull:
                swing_high = df_15m['high'].iloc[-3:].max()
                entry_price = swing_high - 0.618 * (swing_high - recent_low)
                risk = entry_price - (recent_low * 0.998)
                msg = (f"🌟 **【引擎 B：0.618 首波回撤 做多】** 🌟\n"
                       f"🪙 `{sym}` | 🎯 限價掛單: `{entry_price:.4f}`\n"
                       f"🛑 停損: `{recent_low * 0.998:.4f}` | 💰 停利: `{entry_price + (2*risk):.4f}`\n"
                       f"*(讓價格自己跌下來接你，沒吃到就算了不追高)*")
                send_telegram_message(msg)
                time.sleep(1)
                
            elif macd_line < signal_line and bos_bear:
                swing_low = df_15m['low'].iloc[-3:].min()
                entry_price = swing_low + 0.618 * (recent_high - swing_low)
                risk = (recent_high * 1.002) - entry_price
                msg = (f"🌟 **【引擎 B：0.618 首波回撤 做空】** 🌟\n"
                       f"🪙 `{sym}` | 🎯 限價掛單: `{entry_price:.4f}`\n"
                       f"🛑 停損: `{recent_high * 1.002:.4f}` | 💰 停利: `{entry_price - (2*risk):.4f}`\n"
                       f"*(讓價格自己漲上來接你，沒吃到就算了不追空)*")
                send_telegram_message(msg)
                time.sleep(1)

            # ==========================================
            # 引擎 C：7 星技術分析打分 (改為：K線 50% 中軸掛單)
            # ==========================================
            df_15m.ta.adx(length=14, append=True)
            df_15m.ta.psar(append=True)
            bbands = df_15m.ta.bbands(length=20, std=2)
            df_15m.ta.atr(length=14, append=True)
            
            adx = df_15m['ADX_14'].iloc[-2] if 'ADX_14' in df_15m.columns else 0
            dips = df_15m['DMP_14'].iloc[-2] if 'DMP_14' in df_15m.columns else 0
            dins = df_15m['DMN_14'].iloc[-2] if 'DMN_14' in df_15m.columns else 0
            
            psar_col = [c for c in df_15m.columns if c.startswith('PSARl')]
            psars_col = [c for c in df_15m.columns if c.startswith('PSARs')]
            psar_bull = pd.notna(df_15m[psar_col[0]].iloc[-2]) if psar_col else False
            psar_bear = pd.notna(df_15m[psars_col[0]].iloc[-2]) if psars_col else False

            upper_band = bbands.iloc[-2, 2]
            lower_band = bbands.iloc[-2, 0]
            atr = df_15m['ATRr_14'].iloc[-2]

            fvg_bull = (df_15m['high'].iloc[-5] < df_15m['low'].iloc[-3]) and (df_15m['close'].iloc[-4] > df_15m['open'].iloc[-4])
            fvg_bear = (df_15m['low'].iloc[-5] > df_15m['high'].iloc[-3]) and (df_15m['close'].iloc[-4] < df_15m['open'].iloc[-4])

            dow_bull = (df_15m['high'].iloc[-2] > df_15m['high'].iloc[-10:-3].max()) and (df_15m['low'].iloc[-2] > df_15m['low'].iloc[-10:-3].min())
            dow_bear = (df_15m['low'].iloc[-2] < df_15m['low'].iloc[-10:-3].min()) and (df_15m['high'].iloc[-2] < df_15m['high'].iloc[-10:-3].max())

            bull_factors = []
            if htf_trend == "BULLISH": bull_factors.append("🌐 1H 大趨勢看漲")
            if dow_bull: bull_factors.append("📐 突破前高 (Higher High)")
            if macd_line > signal_line and macd_line > 0: bull_factors.append("⚡ MACD 多頭強勢")
            if adx > 20 and dips > dins: bull_factors.append("📈 ADX 趨勢爆發")
            if psar_bull: bull_factors.append("🎯 PSAR 底部支撐")
            if current_close_15m >= upper_band: bull_factors.append("📊 布林帶向上突破")
            if fvg_bull: bull_factors.append("🐋 SMC 買方缺口")

            bear_factors = []
            if htf_trend == "BEARISH": bear_factors.append("🌐 1H 大趨勢看跌")
            if dow_bear: bear_factors.append("📐 跌破前低 (Lower Low)")
            if macd_line < signal_line and macd_line < 0: bear_factors.append("⚡ MACD 空頭強勢")
            if adx > 20 and dins > dips: bear_factors.append("📈 ADX 趨勢爆發")
            if psar_bear: bear_factors.append("🎯 PSAR 頂部壓力")
            if current_close_15m <= lower_band: bear_factors.append("📊 布林帶向下突破")
            if fvg_bear: bear_factors.append("🐋 SMC 賣方缺口")

            if len(bull_factors) >= 6:
                # 【核心修改】：進場價設在「訊號 K 線的 50% 一半位置」，強迫等待回調
                signal_candle_high = df_15m['high'].iloc[-2]
                signal_candle_low = df_15m['low'].iloc[-2]
                entry_price = (signal_candle_high + signal_candle_low) / 2
                
                msg = (f"🏆 **【引擎 C：7星指標強烈共振 ({len(bull_factors)}/7)】**\n"
                       f"🪙 `{sym}` | 🟢 **做多**\n"
                       f"*(強迫等待回調，請掛限價單在 K 線中軸)*\n\n"
                       f"🎯 **掛單進場 (50% 中軸)**：`{entry_price:.4f}`\n"
                       f"🛑 **停損**：`{entry_price - (atr * 1.5):.4f}`\n"
                       f"💰 **停利**：`{entry_price + (atr * 2.5):.4f}`")
                send_telegram_message(msg)
                time.sleep(1)

            if len(bear_factors) >= 6:
                signal_candle_high = df_15m['high'].iloc[-2]
                signal_candle_low = df_15m['low'].iloc[-2]
                entry_price = (signal_candle_high + signal_candle_low) / 2
                
                msg = (f"🏆 **【引擎 C：7星指標強烈共振 ({len(bear_factors)}/7)】**\n"
                       f"🪙 `{sym}` | 🔴 **做空**\n"
                       f"*(強迫等待反彈，請掛限價單在 K 線中軸)*\n\n"
                       f"🎯 **掛單進場 (50% 中軸)**：`{entry_price:.4f}`\n"
                       f"🛑 **停損**：`{entry_price + (atr * 1.5):.4f}`\n"
                       f"💰 **停利**：`{entry_price - (atr * 2.5):.4f}`")
                send_telegram_message(msg)
                time.sleep(1)

        except Exception as e:
            pass
            
if __name__ == '__main__':
    main()
