# 檔名：20150424 MACD + RSI 終極行動優化版.py
import streamlit as st
import requests
import pandas as pd
import time
import altair as alt
import re
import urllib.parse
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
# 🌐 第二部分：雙向反查搜尋引擎
# ==========================================
def search_ticker(query):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    # 1. Yahoo 奇摩股市 (台灣本土 API)
    try:
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;query={urllib.parse.quote(query)}"
        res = requests.get(url, headers=headers, timeout=5).json()
        results = res.get('ResultSet', {}).get('Result', [])
        for r in results:
            sym = r.get('symbol', '')
            if sym.endswith('.TW') or sym.endswith('.TWO') or sym.endswith('.TE'):
                return sym, r.get('name')
        if results: return results[0].get('symbol'), results[0].get('name')
    except: pass
    
    # 2. FinMind 備援
    try:
        fm_url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
        res = requests.get(fm_url, headers=headers, timeout=5).json()
        for item in res.get('data', []):
            sid = item.get('stock_id')
            sname = item.get('stock_name', '')
            if query == sid or query in sname:
                stype = item.get('type')
                if stype == 'twse': return f"{sid}.TW", sname
                elif stype == 'tpex': return f"{sid}.TWO", sname
                elif stype == 'emerging': return f"{sid}.TE", sname
    except: pass
    return None, None

@st.cache_data(ttl=10)
def get_verified_data(ticker, interval="1d", range_val="2y"):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_val}&_ts={int(time.time())}"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200: return None
        json_data = res.json()
        result = json_data['chart']['result'][0]
        meta = result.get('meta', {})
        ts = result.get('timestamp', [])
        if not ts or len(ts) < 5: return None 
        tz_tw = timezone(timedelta(hours=8))
        if (datetime.now(tz_tw) - datetime.fromtimestamp(ts[-1], tz=tz_tw)).days > 30: return None
        quote = result.get('indicators', {}).get('quote', [{}])[0]
        raw_c = quote.get('close', [])
        c_ts, c_c = [], []
        for i in range(len(ts)):
            if raw_c[i] is not None:
                c_ts.append(ts[i]); c_c.append(float(raw_c[i]))
        live_price = meta.get('regularMarketPrice')
        if live_price is None and c_c: live_price = c_c[-1]
        if interval == "1d" and live_price and c_ts:
            if datetime.now(tz_tw).date() > datetime.fromtimestamp(c_ts[-1], tz=tz_tw).date():
                c_ts.append(datetime.now(tz_tw).timestamp()); c_c.append(live_price)
            else: c_c[-1] = live_price
        return {'closes': c_c, 'ts': c_ts, 'price': live_price, 'name': meta.get('longName') or ticker, 'symbol': meta.get('symbol')}
    except: return None

# ==========================================
# 🚀 第三部分：網頁介面 (頂部查詢佈局)
# ==========================================
st.set_page_config(page_title="量化導航 2026", layout="wide")
st.title("🌍 全球量化導航系統")

# 💡 關鍵變動：將查詢設定移至頁面頂部
st.markdown("---")
# 使用 columns 建立頂部搜尋列
search_col, cost_col = st.columns([3, 1])

with search_col:
    # 預設值為空字串 ""
    stock_input = st.text_input("🔍 輸入名稱或代碼 (上市/上櫃/興櫃/美股)", value="", placeholder="例如: 台積電 或 2330").strip()

with cost_col:
    cost_input = st.number_input("💰 持有成本", value=0.0, help="輸入 0 代表純觀望分析")
st.markdown("---")

