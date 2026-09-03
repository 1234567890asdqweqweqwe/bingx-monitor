import ccxt
import pandas as pd
import pandas_ta as ta
import requests
import time
from datetime import datetime

# ==========================================
# ⚙️ 請填入你的 Telegram 機器人設定
# ==========================================
TELEGRAM_BOT_TOKEN = "你的BOT_TOKEN"
TELEGRAM_CHAT_ID = "你的CHAT_ID"

exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram 發送失敗: {e}")

def fetch_ohlcv(symbol, limit=200):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=limit)
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except:
        return pd.DataFrame()

def scan_and_alert():
    print("🤖 Telegram 智慧盯盤機器人已啟動 (前 10 大主流幣 + BTC 濾網模式)...")
    sent_signals = set() # 防止重複推播同一根 K 線的訊號

    while True:
        try:
            # 1. 取得 BTC 大盤趨勢
            df_btc = fetch_ohlcv('BTC-USDT', 250)
            if df_btc.empty: df_btc = fetch_ohlcv('BTC/USDT', 250)
            
            btc_trend = 0
            if not df_btc.empty:
                df_btc['ema200'] = df_btc['close'].ewm(span=200, adjust=False).mean()
                df_btc['ema50'] = df_btc['close'].ewm(span=50, adjust=False).mean()
                c_close, c_e200, c_e50 = df_btc['close'].iloc[-1], df_btc['ema200'].iloc[-1], df_btc['ema50'].iloc[-1]
                if c_close > c_e200 and c_e50 > c_e200: btc_trend = 1
                elif c_close < c_e200 and c_e50 < c_e200: btc_trend = -1

            # 2. 抓取前 10 大強勢山寨幣
            tickers = exchange.fetch_tickers()
            blacklist = ['GOLD', 'SILVER', 'XAU', 'XAG', 'WTI', 'BRENT', 'OIL', 'DXY', 'BTC', 'ETH', 'USDT', 'USDC']
            symbol_vol = []
            for sym, data in tickers.items():
                vol = data.get('quoteVolume', 0)
                if sym.endswith(':USDT') and vol > 10000000:
                    base = sym.split('/')[0].split('-')[0].split(':')[0]
                    if base not in blacklist and len(base) <= 8:
                        symbol_vol.append({'symbol': sym, 'volume': vol})
            
            top10_symbols = [item['symbol'] for item in sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:10]]
            
            for sym in top10_symbols:
                df = fetch_ohlcv(sym, 250)
                if len(df) < 200: continue
                
                df.ta.macd(fast=12, slow=26, signal=9, append=True)
                df.ta.adx(length=14, append=True)
                df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
                df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
                
                i = len(df) - 1
                current = df.iloc[i]
                timestamp = int(current['timestamp'])
                
                macd_line = df['MACD_12_26_9'].iloc[i-1]
                signal_line = df['MACDs_12_26_9'].iloc[i-1]
                adx_val = df['ADX_14'].iloc[i-1]
                
                trend_up = current['close'] > current['ema200'] and current['ema50'] > current['ema200']
                trend_down = current['close'] < current['ema200'] and current['ema50'] < current['ema200']
                bos_bull = df['close'].iloc[i-1] > df['high'].iloc[i-10:i-2].max()
                bos_bear = df['close'].iloc[i-1] < df['low'].iloc[i-10:i-2].min()

                # 檢查是否發送過
                signal_key = f"{sym}_{timestamp}"
                if signal_key in sent_signals: continue

                if adx_val > 25:
                    if macd_line > signal_line and bos_bull and trend_up and btc_trend == 1:
                        entry = current['close']
                        sl = df['low'].iloc[i-5:i-1].min() * 0.995
                        risk = entry - sl
                        if risk > 0 and 0.01 <= (risk / entry) <= 0.05:
                            tp1 = entry + risk
                            tp2 = entry + (2.0 * risk)
                            msg = (
                                f"🟢 **【SMC 實盤多單訊號】**\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"📌 標的: `{sym.split('/')[0]}`\n"
                                f"📍 進場價 (Entry): `{entry:.4f}`\n"
                                f"🛑 建議停損 (SL): `{sl:.4f}`\n"
                                f"🎯 TP1 (1R保本半倉): `{tp1:.4f}`\n"
                                f"🎯 TP2 (2R完全指名): `{tp2:.4f}`\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"⏰ 時間: {datetime.utcnow().strftime('%m-%d %H:%M')} UTC"
                            )
                            send_telegram_message(msg)
                            sent_signals.add(signal_key)

                    elif macd_line < signal_line and bos_bear and trend_down and btc_trend == -1:
                        entry = current['close']
                        sl = df['high'].iloc[i-5:i-1].max() * 1.005
                        risk = sl - entry
                        if risk > 0 and 0.01 <= (risk / entry) <= 0.05:
                            tp1 = entry - risk
                            tp2 = entry - (2.0 * risk)
                            msg = (
                                f"🔴 **【SMC 實盤空單訊號】**\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"📌 標的: `{sym.split('/')[0]}`\n"
                                f"📍 進場價 (Entry): `{entry:.4f}`\n"
                                f"🛑 建議停損 (SL): `{sl:.4f}`\n"
                                f"🎯 TP1 (1R保本半倉): `{tp1:.4f}`\n"
                                f"🎯 TP2 (2R完全指名): `{tp2:.4f}`\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"⏰ 時間: {datetime.utcnow().strftime('%m-%d %H:%M')} UTC"
                            )
                            send_telegram_message(msg)
                            sent_signals.add(signal_key)

        except Exception as e:
            print(f"盯盤主迴圈發生錯誤: {e}")
        
        # 每小時檢查一次 1H K 線是否收盤更新
        time.sleep(3600)

if __name__ == '__main__':
    scan_and_alert()
