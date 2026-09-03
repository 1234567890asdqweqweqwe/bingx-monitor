import ccxt, requests, os, time
import pandas as pd, pandas_ta as ta
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

def send_telegram_message(message):
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                  json={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"})

def fmt_p(p):
    if pd.isna(p) or p is None: return "0"
    if p < 0.0001: return f"{p:.8f}"
    elif p < 1: return f"{p:.6f}"
    else: return f"{p:.4f}"

def main():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 啟動【1H 狙擊手級】掃描...")
    
    try:
        tickers = exchange.fetch_tickers()
        symbol_vol = [{'symbol': s, 'volume': d.get('quoteVolume', 0)} for s, d in tickers.items() if s.endswith(':USDT')]
    except: return

    blacklist = [
        'GOLD', 'SILVER', 'XAU', 'XAG', 'WTI', 'BRENT', 'OIL', 'DXY', 
        'NVDA', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'COIN', 'BABA', 'MSTR',
        'SP500', 'NDX', 'DJI', 'NQ', 'US30', 'BTC', 'ETH',
        'XAUT', 'PAXG', 'USDC', 'FDUSD', 'TUSD', 'USDD', 'EURT', 'BUSD'
    ]

    filtered_vol = []
    for item in symbol_vol:
        base = item['symbol'].split('/')[0].split('-')[0].split(':')[0]
        if base in blacklist or 'NCSK' in base or 'MSTR' in base: continue
        if len(base) > 8 and not base.startswith('100'): continue
        if item['volume'] < 10000000: continue
        filtered_vol.append(item)

    top_50 = sorted(filtered_vol, key=lambda x: x['volume'], reverse=True)[:50]

    for item in top_50:
        sym = item['symbol']
        try:
            df_1h = pd.DataFrame(exchange.fetch_ohlcv(sym, '1h', limit=150), columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_1h.ta.macd(fast=12, slow=26, signal=9, append=True)
            df_1h.ta.adx(length=14, append=True)
            df_1h['ema200'] = df_1h['close'].ewm(span=200, adjust=False).mean()
            df_1h['ema50'] = df_1h['close'].ewm(span=50, adjust=False).mean()

            c_now = df_1h['close'].iloc[-1]
            macd_line = df_1h['MACD_12_26_9'].iloc[-2]
            signal_line = df_1h['MACDs_12_26_9'].iloc[-2]
            adx_val = df_1h['ADX_14'].iloc[-2]
            
            trend_up = c_now > df_1h['ema200'].iloc[-1] and df_1h['ema50'].iloc[-1] > df_1h['ema200'].iloc[-1]
            trend_down = c_now < df_1h['ema200'].iloc[-1] and df_1h['ema50'].iloc[-1] < df_1h['ema200'].iloc[-1]
            
            bos_bull = df_1h['close'].iloc[-2] > df_1h['high'].iloc[-11:-3].max()
            bos_bear = df_1h['close'].iloc[-2] < df_1h['low'].iloc[-11:-3].min()

            if adx_val > 25:
                if macd_line > signal_line and bos_bull and trend_up:
                    sl = df_1h['low'].iloc[-6:-2].min() * 0.995
                    risk = c_now - sl
                    if risk > 0 and 0.01 <= (risk / c_now) <= 0.05:
                        tp1 = c_now + risk
                        tp2 = c_now + (2.0 * risk)
                        msg = (f"💎 **【山寨幣 1H 狙擊：順風起漲】** 💎\n"
                               f"🪙 `{sym}` | 🟢 **強勢做多**\n"
                               f"🎯 **推薦進場**：`{fmt_p(c_now)}`\n"
                               f"🛑 **防守停損**：`{fmt_p(sl)}`\n\n"
                               f"💰 **保守 (1R)**：`{fmt_p(tp1)}` *(平倉一半)*\n"
                               f"💰 **標準 (2R)**：`{fmt_p(tp2)}`")
                        send_telegram_message(msg)
                        time.sleep(1)

                elif macd_line < signal_line and bos_bear and trend_down:
                    sl = df_1h['high'].iloc[-6:-2].max() * 1.005
                    risk = sl - c_now
                    if risk > 0 and 0.01 <= (risk / c_now) <= 0.05:
                        tp1 = c_now - risk
                        tp2 = c_now - (2.0 * risk)
                        msg = (f"💎 **【山寨幣 1H 狙擊：順風起跌】** 💎\n"
                               f"🪙 `{sym}` | 🔴 **強勢做空**\n"
                               f"🎯 **推薦進場**：`{fmt_p(c_now)}`\n"
                               f"🛑 **防守停損**：`{fmt_p(sl)}`\n\n"
                               f"💰 **保守 (1R)**：`{fmt_p(tp1)}` *(平倉一半)*\n"
                               f"💰 **標準 (2R)**：`{fmt_p(tp2)}`")
                        send_telegram_message(msg)
                        time.sleep(1)
        except: pass

if __name__ == '__main__':
    main()
