import ccxt
import pandas as pd
from ta.trend import MACD, ADXIndicator 
import telebot
import threading
import time
from datetime import datetime

# ==========================================
# ⚙️ Telegram 機器人設定 (已填入專屬金鑰)
# ==========================================
TELEGRAM_BOT_TOKEN = "7749949229:AAFbtmZvshpWbONAh3wfHzxM8gy2wansY5A"
TELEGRAM_CHAT_ID = "5790520659"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

user_capital = 100.0

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "🤖 **歡迎使用 SMC 實盤智慧盯盤機器人！**\n\n"
        "我會在背景 24 小時幫你監控【前 10 大強勢幣 + BTC 大盤】，並使用黃金 2R 參數為你發送高勝率訊號。\n\n"
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
    risk_amount = user_capital * 0.02
    margin_amount = user_capital * 0.20
    status_msg = (
        f"📊 **【實盤複利狀態】**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💳 當前總資金: `{user_capital:.2f} USDT`\n"
        f"⚠️ 單筆最大風險 (2%): `{risk_amount:.2f} USDT`\n"
        f"💰 建議保證金 (20%): `{margin_amount:.2f} USDT` (配合10x槓桿)\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )
    bot.reply_to(message, status_msg, parse_mode='Markdown')

@bot.message_handler(commands=['test'])
def test_signal(message):
    bot.reply_to(message, "✅ 測試成功！機器人推播功能 100% 正常，雷達掃描引擎運作中👀")

def fetch_ohlcv(symbol, limit=200):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=limit)
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except:
        return pd.DataFrame()

def market_scanner_loop():
    print("🤖 背景掃描引擎已啟動 (全市場 Top 10 + 黃金參數)...")
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

            # 2. 動態篩選 Top 10 強勢幣
            try: tickers = exchange.fetch_tickers()
            except: tickers = {}
            
            blacklist = ['GOLD', 'SILVER', 'XAU', 'XAG', 'WTI', 'BRENT', 'OIL', 'DXY', 'BTC', 'ETH', 'USDT', 'USDC']
            symbol_vol = []
            for sym, data in tickers.items():
                vol = data.get('quoteVolume', 0)
                if sym.endswith(':USDT') and vol > 10000000:
                    base = sym.split('/')[0].split('-')[0].split(':')[0]
                    if base not in blacklist and len(base) <= 8:
                        symbol_vol.append({'symbol': sym, 'volume': vol})
            
            top10_symbols = [item['symbol'] for item in sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:10]]
            
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

                margin_amount = user_capital * 0.20  
                risk_amount = user_capital * 0.02    

                # 🏆 核心：套用回測驗證的黃金參數
                if adx_val > 25: # 參數 1: 嚴格趨勢過濾
                    # 🟢 多單進場
                    if macd_line > signal_line and bos_bull and trend_up and btc_trend == 1:
                        entry = current['close']
                        sl = df['low'].iloc[i-5:i-1].min() * 0.995 # 參數 2: 0.5% 緊湊防守
                        risk = entry - sl
                        if risk > 0 and 0.01 <= (risk / entry) <= 0.05:
                            tp1 = entry + risk
                            tp2 = entry + (2.0 * risk) # 參數 3: 黃金 2R 停利
                            msg = (
                                f"🟢 **【SMC 實盤多單訊號】**\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"📌 標的: `{sym.split('/')[0]}`\n"
                                f"📍 進場價 (Entry): `{entry:.4f}`\n"
                                f"🛑 建議停損 (SL): `{sl:.4f}`\n"
                                f"🎯 TP1 (1R保本半倉): `{tp1:.4f}`\n"
                                f"🎯 TP2 (2R完全停利): `{tp2:.4f}`\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"💳 當前資金: `{user_capital:.2f}U`\n"
                                f"💰 **建議下單保證金 (20%): `{margin_amount:.2f}U` (10x)**\n"
                                f"⚠️ 單筆風控金額 (2%): `{risk_amount:.2f}U`\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"⏰ 時間: {datetime.utcnow().strftime('%m-%d %H:%M')} UTC"
                            )
                            bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode='Markdown')
                            sent_signals.add(signal_key)

                    # 🔴 空單進場
                    elif macd_line < signal_line and bos_bear and trend_down and btc_trend == -1:
                        entry = current['close']
                        sl = df['high'].iloc[i-5:i-1].max() * 1.005 # 參數 2: 0.5% 緊湊防守
                        risk = sl - entry
                        if risk > 0 and 0.01 <= (risk / entry) <= 0.05:
                            tp1 = entry - risk
                            tp2 = entry - (2.0 * risk) # 參數 3: 黃金 2R 停利
                            msg = (
                                f"🔴 **【SMC 實盤空單訊號】**\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"📌 標的: `{sym.split('/')[0]}`\n"
                                f"📍 進場價 (Entry): `{entry:.4f}`\n"
                                f"🛑 建議停損 (SL): `{sl:.4f}`\n"
                                f"🎯 TP1 (1R保本半倉): `{tp1:.4f}`\n"
                                f"🎯 TP2 (2R完全停利): `{tp2:.4f}`\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"💳 當前資金: `{user_capital:.2f}U`\n"
                                f"💰 **建議下單保證金 (20%): `{margin_amount:.2f}U` (10x)**\n"
                                f"⚠️ 單筆風控金額 (2%): `{risk_amount:.2f}U`\n"
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
        startup_msg = "🚀 **系統啟動成功！**\n機器人已套用【黃金 2R 參數】，開始在背景為您監控全市場前 10 大強勢幣。輸入 `/help` 查看指令。"
        bot.send_message(TELEGRAM_CHAT_ID, startup_msg, parse_mode='Markdown')
        print("✅ 開機通知已發送至 Telegram。")
    except Exception as e:
        print(f"❌ 傳送開機通知失敗，錯誤原因: {e}")

    scanner_thread = threading.Thread(target=market_scanner_loop, daemon=True)
    scanner_thread.start()
    
    print("🚀 Telegram 互動機器人已開始接聽指令...")
    bot.infinity_polling()
