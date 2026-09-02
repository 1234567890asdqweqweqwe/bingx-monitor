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
    print(f"[{now}] 啟動【Data Trader 雙核心：4H假突破 + 0.618首波回撤】...")
    
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
            # ==========================================
            # 策略一：4H 區間假突破 (Data Trader 剝頭皮)
            # ==========================================
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
            
            # 策略一觸發判斷
            if range_high and range_low:
                if prev_close_5m < range_low and current_close_5m > range_low:
                    sl_price = df_5m['low'].iloc[-5:-1].min()
                    entry_price = current_close_5m
                    risk = entry_price - sl_price
                    if risk > 0 and (risk / entry_price) <= 0.02:
                        tp_price = entry_price + (2 * risk)
                        msg = (f"⚡ **【策略 A：4H 區間假跌破 做多】** ⚡\n"
                               f"🪙 幣種：`{sym}`\n"
                               f"🎯 **市價進場**：`{entry_price:.4f}`\n"
                               f"🛑 **停損 (低點)**：`{sl_price:.4f}`\n"
                               f"💰 **停利 (1:2)**：`{tp_price:.4f}`")
                        send_telegram_message(msg)
                        time.sleep(1)
                        
                elif prev_close_5m > range_high and current_close_5m < range_high:
                    sl_price = df_5m['high'].iloc[-5:-1].max()
                    entry_price = current_close_5m
                    risk = sl_price - entry_price
                    if risk > 0 and (risk / entry_price) <= 0.02:
                        tp_price = entry_price - (2 * risk)
                        msg = (f"⚡ **【策略 A：4H 區間假突破 做空】** ⚡\n"
                               f"🪙 幣種：`{sym}`\n"
                               f"🎯 **市價進場**：`{entry_price:.4f}`\n"
                               f"🛑 **停損 (高點)**：`{sl_price:.4f}`\n"
                               f"💰 **停利 (1:2)**：`{tp_price:.4f}`")
                        send_telegram_message(msg)
                        time.sleep(1)

            # ==========================================
            # 策略二：The First Pullback 首波回撤 (Data Trader 趨勢波段)
            # ==========================================
            ohlcv_15m = exchange.fetch_ohlcv(sym, '15m', limit=100)
            df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # 使用 MACD 確認趨勢確實反轉 (Data Trader 核心驗證)
            macd = df_15m.ta.macd(fast=12, slow=26, signal=9)
            macd_line = macd.iloc[-2, 0]
            signal_line = macd.iloc[-2, 2]
            
            recent_high = df_15m['high'].iloc[-15:-2].max()
            recent_low = df_15m['low'].iloc[-15:-2].min()
            current_close_15m = df_15m['close'].iloc[-2]
            
            bos_bull = current_close_15m > recent_high
            bos_bear = current_close_15m < recent_low
            
            # MACD 翻多且 15M 突破前高 -> 尋找 0.618 黃金做多區間
            if macd_line > signal_line and bos_bull:
                swing_high = df_15m['high'].iloc[-3:].max()
                swing_low = recent_low
                
                # Data Trader 獨門 0.618 黃金回撤位
                entry_price = swing_high - 0.618 * (swing_high - swing_low)
                stop_loss = swing_low * 0.998 
                risk = entry_price - stop_loss
                take_profit = entry_price + (2 * risk) # 固定 2R 盈虧比
                
                msg = (f"🌟 **【策略 B：首波回撤 0.618 狙擊做多】** 🌟\n"
                       f"🪙 幣種：`{sym}`\n"
                       f"**【Data Trader 劇本確認】**\n"
                       f"✅ MACD 確認跌勢反轉\n"
                       f"✅ 產生結構突破 (BOS)\n\n"
                       f"🎯 **掛限價單 (0.618 Golden Zone)**：`{entry_price:.4f}`\n"
                       f"🛑 **防守停損**：`{stop_loss:.4f}`\n"
                       f"💰 **TP 停利 (2R)**：`{take_profit:.4f}`\n\n"
                       f"*(不追高！請直接掛限價單等待價格回撤)*")
                send_telegram_message(msg)
                time.sleep(1)

            # MACD 翻空且 15M 跌破前低 -> 尋找 0.618 黃金做空區間
            elif macd_line < signal_line and bos_bear:
                swing_low = df_15m['low'].iloc[-3:].min()
                swing_high = recent_high
                
                entry_price = swing_low + 0.618 * (swing_high - swing_low)
                stop_loss = swing_high * 1.002
                risk = stop_loss - entry_price
                take_profit = entry_price - (2 * risk)
                
                msg = (f"🌟 **【策略 B：首波回撤 0.618 狙擊做空】** 🌟\n"
                       f"🪙 幣種：`{sym}`\n"
                       f"**【Data Trader 劇本確認】**\n"
                       f"✅ MACD 確認漲勢反轉\n"
                       f"✅ 產生結構跌破 (BOS)\n\n"
                       f"🎯 **掛限價單 (0.618 Golden Zone)**：`{entry_price:.4f}`\n"
                       f"🛑 **防守停損**：`{stop_loss:.4f}`\n"
                       f"💰 **TP 停利 (2R)**：`{take_profit:.4f}`\n\n"
                       f"*(不追空！請直接掛限價單等待價格反彈)*")
                send_telegram_message(msg)
                time.sleep(1)
                
        except Exception as e:
            pass
            
if __name__ == '__main__':
    main()
