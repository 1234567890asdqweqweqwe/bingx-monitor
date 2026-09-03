from flask import Flask, render_template_string
import ccxt
import pandas as pd
import pandas_ta as ta
import threading
import time
from datetime import datetime, timedelta

app = Flask(__name__)
exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

latest_signals = []
last_update = "尚未更新"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>SMC 實盤雷達監控中心</title>
    <meta http-equiv="refresh" content="300">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { color: #38bdf8; text-align: center; margin-bottom: 5px; }
        .subtitle { text-align: center; color: #94a3b8; margin-bottom: 30px; }
        .card { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 15px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); display: flex; justify-content: space-between; align-items: center; border-left: 6px solid #64748b; }
        .card.LONG { border-left-color: #22c55e; }
        .card.SHORT { border-left-color: #ef4444; }
        .info h3 { margin: 0 0 8px 0; font-size: 1.2rem; }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 0.85rem; }
        .badge.LONG { background: rgba(34, 197, 94, 0.2); color: #4ade80; }
        .badge.SHORT { background: rgba(239, 68, 68, 0.2); color: #f87171; }
        .details { text-align: right; font-size: 0.95rem; color: #cbd5e1; }
        .update-time { text-align: center; color: #64748b; margin-top: 20px; font-size: 0.85rem; }
    </style>
</head>
<body>
    <div class="container">
        <h1>👑 SMC 實盤雷達監控中心</h1>
        <div class="subtitle">自動掃描全市場前 10 大主流幣 ＋ BTC 大盤趨勢濾網</div>
        
        {% if signals %}
            {% for s in signals %}
            <div class="card {{ s.direction }}">
                <div class="info">
                    <h3>{{ s.symbol }} <span class="badge {{ s.direction }}">{{ s.direction }}</span></h3>
                    <div>進場價 (Entry): <b>{{ s.entry }}</b> | 建議停損 (SL): <span style="color:#f87171;">{{ s.sl }}</span></div>
                </div>
                <div class="details">
                    <div>🎯 TP1 (1R): <b style="color:#4ade80;">{{ s.tp1 }}</b></div>
                    <div>🎯 TP2 (2R): <b style="color:#38bdf8;">{{ s.tp2 }}</b></div>
                    <div style="font-size: 0.8rem; color: #94a3b8; margin-top: 4px;">時間: {{ s.time }}</div>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div style="text-align: center; padding: 60px; background: #1e293b; border-radius: 12px; color: #38bdf8; font-size: 1.4rem; font-weight: bold; letter-spacing: 1px;">
                請耐心等待進場機會吧!!!!!!!
            </div>
        {% endif %}
        
        <div class="update-time">最後掃描時間: {{ update_time }} (每 5 分鐘自動更新)</div>
    </div>
</body>
</html>
"""

def fetch_ohlcv(symbol, limit=200):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except:
        return pd.DataFrame()

def background_scanner():
    global latest_signals, last_update
    while True:
        try:
            print("🔍 網頁雷達背景掃描中...")
            df_btc = fetch_ohlcv('BTC-USDT', 250)
            if df_btc.empty: df_btc = fetch_ohlcv('BTC/USDT', 250)
            
            btc_trend = 0
            if not df_btc.empty:
                df_btc['ema200'] = df_btc['close'].ewm(span=200, adjust=False).mean()
                df_btc['ema50'] = df_btc['close'].ewm(span=50, adjust=False).mean()
                c_close, c_e200, c_e50 = df_btc['close'].iloc[-1], df_btc['ema200'].iloc[-1], df_btc['ema50'].iloc[-1]
                if c_close > c_e200 and c_e50 > c_e200: btc_trend = 1
                elif c_close < c_e200 and c_e50 < c_e200: btc_trend = -1

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
            
            found_signals = []
            for sym in top10_symbols:
                df = fetch_ohlcv(sym, 250)
                if len(df) < 200: continue
                
                df.ta.macd(fast=12, slow=26, signal=9, append=True)
                df.ta.adx(length=14, append=True)
                df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
                df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
                
                i = len(df) - 1
                current = df.iloc[i]
                macd_line = df['MACD_12_26_9'].iloc[i-1]
                signal_line = df['MACDs_12_26_9'].iloc[i-1]
                adx_val = df['ADX_14'].iloc[i-1]
                
                trend_up = current['close'] > current['ema200'] and current['ema50'] > current['ema200']
                trend_down = current['close'] < current['ema200'] and current['ema50'] < current['ema200']
                bos_bull = df['close'].iloc[i-1] > df['high'].iloc[i-10:i-2].max()
                bos_bear = df['close'].iloc[i-1] < df['low'].iloc[i-10:i-2].min()

                if adx_val > 25:
                    if macd_line > signal_line and bos_bull and trend_up and btc_trend == 1:
                        entry = current['close']
                        sl = df['low'].iloc[i-5:i-1].min() * 0.995
                        risk = entry - sl
                        if risk > 0 and 0.01 <= (risk / entry) <= 0.05:
                            found_signals.append({
                                'symbol': sym.split('/')[0], 'direction': 'LONG',
                                'entry': round(entry, 4), 'sl': round(sl, 4),
                                'tp1': round(entry + risk, 4), 'tp2': round(entry + (2.0 * risk), 4),
                                'time': datetime.utcnow().strftime('%m-%d %H:%M')
                            })
                    elif macd_line < signal_line and bos_bear and trend_down and btc_trend == -1:
                        entry = current['close']
                        sl = df['high'].iloc[i-5:i-1].max() * 1.005
                        risk = sl - entry
                        if risk > 0 and 0.01 <= (risk / entry) <= 0.05:
                            found_signals.append({
                                'symbol': sym.split('/')[0], 'direction': 'SHORT',
                                'entry': round(entry, 4), 'sl': round(sl, 4),
                                'tp1': round(entry - risk, 4), 'tp2': round(entry - (2.0 * risk), 4),
                                'time': datetime.utcnow().strftime('%m-%d %H:%M')
                            })
            
            latest_signals = found_signals
            last_update = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        except Exception as e:
            print(f"掃描發生錯誤: {e}")
        
        time.sleep(300)

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, signals=latest_signals, update_time=last_update)

if __name__ == '__main__':
    t = threading.Thread(target=background_scanner, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000)
