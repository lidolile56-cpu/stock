# 檔名：20150422 MACD + RSI 終極量化決策版.py
import streamlit as st
import requests
import pandas as pd
import time
import altair as alt
from datetime import datetime, timezone, timedelta

# ==========================================
# 📊 第一部分：量化核心邏輯 (計算 MACD 與 RSI)
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
# 🌐 第二部分：數據採集 (雙引擎與多週期抓取)
# ==========================================
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
        # 補強今日數據 (僅限日線)
        if interval == "1d" and live_price and c_ts:
            tz_tw = timezone(timedelta(hours=8))
            if datetime.now(tz_tw).date() > datetime.fromtimestamp(c_ts[-1], tz=tz_tw).date():
                c_ts.append(datetime.now(tz_tw).timestamp()); c_c.append(live_price)
            else: c_c[-1] = live_price
        return {'closes': c_c, 'ts': c_ts, 'price': live_price, 'name': meta.get('symbol')}
    except: return None

# ==========================================
# 🚀 第三部分：網頁介面與策略引擎
# ==========================================
st.set_page_config(page_title="量化導航 2026", layout="wide")
st.title("🌍 全球量化導航系統 (精準策略建議版)")

st.sidebar.header("🔍 查詢設定")
stock_input = st.sidebar.text_input("輸入代碼 (例: 2330, 3595, AAPL)", value="2330").strip().upper()
cost_input = st.sidebar.number_input("持有成本 (0 代表觀望)", value=0.0)

