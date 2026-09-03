import ccxt
import pandas as pd
import pandas_ta as ta
import telebot
import threading
import time
from datetime import datetime

# ==========================================
# ⚙️ 請填入你的 Telegram 機器人設定
# ==========================================
TELEGRAM_BOT_TOKEN = "你的BOT_TOKEN"
TELEGRAM_CHAT_ID = "你的CHAT_ID"  # 你的個人或群組 Chat ID

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

# 全域變數：追蹤你當下的總帳戶資金（預設為 100U，可隨時透過 Telegram 指令更新）
user_capital = 100.0

# --- Telegram 互動指令區 ---
@bot.message_handler(commands=['capital', 'setcap'])
def update_capital(message):
    global user_capital
    try:
        parts = message.text.split()
        if len(parts) > 1:
            user_capital = float(parts[1])
            bot.reply_to(message, f"✅ 帳戶資金已更新為: <b>{user_capital} USDT</b>\n接下來的訊號將自動以此金額計算複利倉位！", parse_mode='HTML')
        else:
            bot.reply_to(message, f"📌 當前追蹤資金: <b>{user_capital} USDT</b>\n使用方式: <code>/capital 108.46</code>", parse_mode='HTML')
    except Exception as e:
        bot.reply_to(message, "❌ 格式錯誤，請輸入數字，例如: <code>/capital 108.46</code>", parse_mode='HTML')

@bot.message_handler(commands=['status'])
def show_status(message):
    risk_amount = user_capital * 0.02
    margin_amount = user_capital * 0.20
    status_msg = (
        f"📊 <b>【實盤複利狀態】</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💳 當前總資金: <code>{user_capital:.2f} USDT</code>\n"
        f"⚠️ 單筆最大風險 (2%): <code>{risk_amount:.2f} USDT</code>\n"
        f"💰 建議保證金 (20%): <code>{margin_amount:.2f} USDT</code> (10x槓桿)\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 隨時可輸入 <code>/capital 金額</code> 來更新你的本金！"
    )
    bot.reply_to(message, status_msg, parse_mode='HTML')

def fetch_ohlcv(symbol, limit=200):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=limit)
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except:
        return pd.DataFrame()

# --- 背景掃描與自動推播執行緒 ---
def market_scanner_loop():
    print("🤖 Telegram 智慧盯盤機器人已啟動 (具備動態複利計算功能)...")
    sent_signals = set()

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

                signal_key = f"{sym}_{timestamp}"
                if signal_key in sent_signals: continue

                # 動態計算當下複利倉位大小
                margin_amount = user_capital * 0.20  # 20% 保證金
                risk_amount = user_capital * 0.02    # 2% 風險金額

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
                                f"💳 當前資金: `{user_capital:.2f}U`\n"
                                f"💰 **建議下單保證金 (20%): `{margin_amount:.2f}U` (10x)**\n"
                                f"⚠️ 單筆風控金額 (2%): `{risk_amount:.2f}U`\n"
                                f"━━━━━━━━━━━━━━━━━━━\n"
                                f"⏰ 時間: {datetime.utcnow().strftime('%m-%d %H:%M')} UTC"
                            )
                            bot.send_message(TELEGRAM_CHAT_ID, msg, parse_mode='Markdown')
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
        
        time.sleep(3600)

if __name__ == '__main__':
    # 啟動背景掃描執行緒
    scanner_thread = threading.Thread(target=market_scanner_loop, daemon=True)
    scanner_thread.start()
    
    # 啟動 Telegram 機器人監聽指令（如 /capital）
    print("🚀 Telegram 互動機器人已開始接聽指令...")
    bot.infinity_polling()
