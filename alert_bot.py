import ccxt
import requests
import os
import time
import pandas as pd
import pandas_ta as ta
from datetime import datetime

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"})

def main():
    exchange = ccxt.bingx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] 啟動【傳統共振 + SMC 缺口】雙軌掃描 (純加密貨幣版)...")
    
    try:
        tickers = exchange.fetch_tickers()
        symbol_vol = [{'symbol': sym, 'volume': data['quoteVolume']} 
                      for sym, data in tickers.items() if sym.endswith(':USDT') and data.get('quoteVolume')]
        top_50 = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:50]
    except Exception as e:
        print(f"取得行情失敗: {e}")
        return

    # 建立美股、原物料、指數黑名單
    blacklist = ['NVDA', 'TSLA', 'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'COIN', 'SP500', 'NDX', 'DJI', 'GOLD', 'SILVER', 'NQ', 'BABA']

    for item in top_50:
        sym = item['symbol']
        
        base_coin = sym.split('/')[0].split('-')[0].split(':')[0]
        if base_coin in blacklist:
            continue
            
        try:
            ohlcv = exchange.fetch_ohlcv(sym, '1h', limit=250)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            if len(df) >= 200:
                current_close = df['close'].iloc[-1]
                current_vol = df['volume'].iloc[-1]
                
                # --- 1. 計算技術指標 ---
                df.ta.ema(length=50, append=True)
                df.ta.ema(length=200, append=True)
                df.ta.rsi(length=14, append=True)
                macd = df.ta.macd(fast=12, slow=26, signal=9)
                bbands = df.ta.bbands(length=20, std=2)
                df.ta.atr(length=14, append=True)
                
                ema50 = df['EMA_50'].iloc[-1]
                ema200 = df['EMA_200'].iloc[-1]
                rsi = df['RSI_14'].iloc[-1]
                macd_line = macd.iloc[-1, 0]
                signal_line = macd.iloc[-1, 2]
                lower_band = bbands.iloc[-1, 0]
                upper_band = bbands.iloc[-1, 2]
                vol_ma20 = df['volume'].rolling(20).mean().iloc[-1]
                atr = df['ATRr_14'].iloc[-1]
                
                # --- 2. 傳統多空共振 ---
                bull_reasons = []
                
                if ema50 > ema200: bull_reasons.append("📈 趨勢：EMA 50 > 200")
                if macd_line > signal_line: bull_reasons.append("⚡ 動能：MACD 多頭")
                if rsi < 50: bull_reasons.append("📉 震盪：RSI 具備上漲空間")
                if current_close <= lower_band * 1.02: bull_reasons.append("🛡️ 支撐：回踩布林下軌")
                if current_vol > vol_ma20 * 1.5 and df['close'].iloc[-1] > df['open'].iloc[-1]: 
                    bull_reasons.append("🔥 成交量：爆量買盤")
                
                is_trad_bull = len(bull_reasons) >= 3
                
                # --- 3. SMC 缺口 (FVG) ---
                fvg_bull = (df['high'].iloc[-4] < df['low'].iloc[-2]) and (df['close'].iloc[-3] > df['open'].iloc[-3])
                
                if fvg_bull:
                    fvg_gap_top = df['low'].iloc[-2]
                    fvg_gap_bottom = df['high'].iloc[-4]

                # ==========================
                # 終極判斷與發送通知
                # ==========================
                
                # 【狀況 A】：雙重確認 (連發 3 次)
                if is_trad_bull and fvg_bull:
                    msg = (f"🚨🚨 **【終極多頭信號：雙劍合璧】** 🚨🚨\n"
                           f"🪙 幣種：`{sym}`\n"
                           f"⚠️ 注意：傳統技術面與 SMC 同時看漲！\n\n"
                           f"✅ **傳統共振 ({len(bull_reasons)}/5)**\n" + "\n".join(bull_reasons) + "\n\n"
                           f"✅ **SMC 發現買方缺口 (FVG)**\n"
                           f"真空區間：`{fvg_gap_bottom:.4f}` ~ `{fvg_gap_top:.4f}`\n\n"
                           f"🎯 **建議進場 (掛單買入)**：`{fvg_gap_top:.4f}`\n"
                           f"🛑 **建議停損 (跌破缺口)**：`{fvg_gap_bottom:.4f}`\n"
                           f"💰 **建議賣出 (停利目標)**：`{fvg_gap_top + (atr*3):.4f}`")
                    for _ in range(3):
                        send_telegram_message(msg)
                        time.sleep(0.5)
                    continue

                # 【狀況 B】：純傳統多頭信號
                elif is_trad_bull:
                    msg = (f"🟢 **【傳統多頭共振】**\n"
                           f"🪙 幣種：`{sym}`\n"
                           f"📊 達成指標：{len(bull_reasons)}/5 共振\n\n"
                           f"**【入局理由】**\n" + "\n".join(bull_reasons) + "\n\n"
                           f"🎯 **建議進場 (市價)**：`{current_close}`\n"
                           f"🛑 **建議停損**：`{current_close - (atr*1.5):.4f}`\n"
                           f"💰 **建議賣出 (停利)**：`{current_close + (atr*3):.4f}`")
                    send_telegram_message(msg)
                
                # 【狀況 C】：純 SMC 多頭信號 (新增賣出與停損價)
                elif fvg_bull:
                    msg = (f"🐋 **【SMC 主力足跡 (多)】**\n"
                           f"🪙 幣種：`{sym}`\n"
                           f"發現主力暴拉留下的 **FVG (合理價值缺口)**！\n"
                           f"此區間代表機構強烈買盤，極高機率反彈。\n\n"
                           f"🎯 **建議進場 (掛單買入)**：`{fvg_gap_top:.4f}`\n"
                           f"🛑 **建議停損 (跌破缺口)**：`{fvg_gap_bottom:.4f}`\n"
                           f"💰 **建議賣出 (停利目標)**：`{fvg_gap_top + (atr*3):.4f}`\n\n"
                           f"*(策略：絕對不追高，請於進場價設定限價單等待價格回落)*")
                    send_telegram_message(msg)
                
        except Exception as e:
            pass
        
        time.sleep(1)
        
if __name__ == '__main__':
    main()