if stock_input:
    tickers = [f"{stock_input}.TW", f"{stock_input}.TWO"] if stock_input.isdigit() else [stock_input]
    d_data, wk_data, mo_data = None, None, None
    final_ticker = ""

    with st.spinner(f'正在進行多週期掃描 {stock_input}...'):
        for t in tickers:
            d_data = get_verified_data(t, "1d", "2y")
            if d_data:
                wk_data = get_verified_data(t, "1wk", "max")
                mo_data = get_verified_data(t, "1mo", "max")
                final_ticker = t
                break

    if d_data:
        tz_tw = timezone(timedelta(hours=8))
        report_time = datetime.now(tz_tw).strftime('%Y/%m/%d %H:%M:%S')
        st.success(f"✅ 掃描完成！標的：{final_ticker} ｜ 報告產製時間：{report_time}")
        
        # 數據計算
        is_tw = ".TW" in final_ticker or ".TWO" in final_ticker
        dif, dea, hist = perform_macd_full(d_data['closes'], is_tw)
        rsi_vals = calculate_rsi(d_data['closes'])
        
        # --- 📈 視覺化圖表區 (隱藏 X 軸標籤) ---
        full_dates = [datetime.fromtimestamp(t, tz=tz_tw).strftime('%Y/%m/%d') for t in d_data['ts']]
        x_axis_clean = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))

        st.subheader(f"📊 {d_data['name']} 多維度量化走勢")
        col_price, col_macd, col_rsi = st.columns(3)
        
        with col_price:
            price_df = pd.DataFrame({'日期': full_dates, '價格': d_data['closes']}).drop_duplicates(subset=['日期'])
            chart = alt.Chart(price_df).mark_line(color='#1f77b4').encode(x=x_axis_clean, y=alt.Y('價格', scale=alt.Scale(zero=False), title=None), tooltip=['日期', '價格'])
            st.altair_chart(chart, use_container_width=True)
        with col_macd:
            macd_df = pd.DataFrame({'日期': full_dates, '柱狀': hist}).drop_duplicates(subset=['日期'])
            chart = alt.Chart(macd_df).mark_bar().encode(x=x_axis_clean, y=alt.Y('柱狀', title=None), color=alt.condition(alt.datum['柱狀'] > 0, alt.value('#ff4b4b'), alt.value('#00cc96')), tooltip=['日期', '柱狀'])
            st.altair_chart(chart, use_container_width=True)
        with col_rsi:
            rsi_df = pd.DataFrame({'日期': full_dates, 'RSI': rsi_vals}).drop_duplicates(subset=['日期'])
            chart = alt.Chart(rsi_df).mark_line(color='#9467bd').encode(x=x_axis_clean, y=alt.Y('RSI', scale=alt.Scale(domain=[0, 100]), title=None), tooltip=['日期', 'RSI'])
            st.altair_chart(chart, use_container_width=True)

        # --- 🧠 核心：共振得分與操作建議 ---
        st.divider()
        st.subheader("💡 核心量化決策報告")
        
        # 計算共振分 (日/週/月)
        h_d_up = hist[-1] > hist[-2]
        _, _, h_w = perform_macd_full(wk_data['closes'], is_tw) if wk_data else (None, None, [0, 0])
        _, _, h_m = perform_macd_full(mo_data['closes'], is_tw) if mo_data else (None, None, [0, 0])
        h_w_up = h_w[-1] > h_w[-2] if len(h_w) > 1 else False
        h_m_up = h_m[-1] > h_m[-2] if len(h_m) > 1 else False
        
        resonance_score = sum([h_d_up, h_w_up, h_m_up])
        score_info = {3: "🟢 3 分 (主升共振)", 2: "🟡 2 分 (趨勢修復)", 1: "🟠 1 分 (弱勢反彈)", 0: "🔴 0 分 (空頭排列)"}
        
        col_score, col_suggest = st.columns([1, 2])
        with col_score:
            st.metric("實時共振得分", score_info[resonance_score])
            if cost_input > 0:
                roi = (d_data['price'] - cost_input) / cost_input
                st.metric("實時損益率", f"{roi:+.2%}")
        
        with col_suggest:
            curr_rsi = rsi_vals[-1]
            if cost_input > 0 and (d_data['price'] - cost_input) / cost_input < -0.07:
                st.error("🛑 **建議：執行止損**。虧損已達 7% 紀律線，建議回收資金。")
            elif curr_rsi >= 80:
                st.warning("🚨 **建議：逢高減碼**。RSI 已進入極度超買區，隨時面臨獲利了結賣壓。")
            elif resonance_score == 3 and curr_rsi < 80:
                st.success("✅ **建議：持股續抱**。月、週、日三強共振，且尚未過熱，讓獲利奔跑。")
            elif resonance_score == 0:
                st.error("📉 **建議：嚴格觀望**。全週期動能向下，切勿隨意摸底接刀。")
            else:
                st.info("🔎 **建議：區間操作**。動能分歧，建議依據成本價守好防線，觀望趨勢明朗。")

        # --- 📖 顯示定義指南 (Expander) ---
        with st.expander("📖 查看【共振得分定義與操作建議】參考手冊"):
            st.markdown("""
            ### 🎯 共振得分 (Resonance Score) 定義
            * **🟢 3 分 (主升共振)**：月線、週線、日線動能同時向上。代表大趨勢與小趨勢同步，波段爆發力最強。
            * **🟡 2 分 (趨勢修復)**：長週期與短週期動能出現分歧。通常處於震盪整理或多頭回測階段。
            * **🟠 1 分 (弱勢反彈)**：僅單一週期動能轉強。大勢依然向下，易遇到假突破。
            * **🔴 0 分 (空頭排列)**：所有週期動能皆向下。市場極度弱勢，建議嚴格迴避。

            ### 📈 RSI 位階指南
            * **🔥 80 以上 (超買警戒)**：市場情緒極度狂熱，應考慮獲利了結，切忌追高。
            * **📈 50~79 (多方控盤)**：買盤力道勝出，趨勢偏多運行。
            * **📉 21~49 (空方壓制)**：賣盤力道勝出，趨勢偏空運行。
            * **❄️ 20 以下 (超賣低接)**：市場出現恐慌拋售，可留意跌深反彈的契機。
            """)

        # --- 近 5 日軌跡表格 ---
        st.subheader("📅 近 5 個交易日量化軌跡")
        table_df = pd.DataFrame({'交易日期': full_dates, '收盤價': d_data['closes'], 'MACD柱狀': hist, 'RSI(14)': rsi_vals}).drop_duplicates(subset=['交易日期'], keep='last').tail(5)
        st.table(table_df)
    else:
        st.error("❌ 無法抓取數據。")
