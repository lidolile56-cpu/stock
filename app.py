# 檔名：20150422 MACD + RSI 台股全市場對位版.py
import streamlit as st
import requests
import pandas as pd
import time
import altair as alt
import re
from datetime import datetime, timezone, timedelta

# ==========================================
# 📊 第一部分：量化核心邏輯
# ==========================================
def calculate_ema(data, n):
    if len(data) < n: return [data[-1]] * len(data)
    res = [sum(data[:n])/n]
    alpha = 2 / (n + 1)
    full_res = [data[0]] * (n - 1) + res
    for i in range(n, len(data)):
        full_res.append(data[i] * alpha + full_res[-1] * (1 - alpha))
    return full_res

def perform_macd_full(closes, is_tw):
    if not closes or len(closes) < 35: return None, None, None
    e12 = calculate_ema(closes, 12)
    e26 = calculate_ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = calculate_ema(dif, 9)
    # 台股市場 (TW/TWO/TE) 放大的乘數
    multiplier = 2.0 if is_tw else 1.0
    hist = [(d - a) * multiplier for d, a in zip(dif, dea)]
    return dif, dea, hist

def calculate_rsi(closes, period=14):
    if not closes or len(closes) < period + 1: return [50.0] * len(closes)
    rsi_series = [50.0] * period
    avg_gain = sum(max(0, closes[i] - closes[i-1]) for i in range(1, period+1)) / period
    avg_loss = sum(max(0, closes[i-1] - closes[i]) for i in range(1, period+1)) / period
    rsi_series.append(100.0 - (100.0 / (1.0 + (avg_gain / (avg_loss if avg_loss != 0 else 0.0001)))))
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i-1]
        avg_gain = (avg_gain * (period - 1) + max(0, diff)) / period
        avg_loss = (avg_loss * (period - 1) + max(0, -diff)) / period
        rsi_series.append(100.0 - (100.0 / (1.0 + (avg_gain / (avg_loss if avg_loss != 0 else 0.0001)))))
    return rsi_series

# ==========================================
# 🌐 第二部分：全市場搜尋引擎與數據採集
# ==========================================
def search_ticker(query):
    """支援 上市/上櫃/興櫃 的中英雙向搜尋引擎"""
    # 1. 內建極速字典 (擴增熱門上櫃股)
    common_stocks = {
        # 上市熱門
        "台積電": "2330.TW", "鴻海": "2317.TW", "聯發科": "2454.TW", "廣達": "2382.TW",
        "富邦金": "2881.TW", "國泰金": "2882.TW", "台達電": "2308.TW", "中華電": "2412.TW",
        "長榮": "2603.TW", "聯電": "2303.TW", "大立光": "3008.TW", "緯創": "3231.TW",
        # 上櫃熱門 (OTC)
        "元太": "8069.TWO", "鈊象": "3293.TWO", "環球晶": "6488.TWO", "群聯": "8299.TWO", 
        "世界": "5347.TWO", "譜瑞": "4966.TWO", "信驊": "5274.TWO", "力旺": "3529.TWO",
        "穩懋": "3105.TWO", "雙鴻": "3324.TWO", "中美晶": "5483.TWO"
    }
    for name, symbol in common_stocks.items():
        if name in query:
            return symbol, name

    # 2. Yahoo API 搜尋 (全面開放 .TW, .TWO, .TE)
    headers = {'User-Agent': 'Mozilla/5.0'}
    search_url = "https://query2.finance.yahoo.com/v1/finance/search"
    params = {'q': query, 'lang': 'zh-Hant-TW', 'region': 'TW', 'quotesCount': 5}
    
    try:
        res = requests.get(search_url, headers=headers, params=params, timeout=5).json()
        quotes = res.get('quotes', [])
        
        # 優先過濾出 上市(TW) / 上櫃(TWO) / 興櫃(TE)
        for q in quotes:
            sym = q.get('symbol', '')
            if sym.endswith('.TW') or sym.endswith('.TWO') or sym.endswith('.TE'):
                return sym, q.get('longname') or q.get('shortname') or query
                
        if quotes:
            return quotes[0].get('symbol'), quotes[0].get('longname') or quotes[0].get('shortname') or query
    except: pass
    
    return None, None

