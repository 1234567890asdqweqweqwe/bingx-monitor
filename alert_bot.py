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
    print(f"[{now}] 啟動【1H 大戶防線 + 15M 精準狙擊】...")
    
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
            
            # 【核心升級】全面改用 15M 進行趨勢判斷與觸發
            ohlcv_15m = exchange.fetch_ohlcv(sym, '15m', limit=250)
            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            current_close_15m = df_15m['close'].iloc[-2]
            current_now_15m = df_15m['close'].iloc[-1]
            prev_close_15m = df_15m['close'].iloc[-3]

            resistance_level, support_level = get_overall_sr(df_1h, current_now_15m)

            # ==========================================
            # 引擎 A：4H 區間假突破 (由 15M 實體 K 線確認，勝率極高)
            # ==========================================
            today_date = datetime.now(timezone.utc).date()
            first_4h = df_4h[(df_4h['datetime'].dt.date == today_date) & (df_4h['datetime'].dt.hour == 0)]
            range_high = first_4h['high'].values[0] if not first_4h.empty else None
            range_low = first_4h['low'].values[0] if not first_4h.empty else None
            
            if range_high and range_low:
                # 15M 假跌破做多
                if prev_close_15m < range_low and current_close_15m > range_low:
                    sl_price = df_15m['low'].iloc[-5:-1].min()
                    entry_zone_high = current_now_15m
                    entry_zone_low = range_low
                    risk = entry_zone_high - sl_price
                    
                    if risk > 0 and (risk / entry_zone_high) <= 0.03:
                        tp_price = min(entry_zone_high + (2.5 * risk), resistance_level * 0.998)
                        if (tp_price - entry_zone_high) > (risk * 1.2):
                            msg = (f"⚡ **【15M 走勢預測：4H 假跌破，強勢反轉上漲】** ⚡\n"
                                   f"🪙 `{sym}` | 🟢 **做多 (Long)**\n"
                                   f"*(15M K線已確認收回區間，大戶洗盤結束)*\n\n"
                                   f"🎯 **推薦進場**：`{entry_zone_low:.4f}` ~ `{entry_zone_high:.4f}`\n"
                                   f"🛑 **防守停損**：`{sl_price:.4f}`\n"
                                   f"💰 **停利預測**：`{tp_price:.4f}`\n\n"
                                   f"*(🛡️ 已退避 1H 歷史壓力位：`{resistance_level:.4f}`)*")
                            send_telegram_message(msg)
                            time.sleep(1)
                        
                # 15M 假突破做空
                elif prev_close_15m > range_high and current_close_15m < range_high:
                    sl_price = df_15m['high'].iloc[-5:-1].max()
                    entry_zone_low = current_now_15m
                    entry_zone_high = range_high
                    risk = sl_price - entry_zone_low
                    
                    if risk > 0 and (risk / entry_zone_low) <= 0.03:
                        tp_price = max(entry_zone_low - (2.5 * risk), support_level * 1.002)
                        if (entry_zone_low - tp_price) > (risk * 1.2):
                            msg = (f"⚡ **【15M 走勢預測：4H 假突破，弱勢反轉暴跌】** ⚡\n"
                                   f"🪙 `{sym}` | 🔴 **做空 (Short)**\n"
                                   f"*(15M K線已確認跌回區間，散戶追高被套)*\n\n"
                                   f"🎯 **推薦進場**：`{entry_zone_low:.4f}` ~ `{entry_zone_high:.4f}`\n"
                                   f"🛑 **防守停損**：`{sl_price:.4f}`\n"
                                   f"💰 **停利預測**：`{tp_price:.4f}`\n\n"
                                   f"*(🛡️ 已退避 1H 歷史支撐位：`{support_level:.4f}`)*")
                            send_telegram_message(msg)
                            time.sleep(1)

            # ==========================================
            # 引擎 B：15M 淺回撤動能預測 (0.382~0.618)
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
                e_0382 = swing_high - 0.382 * (swing_high - recent_low)
                e_0618 = swing_high - 0.618 * (swing_high - recent_low)
                sl_price = recent_low * 0.998
                risk = e_0382 - sl_price
                tp_price = min(e_0382 + (2.5 * risk), resistance_level * 0.998)
                
                if (tp_price - e_0382) > (risk * 1.2):
                    msg = (f"🌟 **【15M 走勢預測：結構突破，波段起漲】** 🌟\n"
                           f"🪙 `{sym}` | 🟢 **做多 (Long)**\n\n"
                           f"🎯 **推薦進場區間**：`{e_0618:.4f}` ~ `{e_0382:.4f}`\n"
                           f"*(若現價在此區間，可直接建倉 50%)*\n\n"
                           f"🛑 **停損**：`{sl_price:.4f}` | 💰 **停利**：`{tp_price:.4f}`")
                    send_telegram_message(msg)
                    time.sleep(1)
                    
            elif macd_line < signal_line and bos_bear:
                swing_low = df_15m['low'].iloc[-3:].min()
                e_0382 = swing_low + 0.382 * (recent_high - swing_low)
                e_0618 = swing_low + 0.618 * (recent_high - swing_low)
                sl_price = recent_high * 1.002
                risk = sl_price - e_0382
                tp_price = max(e_0382 - (2.5 * risk), support_level * 1.002)
                
                if (e_0382 - tp_price) > (risk * 1.2):
                    msg = (f"🌟 **【15M 走勢預測：結構跌破，波段起跌】** 🌟\n"
                           f"🪙 `{sym}` | 🔴 **做空 (Short)**\n\n"
                           f"🎯 **推薦進場區間**：`{e_0382:.4f}` ~ `{e_0618:.4f}`\n"
                           f"*(若現價在此區間，可直接建倉 50%)*\n\n"
                           f"🛑 **停損**：`{sl_price:.4f}` | 💰 **停利**：`{tp_price:.4f}`")
                    send_telegram_message(msg)
                    time.sleep(1)

        except Exception as e:
            pass
            
if __name__ == '__main__':
    main()
