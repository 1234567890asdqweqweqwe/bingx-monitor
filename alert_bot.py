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

def get_overall_sr(df_1h, current_price):
    """計算 1H 大級別整體壓力與支撐"""
    df_1h['swing_high'] = df_1h['high'] == df_1h['high'].rolling(window=11, center=True).max()
    df_1h['swing_low'] = df_1h['low'] == df_1h['low'].rolling(window=11, center=True).min()
    swing_highs = df_1h[df_1h['swing_high']]['high'].dropna().tolist()
    swing_lows = df_1h[df_1h['swing_low']]['low'].dropna().tolist()
    res_list = [h for h in swing_highs if h > current_price]
    sup_list = [l for l in swing_lows if l < current_price]
    return (min(res_list) if res_list else df_1h['high'].max(), 
            max(sup_list) if sup_list else df_1h['low'].min())

def main():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 啟動【山寨幣 S 級狙擊版：三重時間框架 + ADX 動能 + 1.5R 空間】...")
    
    try:
        tickers = exchange.fetch_tickers()
        symbol_vol = [{'symbol': sym, 'volume': data['quoteVolume']} 
                      for sym, data in tickers.items() if sym.endswith(':USDT') and data.get('quoteVolume')]
    except Exception as e:
        return

    # ⛔ 終極黑名單：徹底封殺大盤、傳產與主流幣
    blacklist = [
        'GOLD', 'SILVER', 'XAU', 'XAG', 'WTI', 'BRENT', 'OIL', 'DXY', 
        'NVDA', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'COIN', 'BABA', 'MSTR',
        'SP500', 'NDX', 'DJI', 'NQ', 'US30', 'BTC', 'ETH'
    ]

    # 🛡️ 智慧名稱濾網：精準鎖定純正的山寨幣
    filtered_vol = []
    for item in symbol_vol:
        base = item['symbol'].split('/')[0].split('-')[0].split(':')[0]
        
        if base in blacklist or 'NCSK' in base or 'MSTR' in base:
            continue
        if len(base) > 8 and not base.startswith('100'):
            continue
            
        filtered_vol.append(item)

    # 鎖定資金最強的前 50 大純正山寨幣
    top_50 = sorted(filtered_vol, key=lambda x: x['volume'], reverse=True)[:50]

    for item in top_50:
        sym = item['symbol']
        try:
            ohlcv_4h = exchange.fetch_ohlcv(sym, '4h', limit=50)
            df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_4h['datetime'] = pd.to_datetime(df_4h['timestamp'], unit='ms')
            ema200_4h = df_4h['close'].ewm(span=200, adjust=False).mean().iloc[-1] if len(df_4h) > 20 else df_4h['close'].iloc[-1]
            trend_4h = "BULLISH" if df_4h['close'].iloc[-1] > ema200_4h else "BEARISH"
            
            ohlcv_1h = exchange.fetch_ohlcv(sym, '1h', limit=210)
            df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            ema200_1h = df_1h['close'].ewm(span=200, adjust=False).mean().iloc[-1]
            trend_1h = "BULLISH" if df_1h['close'].iloc[-1] > ema200_1h else "BEARISH"
            
            ohlcv_15m = exchange.fetch_ohlcv(sym, '15m', limit=250)
            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_close_15m = df_15m['close'].iloc[-2]
            current_now_15m = df_15m['close'].iloc[-1]
            prev_close_15m = df_15m['close'].iloc[-3]

            resistance_level, support_level = get_overall_sr(df_1h, current_now_15m)
            
            df_15m.ta.adx(length=14, append=True)
            adx_val = df_15m['ADX_14'].iloc[-2] if 'ADX_14' in df_15m.columns else 0

            today_date = datetime.now(timezone.utc).date()
            first_4h = df_4h[(df_4h['datetime'].dt.date == today_date) & (df_4h['datetime'].dt.hour == 0)]
            range_high = first_4h['high'].values[0] if not first_4h.empty else None
            range_low = first_4h['low'].values[0] if not first_4h.empty else None
            
            if range_high and range_low and adx_val > 20: 
                if prev_close_15m < range_low and current_close_15m > range_low and trend_4h == "BULLISH" and trend_1h == "BULLISH":
                    sl_price = df_15m['low'].iloc[-5:-1].min()
                    risk = current_now_15m - sl_price
                    if risk > 0 and (risk / current_now_15m) <= 0.03:
                        tp_price = min(current_now_15m + (2.5 * risk), resistance_level * 0.998)
                        if (tp_price - current_now_15m) >= (risk * 1.5):
                            msg = (f"🔥 **【山寨幣 S 級訊號：大順風假跌破】** 🔥\n"
                                   f"🪙 `{sym}` | 🟢 **強勢做多**\n"
                                   f"*(4H/1H 大趨勢保護中，主力洗盤結束)*\n\n"
                                   f"🎯 **推薦進場**：`{range_low:.4f}` ~ `{current_now_15m:.4f}`\n"
                                   f"🛑 **防守停損**：`{sl_price:.4f}`\n"
                                   f"💰 **安全停利**：`{tp_price:.4f}`\n\n"
                                   f"*(🛡️ 空間極佳！距離 1H 壓力位 `{resistance_level:.4f}` 還有很大距離)*")
                            send_telegram_message(msg)
                            time.sleep(1)
                        
                elif prev_close_15m > range_high and current_close_15m < range_high and trend_4h == "BEARISH" and trend_1h == "BEARISH":
                    sl_price = df_15m['high'].iloc[-5:-1].max()
                    risk = sl_price - current_now_15m
                    if risk > 0 and (risk / current_now_15m) <= 0.03:
                        tp_price = max(current_now_15m - (2.5 * risk), support_level * 1.002)
                        if (current_now_15m - tp_price) >= (risk * 1.5):
                            msg = (f"🔥 **【山寨幣 S 級訊號：大順風假突破】** 🔥\n"
                                   f"🪙 `{sym}` | 🔴 **強勢做空**\n"
                                   f"*(4H/1H 大趨勢保護中，散戶追高被套)*\n\n"
                                   f"🎯 **推薦進場**：`{current_now_15m:.4f}` ~ `{range_high:.4f}`\n"
                                   f"🛑 **防守停損**：`{sl_price:.4f}`\n"
                                   f"💰 **安全停利**：`{tp_price:.4f}`\n\n"
                                   f"*(🛡️ 空間極佳！距離 1H 支撐位 `{support_level:.4f}` 還有很大距離)*")
                            send_telegram_message(msg)
                            time.sleep(1)

            macd = df_15m.ta.macd(fast=12, slow=26, signal=9)
            macd_line = macd.iloc[-2, 0]
            signal_line = macd.iloc[-2, 2]
            bos_bull = current_close_15m > df_15m['high'].iloc[-15:-2].max()
            bos_bear = current_close_15m < df_15m['low'].iloc[-15:-2].min()
            
            if macd_line > signal_line and bos_bull and trend_4h == "BULLISH" and trend_1h == "BULLISH" and adx_val > 20:
                swing_high = df_15m['high'].iloc[-3:].max()
                e_0382 = swing_high - 0.382 * (swing_high - df_15m['low'].iloc[-15:-2].min())
                e_0618 = swing_high - 0.618 * (swing_high - df_15m['low'].iloc[-15:-2].min())
                sl_price = df_15m['low'].iloc[-15:-2].min() * 0.998
                risk = e_0382 - sl_price
                tp_price = min(e_0382 + (2.5 * risk), resistance_level * 0.998)
                
                if (tp_price - e_0382) >= (risk * 1.5):
                    msg = (f"💎 **【山寨幣 S 級訊號：順風波段起漲】** 💎\n"
                           f"🪙 `{sym}` | 🟢 **強勢做多**\n\n"
                           f"🎯 **進場區間**：`{e_0618:.4f}` ~ `{e_0382:.4f}`\n"
                           f"🛑 **防守停損**：`{sl_price:.4f}` | 💰 **安全停利**：`{tp_price:.4f}`\n"
                           f"*(三重趨勢一致且動能強勁，為高勝率單！)*")
                    send_telegram_message(msg)
                    time.sleep(1)
                    
            elif macd_line < signal_line and bos_bear and trend_4h == "BEARISH" and trend_1h == "BEARISH" and adx_val > 20:
                swing_low = df_15m['low'].iloc[-3:].min()
                e_0382 = swing_low + 0.382 * (df_15m['high'].iloc[-15:-2].max() - swing_low)
                e_0618 = swing_low + 0.618 * (df_15m['high'].iloc[-15:-2].max() - swing_low)
                sl_price = df_15m['high'].iloc[-15:-2].max() * 1.002
                risk = sl_price - e_0382
                tp_price = max(e_0382 - (2.5 * risk), support_level * 1.002)
                
                if (e_0382 - tp_price) >= (risk * 1.5):
                    msg = (f"💎 **【山寨幣 S 級訊號：順風波段起跌】** 💎\n"
                           f"🪙 `{sym}` | 🔴 **強勢做空**\n\n"
                           f"🎯 **進場區間**：`{e_0382:.4f}` ~ `{e_0618:.4f}`\n"
                           f"🛑 **防守停損**：`{sl_price:.4f}` | 💰 **安全停利**：`{tp_price:.4f}`\n"
                           f"*(三重趨勢一致且動能強勁，為高勝率單！)*")
                    send_telegram_message(msg)
                    time.sleep(1)

        except Exception as e:
            pass
            
if __name__ == '__main__':
    main()
