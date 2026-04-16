# 檔名：20150413 MACD + RSI 完整說明版.py

import requests
from datetime import datetime, timezone, timedelta

# ==========================================
# 🛠️ 第一部分：基礎工具
# ==========================================
def safe_float(val, default=0.0):
    if val is None: return default
    try: return float(str(val).replace(',', ''))
    except: return default

def calculate_ema(data, n):
    if len(data) < n: return [data[-1]] * len(data)
    res = [sum(data[:n])/n]
    alpha = 2 / (n + 1)
    full_res = [data[0]] * (n - 1) + res
    for i in range(n, len(data)):
        full_res.append(data[i] * alpha + full_res[-1] * (1 - alpha))
    return full_res

# ==========================================
# 📊 第二部分：核心量化引擎 (MACD + RSI)
# ==========================================
def perform_macd_analysis(closes, is_tw):
    if not closes or len(closes) < 35: return None
    e12 = calculate_ema(closes, 12)
    e26 = calculate_ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = calculate_ema(dif, 9)
    multiplier = 2.0 if is_tw else 1.0
    hist = [(d - a) * multiplier for d, a in zip(dif, dea)]
    return hist

def calculate_rsi(closes, period=14):
    if not closes or len(closes) < period + 1: return [50.0] * len(closes)
    
    rsi_series = [50.0] * period
    avg_gain = sum(max(0, closes[i] - closes[i-1]) for i in range(1, period+1)) / period
    avg_loss = sum(max(0, closes[i-1] - closes[i]) for i in range(1, period+1)) / period

    if avg_loss == 0: rsi_series.append(100.0)
    else: rsi_series.append(100.0 - (100.0 / (1.0 + (avg_gain / avg_loss))))

    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i-1]
        gain = max(0, diff)
        loss = max(0, -diff)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        
        if avg_loss == 0: rsi_series.append(100.0)
        else: rsi_series.append(100.0 - (100.0 / (1.0 + (avg_gain / avg_loss))))
            
    return rsi_series

def analyze_indicators_5day(closes, highs, lows, timestamps, is_tw_market):
    hist = perform_macd_analysis(closes, is_tw_market)
    rsi = calculate_rsi(closes, 14)
    if not hist or not rsi: return None
    
    report = []
    for i in range(-5, 0):
        try:
            # MACD 狀態
            m_now, m_pre = hist[i], hist[i-1]
            m_up = m_now > m_pre
            status = ("🔴紅柱" if m_now > 0 else "🟢綠柱") + ("放大" if m_up else "縮減")
            
            # RSI 狀態
            r_val = rsi[i]
            if r_val >= 80: r_status = "🔥 超買警戒"
            elif r_val <= 20: r_status = "❄️ 超賣低接"
            elif r_val >= 50: r_status = "📈 多方控盤"
            else: r_status = "📉 空方壓制"

            p_range = highs[i] - lows[i]
            pos = ((closes[i] - lows[i]) / p_range * 100) if p_range > 0 else 50
            pos_label = "強勢鎖碼" if pos > 80 else "弱勢殺尾" if pos < 20 else "區間對峙"
            
            tz_tw = timezone(timedelta(hours=8))
            dt = datetime.fromtimestamp(timestamps[i], tz=tz_tw).strftime('%Y/%m/%d') 
            
            report.append({
                'date': dt, 'close': closes[i], 'pos': pos, 'pos_label': pos_label, 
                'macd_val': m_now, 'macd_status': status, 'macd_up': m_up,
                'rsi_val': r_val, 'rsi_status': r_status
            })
        except: continue
    return report

