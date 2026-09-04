import ccxt
import pandas as pd
from ta.trend import MACD, ADXIndicator 
import telebot
import threading
import time
from datetime import datetime

# ==========================================
# ⚙️ Telegram 機器人設定
# ==========================================
TELEGRAM_BOT_TOKEN = "7749949229:AAFbtmZvshpWbONAh3wfHzxM8gy2wansY5A"
TELEGRAM_CHAT_ID = "5790520659"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

user_capital = 100.0

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🤖 **歡迎使用 SMC 波段實盤智慧盯盤機器人！**\n\n"
        "我會在背景 24 小時幫你監控【漲幅 Top 10 可交易強勢幣 + BTC 大盤】，並使用「10% 停損 / 20% 停利」波段參數為你發送高爆發訊號。\n\n"
        "🛠 **可用指令列表：**\n"
        "👉 `/status` - 查看當前總資金與下單建議金額\n"
        "👉 `/capital 150` - 更新你的最新總資金為 150U\n"
        "👉 `/test` - 發送一則測試訊號\n"
        "👉 `/help` - 顯示本選單"
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(commands=['capital', 'setcap'])
def update_capital(message):
    global user_capital
    try:
        parts = message.text.split()
        if len(parts) > 1:
            user_capital = float(parts[1])
            bot.reply_to(message, f"✅ 帳戶資金已成功更新為: **{user_capital} USDT**\n接下來的訊號將自動以此金額計算複利倉位！", parse_mode='Markdown')
        else:
            bot.reply_to(message, f"📌 當前設定資金: **{user_capital} USDT**\n💡 更改方式: 請輸入 `/capital 108.46`", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, "❌ 格式錯誤，請輸入純數字，例如: `/capital 108.46`", parse_mode='Markdown')

@bot.message_handler(commands=['status'])
def show_status(message):
    # 智慧複利資金邏輯：小於100U保底10U風險，大於100U則用10%
    risk_amount = user_capital * 0.10 if user_capital > 100.0 else 10.0
    margin_amount = risk_amount * 5 # 配合波段較寬的槓桿評估
    status_msg = (
        f"📊 **【波段實盤複利狀態】**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💳 當前總資金: `{user_capital:.2f} USDT`\n"
        f"⚠️ 單筆風控金額 (10%): `{risk_amount:.2f} USDT`\n"
        f"🎯 預計停損目標 (-10%): `{risk_amount:.2f} USDT`\n"
        f"🎯 預計停利目標 (+20%): `{risk_amount * 2.0:.2f} USDT`\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )
    bot.reply_to(message, status_msg, parse_mode='Markdown')

@bot.message_handler(commands=['test'])
def test_signal(message):
    bot.reply_to(message, "✅ 測試成功！波段機器人推播功能 100% 正常，雷達掃描引擎運作中👀")

def fetch_ohlcv(symbol, limit=200):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=limit)
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except:
        return pd.DataFrame()

