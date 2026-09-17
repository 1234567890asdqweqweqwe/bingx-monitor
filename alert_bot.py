import ccxt
import pandas as pd
from ta.trend import MACD, ADXIndicator 
import telebot
from datetime import datetime

# ==========================================
# ⚙️ Telegram 機器人設定
# ==========================================
TELEGRAM_BOT_TOKEN = "7749949229:AAFbtmZvshpWbONAh3wfHzxM8gy2wansY5A"
TELEGRAM_CHAT_ID = "5790520659"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

# 💡 初始本金。若未來要加碼，直接在此修改後更新到 GitHub 即可
user_capital = 100.0  

def fetch_ohlcv(symbol, limit=250):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=limit)
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except:
        return pd.DataFrame()

def run_market_scan():
    print(f"🤖 GitHub Actions 排程掃描已啟動！目前時間: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    try:
        # 1. 取得 BTC 大盤濾網
        df_btc = fetch_ohlcv('BTC-USDT', 250)
        if df_btc.empty: df_btc = fetch_ohlcv('BTC/USDT', 250)
        
        btc_trend = 0
        if not df_btc.empty:
            df_btc['ema200'] = df_btc['close'].ewm(span=200, adjust=False).mean()
            df_btc['ema50'] = df_btc['close'].ewm(span=50, adjust=False).mean()
            c_close = df_btc['close'].iloc[-1]
            c_e200 = df_btc['ema200'].iloc[-1]
            c_e50 = df_btc['ema50'].iloc[-1]
            
            if c_close > c_e200 and c_e50 > c_e200: btc_trend = 1
            elif c_close < c_e200 and c_e50 < c_e200: btc_trend = -1

        # 2. 動態抓取並嚴格過濾可交易的漲幅 Top 10
        try: tickers = exchange.fetch_tickers()
        except: tickers = {}
        
        blacklist = ['GOLD', 'SILVER', 'XAU', 'XAG', 'WTI', 'BRENT', 'OIL', 'DXY', 'USDT', 'USDC', 'FDUSD', 'TUSD', 'USDD']
        symbol_change = []
        
        for sym, data in tickers.items():
            info = data.get('info', {})
            is_trading = True
            if isinstance(info, dict):
                status_val = info.get('status', 'trading')
                if status_val not in ['trading', '1', True]: 
                    is_trading = False

            vol = data.get('quoteVolume', 0)
            pct_change = data.get('percentage', 0)
            if pct_change is None: pct_change = 0
                
            if is_trading and sym.endswith(':USDT') and vol > 5000000:
                base = sym.split('/')[0].split('-')[0].split(':')[0]
                if base not in blacklist and len(base) <= 10:
                    symbol_change.append({'symbol': sym, 'change': pct_change})
        
        sorted_candidates = sorted(symbol_change, key=lambda x: x['change'], reverse=True)
        
        top10_symbols = []
        for item in sorted_candidates:
            if len(top10_symbols) >= 10: break
            sym = item['symbol']
            df_test = fetch_ohlcv(sym, 200)
            if len(df_test) >= 200:
                top10_symbols.append(sym)

        signals_found = 0

        # 3. 逐一計算指標與發送訊號
        for sym in top10_symbols:
            df = fetch_ohlcv(sym, 250)
            if len(df) < 200: continue
            
            macd_ind = MACD(close=df['close'], window_slow=26, window_fast=12, window_sign=9)
            df['MACD_line'] = macd_ind.macd()
            df['MACD_signal'] = macd_ind.macd_signal()
            
            adx_ind = ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14)
            df['ADX'] = adx_ind.adx()
            
            df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
            df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
            
            i = len(df) - 1
            current = df.iloc[i]
            
            macd_line = df['MACD_line'].iloc[i-1]
            signal_line = df['MACD_signal'].iloc[i-1]
            adx_val = df['ADX'].iloc[i-1]
            
            trend_up = current['close'] > current['ema200'] and current['ema50'] > current['ema200']
            trend_down = current['close'] < current['ema200'] and current['ema50'] < current['ema200']
            
            # SMC 局部破壞結構 (BOS)
            bos_bull = df['close'].iloc[i-1] > df['high'].iloc[i-10:i-2].max()
            bos_bear = df['close'].iloc[i-1] < df['low'].iloc[i-10:i-2].min()

            # ==========================================
            # 🛡️ 🚀 核心新增：SNR 支撐壓力位分析系統
            # ==========================================
            # 計算過去 50 小時的宏觀天花板(壓力)與地板(支撐)
            res_50 = df['high'].iloc[i-50:i-1].max()
            sup_50 = df['low'].iloc[i-50:i-1].min()
            
            # 多頭 SNR 條件：(1) 強勢突破天花板，(2) 買在接近地板反彈處 (3%內)
            long_snr_breakout = current['close'] > res_50
            long_snr_bounce = (current['close'] - sup_50) / sup_50 <= 0.03
            long_snr_valid = long_snr_breakout or long_snr_bounce

            # 空頭 SNR 條件：(1) 暴跌摜破地板，(2) 在天花板附近遇阻力 (3%內)
            short_snr_breakout = current['close'] < sup_50
            short_snr_bounce = (res_50 - current['close']) / current['close'] <= 0.03
            short_snr_valid = short_snr_breakout or short_snr_bounce
            # ==========================================

            # 智慧資金控管計算 (小於100U保底10U，大於100U複利10%)
            risk_amount = (user_capital * 0.10) if user_capital > 100.0 else 10.0

            # 綜合過濾條件：強動能 (ADX>25) + SMC結構突破 + SNR關鍵位確認
            if adx_val > 25: 
                # 🟢 多單進場 (10% 停損 / 20% 停利)
                if macd_line > signal_line and bos_bull and trend_up and btc_trend == 1 and long_snr_valid:
                    entry = current['close']
                    sl = entry * 0.90
                    tp1 = entry * 1.10
                    tp2 = entry * 1.20 
                    
                    snr_type = "🚀 突破 50h 天花板" if long_snr_breakout else "🛡️ 50h 支撐位精準反彈"

                    msg = (
                        f"🟢 **【SMC + SNR 波段多單訊號】**\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"📌 標的: `{sym.split('/')[0].split('-')[0]}`\n"
                        f"🔍 觸發型態: {snr_type}\n"
                        f"📍 進場價 (Entry): `{entry:.4f}`\n"
                        f"🛑 建議停損 (SL): `{sl:.4f}` (-10%)\n"
                        f"🎯 TP1 (1R保本半倉): `{tp1:.4f}` (+10%)\n"
                        f"🎯 TP2 (2R完全停利): `{tp2:.4f}` (+20%)\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💳 當前設定資金: `{user_capital:.2f}U`\n"
                        f"⚠️ 單筆風控金額 (10%): `{risk_amount:.2f}U`\n"
                        f"⏰ 時間: {datetime.utcnow().strftime('%m-%d %H:%M')} UTC"
                    )
                    bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode='Markdown')
                    signals_found += 1
                    print(f"✅ 已發送 {sym} 多單訊號 ({snr_type})")

                # 🔴 空單進場 (10% 停損 / 20% 停利)
                elif macd_line < signal_line and bos_bear and trend_down and btc_trend == -1 and short_snr_valid:
                    entry = current['close']
                    sl = entry * 1.10
                    tp1 = entry * 0.90
                    tp2 = entry * 0.80 
                    
                    snr_type = "📉 跌破 50h 地板" if short_snr_breakout else "🧱 50h 壓力位遇阻回落"

                    msg = (
                        f"🔴 **【SMC + SNR 波段空單訊號】**\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"📌 標的: `{sym.split('/')[0].split('-')[0]}`\n"
                        f"🔍 觸發型態: {snr_type}\n"
                        f"📍 進場價 (Entry): `{entry:.4f}`\n"
                        f"🛑 建議停損 (SL): `{sl:.4f}` (-10%)\n"
                        f"🎯 TP1 (1R保本半倉): `{tp1:.4f}` (-10%)\n"
                        f"🎯 TP2 (2R完全停利): `{tp2:.4f}` (-20%)\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"💳 當前設定資金: `{user_capital:.2f}U`\n"
                        f"⚠️ 單筆風控金額 (10%): `{risk_amount:.2f}U`\n"
                        f"⏰ 時間: {datetime.utcnow().strftime('%m-%d %H:%M')} UTC"
                    )
                    bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode='Markdown')
                    signals_found += 1
                    print(f"✅ 已發送 {sym} 空單訊號 ({snr_type})")

        print(f"🏁 掃描完成！本次共觸發 {signals_found} 個訊號。程式將自動關閉等待下次排程。")

    except Exception as e:
        print(f"❌ 掃描過程發生錯誤: {e}")

if __name__ == '__main__':
    run_market_scan()