# ==========================================
# 🌐 第三部分：數據採集 (實時對位)
# ==========================================
def get_verified_data(ticker, interval="1d", lookback="max"):
    us_name_map = {
        'AAPL': '蘋果公司', 'NVDA': '輝達', 'TSLA': '特斯拉', 'MSFT': '微軟',
        'GOOGL': 'Alphabet', 'AMZN': '亞馬遜', 'META': 'Meta',
        'TSM': '台積電 ADR', 'AVGO': '博通', 'ASML': '艾司摩爾', 'AMD': '超微半導體'
    }
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={lookback}"
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        result = res.get('chart', {}).get('result', [])[0]
        meta = result.get('meta', {})
        
        m_state = meta.get('marketState', 'REGULAR')
        is_warning = meta.get('exchangeDataDelayedBy', 0) > 0 or m_state != 'REGULAR'
        status_label = "🚨 [注意/處置股監控]" if is_warning else "✅ 正常交易"
        
        live_price = meta.get('regularMarketPrice')
        live_time = meta.get('regularMarketTime')
        
        symbol = meta.get('symbol', '').split('.')[0]
        raw_name = meta.get('longName') or meta.get('shortName') or ticker
        stock_name = us_name_map.get(symbol, raw_name) if not (ticker.endswith('.TW') or ticker.endswith('.TWO')) else raw_name
        
        ts = result.get('timestamp', [])
        quote = result.get('indicators', {}).get('quote', [{}])[0]
        adj_close = result.get('indicators', {}).get('adjclose', [{}])[0].get('adjclose', [])
        raw_c = adj_close if (adj_close and len(adj_close) > 0) else quote.get('close', [])
        raw_h, raw_l = quote.get('high', []), quote.get('low', [])
        
        c_ts, c_c, c_h, c_l = [], [], [], []
        for i in range(len(ts)):
            if raw_c[i] is not None:
                c_ts.append(ts[i]); c_c.append(safe_float(raw_c[i]))
                c_h.append(safe_float(raw_h[i]) if raw_h[i] else safe_float(raw_c[i]))
                c_l.append(safe_float(raw_l[i]) if raw_l[i] else safe_float(raw_c[i]))
        
        # 實時價格強行覆蓋校準
        if live_price and c_c:
            if live_time > c_ts[-1] + 60:
                c_ts.append(live_time); c_c.append(live_price)
                c_h.append(live_price); c_l.append(live_price)
            else:
                c_c[-1] = live_price
                c_h[-1] = max(c_h[-1], live_price); c_l[-1] = min(c_l[-1], live_price)
        
        return {'name': stock_name, 'price': live_price, 
                'ath': max(c_h), 'atl': min(c_l), 'closes': c_c, 
                'highs': c_h, 'lows': c_l, 'ts': c_ts, 'status': status_label}
    except: return None

