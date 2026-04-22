# 檔名：20150422 MACD + RSI 終極通用對位版.py
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
# 🌐 第二部分：搜尋與數據採集 (🎯 名稱代碼連結核心)
# ==========================================
def search_ticker(query):
    """透過 Yahoo API 將中文名稱轉換為代碼"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    search_url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}&lang=zh-Hant-TW&region=TW"
    try:
        res = requests.get(search_url, headers=headers, timeout=5).json()
        quotes = res.get('quotes', [])
        if quotes:
            # 優先回傳最匹配的代碼與名稱
            return quotes[0].get('symbol'), quotes[0].get('longname') or quotes[0].get('shortname')
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
        
        # 獲取官方中文或英文名稱
        official_name = meta.get('longName') or meta.get('shortName') or ticker
        return {'closes': c_c, 'ts': c_ts, 'price': live_price, 'name': official_name, 'symbol': meta.get('symbol')}
    except: return None

# ==========================================
# 🚀 第三部分：網頁介面
# ==========================================
st.set_page_config(page_title="量化導航 2026", layout="wide")
st.title("🌍 全球量化導航系統 (名稱與代碼連結版)")

st.sidebar.header("🔍 查詢設定")
stock_input = st.sidebar.text_input("輸入股票名稱或代碼 (例: 台積電, 2330, AAPL)", value="台積電").strip()
cost_input = st.sidebar.number_input("持有成本 (0 代表觀望)", value=0.0)

if stock_input:
    # 💡 啟動搜尋引擎判斷
    d_data, wk_data, mo_data = None, None, None
    found_symbol, found_name = None, None

    with st.spinner(f'正在搜尋並對位「{stock_input}」的數據...'):
        # 判斷是否包含中文字元
        if re.search(r'[\u4e00-\u9fff]', stock_input):
            found_symbol, found_name = search_ticker(stock_input)
        else:
            found_symbol = stock_input.upper()

        if found_symbol:
            # 嘗試抓取日/週/月線
            tickers_to_try = [found_symbol]
            if found_symbol.isdigit(): # 若為純數字則自動嘗試 TW/TWO
                tickers_to_try = [f"{found_symbol}.TW", f"{found_symbol}.TWO"]
            
            for t in tickers_to_try:
                d_data = get_verified_data(t, "1d", "2y")
                if d_data:
                    wk_data = get_verified_data(t, "1wk", "max")
                    mo_data = get_verified_data(t, "1mo", "max")
                    break

    if d_data:
        tz_tw = timezone(timedelta(hours=8))
        report_time = datetime.now(tz_tw).strftime('%Y/%m/%d %H:%M:%S')
        is_tw = ".TW" in d_data['symbol'] or ".TWO" in d_data['symbol']
        
        # 💡 在報表標頭完整顯示 名稱 與 代碼
        display_label = f"{d_data['name']} ({d_data['symbol']})"
        st.success(f"✅ 成功對位！標的：{display_label} ｜ 報告產製時間：{report_time}")
        
        # 圖表邏輯 (隱藏 X 軸日期)
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

        # 核心決策報告
        st.divider()
        st.subheader(f"💡 {display_label} 核心量化決策報告")
        
        # 計算共振分
        h_d_up = hist[-1] > hist[-2]
        _, _, h_w = perform_macd_full(wk_data['closes'], is_tw) if wk_data else (0,0,[0,0])
        _, _, h_m = perform_macd_full(mo_data['closes'], is_tw) if mo_data else (0,0,[0,0])
        resonance_score = sum([h_d_up, (h_w[-1]>h_w[-2]), (h_m[-1]>h_m[-2])])
        
        col_metrics, col_advice = st.columns([1, 2])
        with col_metrics:
            st.metric("當前成交價", f"${d_data['price']}")
            if cost_input > 0:
                roi = (d_data['price'] - cost_input) / cost_input
                st.metric("實時損益率", f"{roi:+.2%}")
            st.metric("共振得分", f"{resonance_score} 分")

        with col_advice:
            curr_rsi = rsi_vals[-1]
            if cost_input > 0 and (d_data['price'] - cost_input) / cost_input < -0.07:
                st.error("🛑 **建議：執行止損**。虧損已達 7% 紀律線，建議回收資金。")
            elif curr_rsi >= 80:
                st.warning("🚨 **建議：逢高減碼**。RSI 已進入極度超買區。")
            elif resonance_score == 3 and curr_rsi < 80:
                st.success("✅ **建議：持股續抱**。全週期共振向上，讓獲利奔跑。")
            else:
                st.info("🔎 **建議：區間操作**。動能分歧，依據成本價守好防線。")

        with st.expander("📖 查看【共振得分與 RSI 指南】"):
            st.markdown("* **3 分**: 月/週/日全線向上 🟢\n* **0 分**: 全線向下 🔴\n* **RSI > 80**: 過熱 🚨\n* **RSI < 20**: 恐慌 ❄️")

        st.subheader("📅 近 5 個交易日軌跡")
        table_df = pd.DataFrame({'日期': full_dates, '收盤': d_data['closes'], 'MACD': hist, 'RSI': rsi_vals}).drop_duplicates(subset=['日期'], keep='last').tail(5)
        st.table(table_df)
    else:
        st.error(f"❌ 無法抓取數據。請檢查「{stock_input}」是否輸入正確。")