@st.cache_data(ttl=10)
def get_verified_data(ticker, interval="1d", range_val="2y"):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_val}&_ts={int(time.time())}"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200: return None
        result = res.json()['chart']['result'][0]
        meta = result.get('meta', {})
        live_price = meta.get('regularMarketPrice')
        ts, quote = result.get('timestamp', []), result.get('indicators', {}).get('quote', [{}])[0]
        raw_c = quote.get('close', [])
        c_ts, c_c = [], []
        for i in range(len(ts)):
            if raw_c[i] is not None:
                c_ts.append(ts[i]); c_c.append(float(raw_c[i]))
                
        # 補強今日數據
        tz_tw = timezone(timedelta(hours=8))
        if interval == "1d" and live_price and c_ts:
            if datetime.now(tz_tw).date() > datetime.fromtimestamp(c_ts[-1], tz=tz_tw).date():
                c_ts.append(datetime.now(tz_tw).timestamp()); c_c.append(live_price)
            else: c_c[-1] = live_price
            
        official_name = meta.get('longName') or meta.get('shortName') or ticker
        return {'closes': c_c, 'ts': c_ts, 'price': live_price, 'name': official_name, 'symbol': meta.get('symbol')}
    except: return None

# ==========================================
# 🚀 第三部分：網頁介面與決策引擎
# ==========================================
st.set_page_config(page_title="量化導航 2026", layout="wide")
st.title("🌍 全球量化導航系統 (台股全市場版)")

st.sidebar.header("🔍 查詢設定")
stock_input = st.sidebar.text_input("輸入名稱或代碼 (例: 鈊象, 3595, AAPL)", value="台積電").strip()
cost_input = st.sidebar.number_input("持有成本 (0 代表觀望)", value=0.0)