# ==========================================
# 🚀 第四部分：執行引擎
# ==========================================
def start_analysis_engine():
    print("=" * 115)
    print("🌍 全球多週期全量量化導航系統 (MACD + RSI 雙核實時版)")
    tz_tw = timezone(timedelta(hours=8))
    print(f"⏰ 系統時間：{datetime.now(tz=tz_tw).strftime('%Y/%m/%d %H:%M:%S')}")
    print("=" * 115)
    
    while True:
        stock_code = input("\n🔍 請輸入股票代碼 (Q 離開): ").strip().upper()
        if stock_code == 'Q': break
        is_tw = stock_code.isdigit()
        tickers = [f"{stock_code}.TW", f"{stock_code}.TWO"] if is_tw else [stock_code]
        
        d_data = None
        for t in tickers:
            d_data = get_verified_data(t, interval="1d", lookback="2y") # 嚴格鎖定日線
            if d_data: break
        if not d_data: print("❌ 抓取失敗"); continue
        
        mo_data = get_verified_data(t, interval="1mo", lookback="max")
        mo_up = (perform_macd_analysis(mo_data['closes'], is_tw)[-1] > perform_macd_analysis(mo_data['closes'], is_tw)[-2]) if mo_data else False
        wk_data = get_verified_data(t, interval="1wk", lookback="max")
        wk_up = (perform_macd_analysis(wk_data['closes'], is_tw)[-1] > perform_macd_analysis(wk_data['closes'], is_tw)[-2]) if wk_data else False
        
        history_5d = analyze_indicators_5day(d_data['closes'], d_data['highs'], d_data['lows'], d_data['ts'], is_tw)
        
        # --- 輸出報告 ---
        print("\n" + "★" * 115)
        print(f"【深度量化報告】 {stock_code} - {d_data['name']}")
        print(f"🚨 市場狀態：{d_data['status']} | 目前實時報價：{d_data['price']}")
        print(f"歷史極值範圍：{d_data['atl']:.2f} ↔ {d_data['ath']:.2f}")
        print("★" * 115)

        if "注意/處置" in d_data['status']:
            print(f"⚠️ 【處置股注意事項】：")
            print(f"   1. 人工撮合：個股處於處置期間，依規採人工撮合 (如5/20/60分鐘一盤)。")
            print(f"   2. 報價限制：數據受撮合頻率影響，價格顯示依實際即時成交價為主。")
            print(f"   3. 資金管控：部分處置條件需『全額預收款券』，請核對券商端餘額。")
            print(f"   4. 流動風險：撮合間隔長，請慎防流動性陷阱與解除處置後之震盪。")
            print("-" * 115)

        print(f"📈 【近 5 個交易日動能軌跡】 (MACD + RSI 雙核)")
        print("-" * 115)
        print(f"{'交易日期':<12} | {'收盤價':<8} | {'當日強度位階':<13} | {'MACD 柱狀值':<12} | {'MACD 動能':<12} | {'RSI(14)':<8} | {'RSI 狀態'}")
        print("-" * 115)
        if history_5d:
            for h in history_5d:
                print(f"{h['date']:<12} | {h['close']:<10.2f} | {h['pos']:>5.1f}% ({h['pos_label']}) | {h['macd_val']:>+12.3f} | {h['macd_status']:<12} | {h['rsi_val']:>6.1f} | {h['rsi_status']}")
        else:
            print("❌ 無法運算 5 日軌跡，數據量不足。")
            
        resonance_score = sum([history_5d[-1]['macd_up'] if history_5d else 0, wk_up, mo_up])
        score_visual = {3: "🟢 3 分", 2: "🟡 2 分", 1: "🟠 1 分", 0: "🔴 0 分"}[resonance_score]
        
        print("-" * 115)
        print(f"\n🧠 【導航手冊：指標數據與深層解析】")
        print(f"● 歷史位階：{((d_data['price']-d_data['atl'])/(d_data['ath']-d_data['atl'])*100):.1f}% -> [{'⚠️ 天價壓' if ((d_data['price']-d_data['atl'])/(d_data['ath']-d_data['atl'])*100) > 85 else '💎 底位撐' if ((d_data['price']-d_data['atl'])/(d_data['ath']-d_data['atl'])*100) < 15 else '⚖️ 合理區'}]")
        print(f"● 實時共振得分：{score_visual}")
        
        print(f"   ➤ 【共振得分定義與操作建議】：")
        print(f"      🟢 3 分 (主升共振)：月、週、日線動能皆向上。波段爆發潛力強，建議持股續抱。")
        print(f"      🟡 2 分 (趨勢修復)：長短週期動能分歧 (如長多短空、長空短多)。屬震盪整理格局。")
        print(f"      🟠 1 分 (弱勢反彈)：僅單一週期轉強，大勢依然向下。易遇假突破，短線見好就收。")
        print(f"      🔴 0 分 (空頭排列)：月、週、日線動能皆向下。趨勢極度弱勢，建議嚴格迴避。")
        
        print(f"   ➤ 【RSI (14日) 狀態定義與操作指南】：")
        print(f"      🔥 RSI ≥ 80 (超買警戒)：市場極度狂熱，短線漲幅過大，隨時面臨獲利了結賣壓，切忌追高。")
        print(f"      📈 RSI 50~79 (多方控盤)：買盤力道勝出，趨勢偏多運行，配合 MACD 紅柱為優良進場區。")
        print(f"      📉 RSI 21~49 (空方壓制)：賣盤力道勝出，趨勢偏空運行，反彈易遇壓，建議觀望防守。")
        print(f"      ❄️ RSI ≤ 20 (超賣低接)：市場恐慌拋售，短線跌幅已深，乖離過大，可留意跌深反彈契機。")
        
        cost_in = input(f"\n💰 請輸入成本 (按 Enter 觀望): ").strip()
        if cost_in:
            roi = (d_data['price'] - float(cost_in)) / float(cost_in)
            print(f"📊 實時損益：{roi:+.2%}。")
            
            current_rsi = history_5d[-1]['rsi_val'] if history_5d else 50
            if resonance_score == 3 and current_rsi < 80: 
                print("✅ 建議：三強共振標的且 RSI 尚未超買，建議續抱讓獲利奔跑。")
            elif current_rsi >= 80:
                print("🚨 建議：RSI 已進入極度超買區，隨時面臨獲利了結賣壓，強烈建議逢高分批減碼。")
            elif ((d_data['price']-d_data['atl'])/(d_data['ath']-d_data['atl'])*100) > 85 and not (history_5d and history_5d[-1]['macd_up']): 
                print("🚨 建議：歷史高位且實時動能轉弱，建議逢高分批減碼。")
            elif current_rsi <= 20 and resonance_score >= 1:
                print("💡 建議：RSI 嚴重超賣且動能有轉強跡象，短線乖離過大，可留意跌深反彈契機。")
            elif roi < -0.07: 
                print("🛑 建議：已觸及 7% 紀律止損線。")
            else: 
                print("🔎 建議：趨勢不明，以成本價為防線。")
        print("=" * 115)

if __name__ == "__main__":
    start_analysis_engine()