def market_scanner_loop():
    print("🤖 背景掃描引擎已啟動 (智慧遞補漲幅 Top 10 + 10%停損/20%停利波段)...")
    sent_signals = set()

    while True:
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
            
            # 依 24h 漲幅由大到小排序
            sorted_candidates = sorted(symbol_change, key=lambda x: x['change'], reverse=True)
            
            # 智慧遞補湊滿 10 個有效幣種
            top10_symbols = []
            for item in sorted_candidates:
                if len(top10_symbols) >= 10: break
                sym = item['symbol']
                df_test = fetch_ohlcv(sym, 200)
                if len(df_test) >= 200:
                    top10_symbols.append(sym)

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
                timestamp = int(current['timestamp'])
                
                macd_line = df['MACD_line'].iloc[i-1]
                signal_line = df['MACD_signal'].iloc[i-1]
                adx_val = df['ADX'].iloc[i-1]
                
                trend_up = current['close'] > current['ema200'] and current['ema50'] > current['ema200']
                trend_down = current['close'] < current['ema200'] and current['ema50'] < current['ema200']
                bos_bull = df['close'].iloc[i-1] > df['high'].iloc[i-10:i-2].max()
                bos_bear = df['close'].iloc[i-1] < df['low'].iloc[i-10:i-2].min()

                signal_key = f"{sym}_{timestamp}"
                if signal_key in sent_signals: continue
                if len(sent_signals) > 1000: sent_signals.clear()

                # 智慧資金控管計算
                risk_amount = (user_capital * 0.10) if user_capital > 100.0 else 10.0
                margin_amount = risk_amount * 5 # 建議保證金範例

                # 🏆 核心：套用波段策略參數 (ADX > 25)
                if adx_val > 25: 
                    # 🟢 多單進場 (10% 停損 / 20% 停利)
                    if macd_line > signal_line and bos_bull and trend_up and btc_trend == 1:
                        entry = current['close']
                        sl = entry * 0.90  # 10% 停損
                        tp1 = entry * 1.10 # 10% 漲幅保本 (1R)
                        tp2 = entry * 1.20 # 20% 漲幅完利 (2R)
                        
                        msg = (
                            f"🟢 **【SMC 波段多單訊號】**\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"📌 標的: `{sym.split('/')[0].split('-')[0]}`\n"
                            f"📍 進場價 (Entry): `{entry:.4f}`\n"
                            f"🛑 建議停損 (SL): `{sl:.4f}` (-10%)\n"
                            f"🎯 TP1 (1R保本半倉): `{tp1:.4f}` (+10%)\n"
                            f"🎯 TP2 (2R完全停利): `{tp2:.4f}` (+20%)\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💳 當前資金: `{user_capital:.2f}U`\n"
                            f"⚠️ 單筆風控金額 (10%): `{risk_amount:.2f}U`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"⏰ 時間: {datetime.utcnow().strftime('%m-%d %H:%M')} UTC"
                        )
                        bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode='Markdown')
                        sent_signals.add(signal_key)

                    # 🔴 空單進場 (10% 停損 / 20% 停利)
                    elif macd_line < signal_line and bos_bear and trend_down and btc_trend == -1:
                        entry = current['close']
                        sl = entry * 1.10  # 10% 停損
                        tp1 = entry * 0.90 # 10% 跌幅保本 (1R)
                        tp2 = entry * 0.80 # 20% 跌幅完利 (2R)
                        
                        msg = (
                            f"🔴 **【SMC 波段空單訊號】**\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"📌 標的: `{sym.split('/')[0].split('-')[0]}`\n"
                            f"📍 進場價 (Entry): `{entry:.4f}`\n"
                            f"🛑 建議停損 (SL): `{sl:.4f}` (-10%)\n"
                            f"🎯 TP1 (1R保本半倉): `{tp1:.4f}` (-10%)\n"
                            f"🎯 TP2 (2R完全停利): `{tp2:.4f}` (-20%)\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"💳 當前資金: `{user_capital:.2f}U`\n"
                            f"⚠️ 單筆風控金額 (10%): `{risk_amount:.2f}U`\n"
                            f"━━━━━━━━━━━━━━━━━━━\n"
                            f"⏰ 時間: {datetime.utcnow().strftime('%m-%d %H:%M')} UTC"
                        )
                        bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode='Markdown')
                        sent_signals.add(signal_key)

        except Exception as e:
            print(f"盯盤主迴圈發生錯誤: {e}")
        
        time.sleep(3000)

if __name__ == '__main__':
    try:
        startup_msg = "🚀 **波段系統啟動成功！**\n機器人已套用【智慧遞補漲幅 Top 10 + 10%停損/20%停利 + 智能複利】，開始在背景為您監控。輸入 `/help` 查看指令。"
        bot.send_message(TELEGRAM_CHAT_ID, startup_msg, parse_mode='Markdown')
        print("✅ 開機通知已發送至 Telegram。")
    except Exception as e:
        print(f"❌ 傳送開機通知失敗，錯誤原因: {e}")

    scanner_thread = threading.Thread(target=market_scanner_loop, daemon=True)
    scanner_thread.start()
    
    print("🚀 Telegram 互動機器人已開始接聽指令...")
    bot.infinity_polling()