if stock_input:
    d_data, wk_data, mo_data = None, None, None
    found_symbol, display_name = None, None

    with st.spinner(f'正在進行全市場搜尋 (上市/上櫃/興櫃)...'):
        if re.search(r'[\u4e00-\u9fff]', stock_input):
            found_symbol, display_name = search_ticker(stock_input)
        else:
            found_symbol = stock_input.upper()
            display_name = stock_input.upper()

        if found_symbol:
            tickers_to_try = [found_symbol]
            # 💡 擴展到三市場尋標引擎
            if found_symbol.isdigit(): 
                tickers_to_try = [f"{found_symbol}.TW", f"{found_symbol}.TWO", f"{found_symbol}.TE"]
            
            for t in tickers_to_try:
                d_data = get_verified_data(t, "1d", "2y")
                if d_data:
                    wk_data = get_verified_data(t, "1wk", "max")
                    mo_data = get_verified_data(t, "1mo", "max")
                    break # 找到對應市場，立刻跳出迴圈

    if d_data:
        tz_tw = timezone(timedelta(hours=8))
        report_time = datetime.now(tz_tw).strftime('%Y/%m/%d %H:%M:%S')
        
        # 判斷是否為台股 (包含興櫃 TE)
        is_tw = d_data['symbol'].endswith('.TW') or d_data['symbol'].endswith('.TWO') or d_data['symbol'].endswith('.TE')
        
        final_name = display_name if re.search(r'[\u4e00-\u9fff]', display_name) else d_data['name']
        display_label = f"{final_name} ({d_data['symbol']})"
        
        st.success(f"✅ 成功對位！標的：{display_label} ｜ 報告產製時間：{report_time}")
        
        # --- 圖表區 (隱藏 X 軸日期) ---
        full_dates = [datetime.fromtimestamp(t, tz=tz_tw).strftime('%Y/%m/%d') for t in d_data['ts']]
        x_axis_clean = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))

        st.subheader(f"📈 {display_label} 多維度量化趨勢")
        col_price, col_macd, col_rsi = st.columns(3)
        
        dif, dea, hist = perform_macd_full(d_data['closes'], is_tw)
        rsi_vals = calculate_rsi(d_data['closes'])

        with col_price:
            df = pd.DataFrame({'日期': full_dates, '價格': d_data['closes']}).drop_duplicates(subset=['日期'])
            st.altair_chart(alt.Chart(df).mark_line().encode(x=x_axis_clean, y=alt.Y('價格', scale=alt.Scale(zero=False), title=None), tooltip=['日期', '價格']), use_container_width=True)
        with col_macd:
            df = pd.DataFrame({'日期': full_dates, '柱狀': hist}).drop_duplicates(subset=['日期'])
            st.altair_chart(alt.Chart(df).mark_bar().encode(x=x_axis_clean, y=alt.Y('柱狀', title=None), color=alt.condition(alt.datum['柱狀'] > 0, alt.value('#ff4b4b'), alt.value('#00cc96')), tooltip=['日期', '柱狀']), use_container_width=True)
        with col_rsi:
            df = pd.DataFrame({'日期': full_dates, 'RSI': rsi_vals}).drop_duplicates(subset=['日期'])
            st.altair_chart(alt.Chart(df).mark_line(color='#9467bd').encode(x=x_axis_clean, y=alt.Y('RSI', scale=alt.Scale(domain=[0, 100]), title=None), tooltip=['日期', 'RSI']), use_container_width=True)

        # --- 核心決策區 ---
        st.divider()
        st.subheader(f"💡 {display_label} 核心量化決策報告")
        
        h_d_up = hist[-1] > hist[-2]
        _, _, h_w = perform_macd_full(wk_data['closes'], is_tw) if wk_data else (0,0,[0,0])
        _, _, h_m = perform_macd_full(mo_data['closes'], is_tw) if mo_data else (0,0,[0,0])
        resonance_score = sum([h_d_up, (len(h_w)>1 and h_w[-1]>h_w[-2]), (len(h_m)>1 and h_m[-1]>h_m[-2])])
        score_info = {3: "🟢 3 分 (主升共振)", 2: "🟡 2 分 (趨勢修復)", 1: "🟠 1 分 (弱勢反彈)", 0: "🔴 0 分 (空頭排列)"}
        
        col_metrics, col_advice = st.columns([1, 2])
        with col_metrics:
            st.metric("當前成交價", f"${d_data['price']}")
            if cost_input > 0:
                roi = (d_data['price'] - cost_input) / cost_input
                st.metric("實時損益率", f"{roi:+.2%}")
            st.metric("實時共振得分", score_info[resonance_score])

        with col_advice:
            curr_rsi = rsi_vals[-1]
            if cost_input > 0 and (d_data['price'] - cost_input) / cost_input < -0.07:
                st.error("🛑 **建議：執行止損**。虧損已達 7% 紀律線，建議優先回收資金。")
            elif curr_rsi >= 80:
                st.warning("🚨 **建議：逢高減碼**。RSI 已進入極度超買區，隨時有獲利了結賣壓。")
            elif resonance_score == 3 and curr_rsi < 80:
                st.success("✅ **建議：持股續抱**。月、週、日三強共振，尚未進入過熱區，讓獲利奔跑。")
            elif resonance_score == 0:
                st.error("📉 **建議：嚴格觀望**。全週期動能向下，切勿隨意摸底接刀。")
            else:
                st.info("🔎 **建議：區間操作**。動能分歧，建議依據成本價守好防線，觀望趨勢明朗。")

        with st.expander("📖 查看【共振得分與 RSI 指南】"):
            st.markdown("* **🟢 3 分 (主升共振)**：月/週/日線動能同步向上，波段爆發力最強。\n* **🟡 2 分 (趨勢修復)**：長短週期動能出現分歧，震盪整理。\n* **🟠 1 分 (弱勢反彈)**：僅單一週期動能轉強，大勢依然向下。\n* **🔴 0 分 (空頭排列)**：全週期動能皆向下，市場極度弱勢。\n---\n* **🔥 RSI ≥ 80 (超買警戒)**：市場極度狂熱，應考慮獲利了結。\n* **📈 RSI 50~79 (多方控盤)**：買盤力道勝出，趨勢偏多運行。\n* **📉 RSI 21~49 (空方壓制)**：賣盤力道勝出，趨勢偏空運行。\n* **❄️ RSI ≤ 20 (超賣低接)**：市場出現恐慌拋售，留意跌深反彈契機。")

        st.subheader("📅 近 5 個交易日量化軌跡")
        table_df = pd.DataFrame({'交易日期': full_dates, '收盤價': d_data['closes'], 'MACD柱狀': [round(x,3) for x in hist], 'RSI(14)': [round(x,1) for x in rsi_vals]}).drop_duplicates(subset=['交易日期'], keep='last').tail(5)
        st.table(table_df)
    else:
        st.error(f"❌ 無法抓取數據。請檢查「{stock_input}」名稱或代碼是否正確。")
