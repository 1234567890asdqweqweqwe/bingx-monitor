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
    print(f"[{now}] 啟動【傳統共振 + SMC 缺口】雙軌掃描...")
    
    try:
        tickers = exchange.fetch_tickers()
        symbol_vol = [{'symbol': sym, 'volume': data['quoteVolume']} 
                      for sym, data in tickers.items() if sym.endswith(':USDT') and data.get('quoteVolume')]
        top_50 = sorted(symbol_vol, key=lambda x: x['volume'], reverse=True)[:50]
    except Exception as e:
        print(f"取得行情失敗: {e}")
        return

    for item in top_50:
        sym = item['symbol']
        try:
            ohlcv = exchange.fetch_ohlcv(sym, '1h', limit=250)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            if len(df) >= 200:
                current_close = df['close'].iloc[-1]
                current_vol = df['volume'].iloc[-1]
                
                # --- 1. 計算傳統技術指標 ---
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
                
                # --- 2. 評估傳統多空共振 ---
                bull_reasons = []
                bear_reasons = []
                
                if ema50 > ema200: bull_reasons.append("📈 趨勢：EMA 50 > 200")
                else: bear_reasons.append("📉 趨勢：EMA 50 < 200")
                
                if macd_line > signal_line: bull_reasons.append("⚡ 動能：MACD 多頭")
                else: bear_reasons.append("⚡ 動能：MACD 空頭")
                
                if rsi < 50: bull_reasons.append("📉 震盪：RSI 具備上漲空間")
                if rsi > 60: bear_reasons.append("📈 震盪：RSI 高檔超買風險")
                
                if current_close <= lower_band * 1.02: bull_reasons.append("🛡️ 支撐：回踩布林下軌")
                if current_close >= upper_band * 0.98: bear_reasons.append("🧱 壓力：觸及布林上軌")
                
                if current_vol > vol_ma20 * 1.5:
                    if df['close'].iloc[-1] > df['open'].iloc[-1]: bull_reasons.append("🔥 成交量：爆量買盤")
                    else: bear_reasons.append("🔥 成交量：爆量砸盤")
                
                # 判定狀態
                is_trad_bull = len(bull_reasons) >= 3
                is_trad_bear = len(bear_reasons) >= 3
                
                # --- 3. 評估 SMC 缺口 (FVG) ---
                # 利用近 3 根已完成的 K 線來尋找缺口 (索引 -4, -3, -2)
                # 買方缺口：第一根的高點 < 第三根的低點
                fvg_bull = (df['high'].iloc[-4] < df['low'].iloc[-2]) and (df['close'].iloc[-3] > df['open'].iloc[-3])
                # 賣方缺口：第一根的低點 > 第三根的高點
                fvg_bear = (df['low'].iloc[-4] > df['high'].iloc[-2]) and (df['close'].iloc[-3] < df['open'].iloc[-3])
                
                if fvg_bull:
                    fvg_gap_top = df['low'].iloc[-2]
                    fvg_gap_bottom = df['high'].iloc[-4]
                if fvg_bear:
                    fvg_gap_top = df['low'].iloc[-4]
                    fvg_gap_bottom = df['high'].iloc[-2]

                # ==========================
                # 終極判斷與發送通知
                # ==========================
                
                # 【狀況 A】：雙重確認 (超級信號) -> 連發 3 次
                if is_trad_bull and fvg_bull:
                    msg = (f"🚨🚨 **【終極多頭信號：雙劍合璧】** 🚨🚨\n"
                           f"🪙 幣種：`{sym}`\n"
                           f"⚠️ 注意：傳統技術面與 SMC 主力資金同時看漲！\n\n"
                           f"✅ **傳統共振 ({len(bull_reasons)}/5)**\n" + "\n".join(bull_reasons) + "\n\n"
                           f"✅ **SMC 發現買方 FVG 缺口**\n"
                           f"主力在 `{fvg_gap_bottom:.4f}` ~ `{fvg_gap_top:.4f}` 留下真空區，這是最強支撐！\n\n"
                           f"🎯 **建議進場**：接近缺口上緣 `{fvg_gap_top:.4f}`\n"
                           f"🛑 **停損 (跌破缺口)**：`{fvg_gap_bottom:.4f}`\n"
                           f"💰 **停利**：`{fvg_gap_top + (atr*3):.4f}`")
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
                           f"🎯 **建議進場**：`{current_close}`\n"
                           f"🛑 **建議停損**：`{current_close - (atr*1.5):.4f}`\n"
                           f"💰 **建議停利**：`{current_close + (atr*3):.4f}`")
                    send_telegram_message(msg)
                
                # 【狀況 C】：純 SMC 多頭信號
                elif fvg_bull:
                    msg = (f"🐋 **【SMC 主力足跡 (多)】**\n"
                           f"🪙 幣種：`{sym}`\n"
                           f"發現主力暴拉留下的 **FVG (合理價值缺口)**！\n"
                           f"真空區間：`{fvg_gap_bottom:.4f}` ~ `{fvg_gap_top:.4f}`\n\n"
                           f"🎯 **建議策略**：不要追高，掛限價單在缺口上緣 `{fvg_gap_top:.4f}` 等待價格回補。")
                    send_telegram_message(msg)

                # (做空的防守邏輯同理，為保持程式碼簡潔，重點呈現超級信號邏輯)
                
        except Exception as e:
            pass
        
        time.sleep(1)
        
if __name__ == '__main__':
    main()
