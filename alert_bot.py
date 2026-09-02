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
    print(f"[{now}] 啟動【預測走勢＋動態進場區間】三引擎系統...")
    
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
            current_now_15m = df_15m['close'].iloc[-1] 
            
            ohlcv_5m = exchange.fetch_ohlcv(sym, '5m', limit=50)
            df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_close_5m = df_5m['close'].iloc[-2]
            prev_close_5m = df_5m['close'].iloc[-3]

            # --- 引擎 A：4H 區間假突破 (預測反轉) ---
            today_date = datetime.now(timezone.utc).date()
            first_4h = df_4h[(df_4h['datetime'].dt.date == today_date) & (df_4h['datetime'].dt.hour == 0)]
            range_high = first_4h['high'].values[0] if not first_4h.empty else None
            range_low = first_4h['low'].values[0] if not first_4h.empty else None
            
            if range_high and range_low:
                if prev_close_5m < range_low and current_close_5m > range_low:
                    sl_price = df_5m['low'].iloc[-5:-1].min()
                    entry_zone_high = current_now_15m
                    entry_zone_low = range_low
                    risk = entry_zone_high - sl_price
                    
                    if risk > 0 and (risk / entry_zone_high) <= 0.02:
                        tp_price = entry_zone_high + (2.5 * risk)
                        msg = (f"⚡ **【走勢預測：4H 誘空結束，準備強勢上漲】** ⚡\n"
                               f"🪙 `{sym}` | 🟢 **做多 (Long)**\n"
                               f"*(洗盤已結束，即將啟動反轉行情)*\n\n"
                               f"🎯 **推薦進場區間**：`{entry_zone_low:.4f}` ~ `{entry_zone_high:.4f}`\n"
                               f"*(💡建議：一半倉位現價市價進場，一半掛單在區間下緣)*\n\n"
                               f"🛑 **停損 (跌破前低)**：`{sl_price:.4f}`\n"
                               f"💰 **停利預測**：`{tp_price:.4f}`")
                        send_telegram_message(msg)
                        time.sleep(1)
                        
                elif prev_close_5m > range_high and current_close_5m < range_high:
                    sl_price = df_5m['high'].iloc[-5:-1].max()
                    entry_zone_low = current_now_15m
                    entry_zone_high = range_high
                    risk = sl_price - entry_zone_low
                    
                    if risk > 0 and (risk / entry_zone_low) <= 0.02:
                        tp_price = entry_zone_low - (2.5 * risk)
                        msg = (f"⚡ **【走勢預測：4H 誘多結束，準備暴跌回調】** ⚡\n"
                               f"🪙 `{sym}` | 🔴 **做空 (Short)**\n"
                               f"*(多軍動能耗盡，主力準備砸盤)*\n\n"
                               f"🎯 **推薦進場區間**：`{entry_zone_low:.4f}` ~ `{entry_zone_high:.4f}`\n"
                               f"*(💡建議：一半倉位現價市價進場，一半掛單在區間上緣)*\n\n"
                               f"🛑 **停損 (突破前高)**：`{sl_price:.4f}`\n"
                               f"💰 **停利預測**：`{tp_price:.4f}`")
                        send_telegram_message(msg)
                        time.sleep(1)

            # --- 引擎 B：淺回撤動能預測 (0.382~0.618 區間) ---
            macd = df_15m.ta.macd(fast=12, slow=26, signal=9)
            macd_line = macd.iloc[-2, 0]
            signal_line = macd.iloc[-2, 2]
            recent_high = df_15m['high'].iloc[-15:-2].max()
            recent_low = df_15m['low'].iloc[-15:-2].min()
            bos_bull = current_close_15m > recent_high
            bos_bear = current_close_15m < recent_low
            
            if macd_line > signal_line and bos_bull:
                swing_high = df_15m['high'].iloc[-3:].max()
                entry_0382 = swing_high - 0.382 * (swing_high - recent_low)
                entry_0618 = swing_high - 0.618 * (swing_high - recent_low)
                sl_price = recent_low * 0.998
                risk = entry_0382 - sl_price
                
                msg = (f"🌟 **【走勢預測：動能突破，回踩後將再創高】** 🌟\n"
                       f"🪙 `{sym}` | 🟢 **做多 (Long)**\n\n"
                       f"🎯 **推薦進場區間**：`{entry_0618:.4f}` ~ `{entry_0382:.4f}`\n"
                       f"*(💡建議：若現價已在區間內，可直接市價買入 50%，不怕錯失行情)*\n\n"
                       f"🛑 **停損**：`{sl_price:.4f}`\n"
                       f"💰 **停利預測**：`{entry_0382 + (2.5*risk):.4f}`")
                send_telegram_message(msg)
                time.sleep(1)
                
            elif macd_line < signal_line and bos_bear:
                swing_low = df_15m['low'].iloc[-3:].min()
                entry_0382 = swing_low + 0.382 * (recent_high - swing_low)
                entry_0618 = swing_low + 0.618 * (recent_high - swing_low)
                sl_price = recent_high * 1.002
                risk = sl_price - entry_0382
                
                msg = (f"🌟 **【走勢預測：支撐跌破，反彈後將繼續破底】** 🌟\n"
                       f"🪙 `{sym}` | 🔴 **做空 (Short)**\n\n"
                       f"🎯 **推薦進場區間**：`{entry_0382:.4f}` ~ `{entry_0618:.4f}`\n"
                       f"*(💡建議：若現價已在區間內，可直接市價做空 50%，保證上車)*\n\n"
                       f"🛑 **停損**：`{sl_price:.4f}`\n"
                       f"💰 **停利預測**：`{entry_0382 - (2.5*risk):.4f}`")
                send_telegram_message(msg)
                time.sleep(1)

            # --- 引擎 C：7 星全指標大共振 ---
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
            if htf_trend == "BULLISH": bull_factors.append("🌐 大趨勢看漲")
            if dow_bull: bull_factors.append("📐 結構突破 (HH)")
            if macd_line > signal_line and macd_line > 0: bull_factors.append("⚡ MACD 爆發")
            if adx > 20 and dips > dins: bull_factors.append("📈 ADX 趨勢成型")
            if psar_bull: bull_factors.append("🎯 PSAR 支撐")
            if current_close_15m >= upper_band: bull_factors.append("📊 突破布林上軌")
            if fvg_bull: bull_factors.append("🐋 主力買方缺口")

            bear_factors = []
            if htf_trend == "BEARISH": bear_factors.append("🌐 大趨勢看跌")
            if dow_bear: bear_factors.append("📐 結構跌破 (LL)")
            if macd_line < signal_line and macd_line < 0: bear_factors.append("⚡ MACD 爆發")
            if adx > 20 and dins > dips: bear_factors.append("📈 ADX 趨勢成型")
            if psar_bear: bear_factors.append("🎯 PSAR 壓力")
            if current_close_15m <= lower_band: bear_factors.append("📊 跌破布林下軌")
            if fvg_bear: bear_factors.append("🐋 主力賣方缺口")

            if len(bull_factors) >= 6:
                msg = (f"🏆 **【走勢預測：強烈多方共振，極高機率單邊暴漲】**\n"
                       f"🪙 `{sym}` | 🟢 **強勢做多**\n\n"
                       f"🎯 **推薦進場**：動能過強不建議等回調，**可直接市價 `{current_now_15m:.4f}` 買入！**\n"
                       f"🛑 **防守停損**：`{current_now_15m - (atr * 1.5):.4f}`\n"
                       f"💰 **停利預測**：`{current_now_15m + (atr * 2.5):.4f}`\n\n"
                       f"共振指標 ({len(bull_factors)}/7)：\n" + "\n".join([f"• {f}" for f in bull_factors]))
                send_telegram_message(msg)
                time.sleep(1)

            if len(bear_factors) >= 6:
                msg = (f"🏆 **【走勢預測：強烈空方共振，極高機率單邊暴跌】**\n"
                       f"🪙 `{sym}` | 🔴 **強勢做空**\n\n"
                       f"🎯 **推薦進場**：動能過強不建議等反彈，**可直接市價 `{current_now_15m:.4f}` 做空！**\n"
                       f"🛑 **防守停損**：`{current_now_15m + (atr * 1.5):.4f}`\n"
                       f"💰 **停利預測**：`{current_now_15m - (atr * 2.5):.4f}`\n\n"
                       f"共振指標 ({len(bear_factors)}/7)：\n" + "\n".join([f"• {f}" for f in bear_factors]))
                send_telegram_message(msg)
                time.sleep(1)

        except Exception as e:
            pass
            
if __name__ == '__main__':
    main()