if stock_input:
    d_data, wk_data, mo_data = None, None, None
    found_symbol, display_name = None, None

    with st.spinner(f'正在解析「{stock_input}」並同步雲端數據...'):
        found_symbol, display_name = search_ticker(stock_input)
        if not found_symbol:
            found_symbol = stock_input.upper()
            display_name = stock_input.upper()

        if found_symbol:
            tickers_to_try = [found_symbol]
            base_symbol = found_symbol.split('.')[0]
            if base_symbol.isdigit():
                for sfx in ['.TW', '.TWO', '.TE']:
                    candidate = f"{base_symbol}{sfx}"
                    if candidate not in tickers_to_try: tickers_to_try.append(candidate)
            
            for t in tickers_to_try:
                d_data = get_verified_data(t, "1d", "2y")
                if d_data:
                    wk_data = get_verified_data(t, "1wk", "max")
                    mo_data = get_verified_data(t, "1mo", "max")
                    break 

    if d_data:
        tz_tw = timezone(timedelta(hours=8))
        report_time = datetime.now(tz_tw).strftime('%Y/%m/%d %H:%M:%S')
        is_tw = d_data['symbol'].endswith('.TW') or d_data['symbol'].endswith('.TWO') or d_data['symbol'].endswith('.TE')
        
        # 名稱決策 (繁中優先)
        final_name = display_name if re.search(r'[\u4e00-\u9fff]', str(display_name)) else d_data['name']
        display_label = f"{final_name} ({d_data['symbol']})"
        
        st.success(f"✅ 分析完成！標的：{display_label} ｜ 時間：{report_time}")
        
        # --- 圖表區 (隱藏 X 軸日期) ---
        full_dates = [datetime.fromtimestamp(t, tz=tz_tw).strftime('%Y/%m/%d') for t in d_data['ts']]
        x_axis_clean = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))
        
        dif, dea, hist = perform_macd_full(d_data['closes'], is_tw)
        rsi_vals = calculate_rsi(d_data['closes'])

        col1, col2, col3 = st.columns(3)
        with col1:
            st.subheader("價格走勢")
            df = pd.DataFrame({'日期': full_dates, '價格': d_data['closes']}).drop_duplicates(subset=['日期'])
            st.altair_chart(alt.Chart(df).mark_line().encode(x=x_axis_clean, y=alt.Y('價格', scale=alt.Scale(zero=False), title=None), tooltip=['日期', '價格']), use_container_width=True)
        with col2:
            st.subheader("MACD 柱狀")
            df = pd.DataFrame({'日期': full_dates, '柱狀': hist}).drop_duplicates(subset=['日期'])
            st.altair_chart(alt.Chart(df).mark_bar().encode(x=x_axis_clean, y=alt.Y('柱狀', title=None), color=alt.condition(alt.datum['柱狀'] > 0, alt.value('#ff4b4b'), alt.value('#00cc96')), tooltip=['日期', '柱狀']), use_container_width=True)
        with col3:
            st.subheader("RSI (14)")
            df = pd.DataFrame({'日期': full_dates, 'RSI': rsi_vals}).drop_duplicates(subset=['日期'])
            st.altair_chart(alt.Chart(df).mark_line(color='#9467bd').encode(x=x_axis_clean, y=alt.Y('RSI', scale=alt.Scale(domain=[0, 100]), title=None), tooltip=['日期', 'RSI']), use_container_width=True)

        # --- 策略報告 ---
        st.divider()
        h_d_up = hist[-1] > hist[-2] if hist else False
        _, _, h_w = perform_macd_full(wk_data['closes'], is_tw) if wk_data else (0,0,[0,0])
        _, _, h_m = perform_macd_full(mo_data['closes'], is_tw) if mo_data else (0,0,[0,0])
        resonance_score = sum([h_d_up, (len(h_w)>1 and h_w[-1]>h_w[-2]), (len(h_m)>1 and h_m[-1]>h_m[-2])])
        score_info = {3: "🟢 3 分 (主升共振)", 2: "🟡 2 分 (趨勢修復)", 1: "🟠 1 分 (弱勢反彈)", 0: "🔴 0 分 (空頭排列)"}
        
        col_m, col_a = st.columns([1, 2])
        with col_m:
            st.metric("當前價", f"${d_data['price']}")
            if cost_input > 0:
                roi = (d_data['price'] - cost_input) / cost_input
                st.metric("損益率", f"{roi:+.2%}")
            st.metric("共振得分", score_info[resonance_score])
        with col_a:
            curr_rsi = rsi_vals[-1] if rsi_vals else 50
            if cost_input > 0 and (d_data['price'] - cost_input) / cost_input < -0.07:
                st.error("🛑 **建議：執行止損**。虧損已達 7% 紀律線。")
            elif curr_rsi >= 80:
                st.warning("🚨 **建議：逢高減碼**。RSI 已進入極度超買區。")
            elif resonance_score == 3 and curr_rsi < 80:
                st.success("✅ **建議：持股續抱**。全週期共振向上，趨勢強勁。")
            else:
                st.info("🔎 **建議：區間操作**。動能分歧，依據成本價守好防線。")

        with st.expander("📖 查看【共振得分與 RSI 指南】"):
            st.markdown("* **🟢 3 分**: 月/週/日全線向上\n* **🔴 0 分**: 全線向下\n* **🔥 RSI ≥ 80**: 超買過熱\n* **❄️ RSI ≤ 20**: 恐慌超賣")

        st.subheader("📅 近 5 日軌跡")
        table_df = pd.DataFrame({'日期': full_dates, '收盤': d_data['closes'], 'MACD': [round(x,3) for x in hist], 'RSI': [round(x,1) for x in rsi_vals]}).drop_duplicates(subset=['日期'], keep='last').tail(5)
        st.table(table_df)
    else:
        st.error(f"❌ 查無「{stock_input}」的數據，請檢查名稱或代碼。")
else:
    # 💡 預設留白時顯示的導引
    st.info("💡 **請在上方輸入框輸入股票名稱 (如: 台積電) 或代號 (如: 2330) 以開啟量化分析。**")
