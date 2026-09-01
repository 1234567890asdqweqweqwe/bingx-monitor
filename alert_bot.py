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
                
                # --- 2. SMC 缺口 (FVG) 判斷 ---
                # 買方缺口 (看漲做多)
                fvg_bull = (df['high'].iloc[-4] < df['low'].iloc[-2]) and (df['close'].iloc[-3] > df['open'].iloc[-3])
                # 賣方缺口 (看跌做空)
                fvg_bear = (df['low'].iloc[-4] > df['high'].iloc[-2]) and (df['close'].iloc[-3] < df['open'].iloc[-3])
                
                fvg_bull_gap_top = 0
                fvg_bull_gap_bottom = 0
                fvg_bear_gap_top = 0
                fvg_bear_gap_bottom = 0

                if fvg_bull:
                    fvg_bull_gap_top = df['low'].iloc[-2]
                    fvg_bull_gap_bottom = df['high'].iloc[-4]
                if fvg_bear:
                    fvg_bear_gap_top = df['low'].iloc[-4]  # 賣方缺口的上緣
                    fvg_bear_gap_bottom = df['high'].iloc[-2] # 賣方缺口的下緣

                # ==========================
                # 發送 SMC 專屬通知
                # ==========================
                
                # 【狀況 A】：SMC 建議做多
                if fvg_bull:
                    msg = (f"🐋 **【SMC 主力足跡雷達】**\n"
                           f"🪙 幣種：`{sym}`\n"
                           f"🟢 **建議方向：做多 (Long)** 🟢\n\n"
                           f"**【分析依據】**\n"
                           f"發現主力暴拉留下的 **向上 FVG 缺口**！\n"
                           f"真空區間：`{fvg_bull_gap_bottom:.4f}` ~ `{fvg_bull_gap_top:.4f}`\n\n"
                           f"🎯 **建議進場 (掛限價單做多)**：`{fvg_bull_gap_top:.4f}`\n"
                           f"🛑 **建議停損 (跌破缺口)**：`{fvg_bull_gap_bottom:.4f}`\n"
                           f"💰 **建議賣出 (停利目標)**：`{fvg_bull_gap_top + (atr*3):.4f}`\n\n"
                           f"*(絕對不追高，請於進場價設定限價買單等待價格回落)*")
                    send_telegram_message(msg)
                
                # 【狀況 B】：SMC 建議做空 (補齊做空邏輯)
                elif fvg_bear:
                    msg = (f"🐋 **【SMC 主力足跡雷達】**\n"
                           f"🪙 幣種：`{sym}`\n"
                           f"🔴 **建議方向：做空 (Short)** 🔴\n\n"
                           f"**【分析依據】**\n"
                           f"發現主力暴力砸盤留下的 **向下 FVG 缺口**！\n"
                           f"真空區間：`{fvg_bear_gap_bottom:.4f}` ~ `{fvg_bear_gap_top:.4f}`\n\n"
                           f"🎯 **建議進場 (掛限價單做空)**：`{fvg_bear_gap_bottom:.4f}`\n"
                           f"🛑 **建議停損 (突破缺口)**：`{fvg_bear_gap_top:.4f}`\n"
                           f"💰 **建議平倉 (停利目標)**：`{fvg_bear_gap_bottom - (atr*3):.4f}`\n\n"
                           f"*(絕對不追低，請於進場價設定限價空單等待價格反彈)*")
                    send_telegram_message(msg)
                
        except Exception as e:
            pass
        
        time.sleep(1)
        
if __name__ == '__main__':
    main()
