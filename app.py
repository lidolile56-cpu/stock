# 檔名：20150422 MACD + RSI 終極完美版.py
import streamlit as st
import requests
import pandas as pd
import time
import altair as alt
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
# 🌐 第二部分：數據採集 (雙引擎與去重)
# ==========================================
@st.cache_data(ttl=10)
def get_verified_data(ticker):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2y&_ts={int(time.time())}"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200: return None
        result = res.json()['chart']['result'][0]
        meta = result.get('meta', {})
        live_price = meta.get('regularMarketPrice')
        ts, quote = result.get('timestamp', []), result.get('indicators', {}).get('quote', [{}])[0]
        raw_c, raw_h, raw_l = quote.get('close', []), quote.get('high', []), quote.get('low', [])
        c_ts, c_c, c_h, c_l = [], [], [], []
        for i in range(len(ts)):
            if raw_c[i] is not None:
                c_ts.append(ts[i]); c_c.append(float(raw_c[i]))
                c_h.append(float(raw_h[i]) if raw_h[i] else float(raw_c[i]))
                c_l.append(float(raw_l[i]) if raw_l[i] else float(raw_c[i]))
        tz_tw = timezone(timedelta(hours=8))
        now_tw = datetime.now(tz_tw)
        if live_price and c_ts:
            if now_tw.date() > datetime.fromtimestamp(c_ts[-1], tz=tz_tw).date():
                c_ts.append(now_tw.timestamp()); c_c.append(live_price)
            else: c_c[-1] = live_price
        return {'name': meta.get('symbol'), 'price': live_price, 'ath': max(c_h), 'atl': min(c_l), 'closes': c_c, 'ts': c_ts}
    except: return None

# ==========================================
# 🚀 第三部分：網頁介面 (恢復精準分析建議)
# ==========================================
st.set_page_config(page_title="量化導航 2026", layout="wide")
st.title("🌍 全球量化導航系統 (精準分析與高階圖表版)")

st.sidebar.header("🔍 查詢設定")
stock_input = st.sidebar.text_input("輸入代碼", value="2330").strip().upper()
cost_input = st.sidebar.number_input("持有成本 (0 代表觀望)", value=0.0)

if stock_input:
    tickers = [f"{stock_input}.TW", f"{stock_input}.TWO"] if stock_input.isdigit() else [stock_input]
    d_data = None
    for t in tickers:
        d_data = get_verified_data(t)
        if d_data:
            final_ticker = t
            break

    if d_data:
        tz_tw = timezone(timedelta(hours=8))
        report_time = datetime.now(tz_tw).strftime('%Y/%m/%d %H:%M:%S')
        st.success(f"✅ 分析完成！報告產製時間：{report_time}")
        
        full_dates = [datetime.fromtimestamp(t, tz=tz_tw).strftime('%Y/%m/%d') for t in d_data['ts']]
        x_axis_clean = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))

        # --- 1. 收盤價走勢 ---
        st.subheader(f"📈 {d_data['name']} 收盤價走勢")
        price_df = pd.DataFrame({'日期': full_dates, '收盤價': d_data['closes']}).drop_duplicates(subset=['日期'])
        c_price = alt.Chart(price_df).mark_line(color='#1f77b4').encode(x=x_axis_clean, y=alt.Y('收盤價', scale=alt.Scale(zero=False), title=None), tooltip=['日期', '收盤價'])
        st.altair_chart(c_price, use_container_width=True)

        # --- 2. MACD 與 RSI ---
        dif, dea, hist = perform_macd_full(d_data['closes'], ".TW" in final_ticker)
        rsi_vals = calculate_rsi(d_data['closes'])
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📊 MACD 指標")
            macd_df = pd.DataFrame({'日期': full_dates, 'DIF': dif, 'DEA': dea, '柱狀': hist}).drop_duplicates(subset=['日期'])
            c_lines = alt.Chart(macd_df.melt('日期', var_name='指標', value_name='數值')).mark_line().encode(x=x_axis_clean, y=alt.Y('數值', title=None), color='指標', tooltip=['日期', '指標', '數值'])
            c_bar = alt.Chart(macd_df).mark_bar().encode(x=x_axis_clean, y=alt.Y('柱狀', title=None), color=alt.condition(alt.datum['柱狀'] > 0, alt.value('#ff4b4b'), alt.value('#00cc96')), tooltip=['日期', '柱狀'])
            st.altair_chart(c_bar + c_lines, use_container_width=True)
        with col2:
            st.subheader("📉 RSI (14) 走勢")
            rsi_df = pd.DataFrame({'日期': full_dates, 'RSI': rsi_vals}).drop_duplicates(subset=['日期'])
            c_rsi = alt.Chart(rsi_df).mark_line(color='#9467bd').encode(x=x_axis_clean, y=alt.Y('RSI', scale=alt.Scale(domain=[0, 100]), title=None), tooltip=['日期', 'RSI'])
            st.altair_chart(c_rsi, use_container_width=True)

        # --- 💡 恢復：精準文字分析區 ---
        st.divider()
        st.subheader("💡 核心決策分析報告")
        
        # 計算共振得分 (需抓週/月線，此處簡化為趨勢判斷)
        current_macd_up = hist[-1] > hist[-2]
        current_rsi = rsi_vals[-1]
        
        # 損益分析
        if cost_input > 0:
            roi = (d_data['price'] - cost_input) / cost_input
            col_roi, col_suggest = st.columns([1, 2])
            with col_roi:
                st.metric("實時損益率", f"{roi:+.2%}")
            with col_suggest:
                if roi < -0.07:
                    st.error("🛑 **操作建議：執行止損**。虧損已觸及 7% 紀律防線，建議優先回收資金。")
                elif current_rsi >= 80:
                    st.warning("🚨 **操作建議：逢高減碼**。RSI 已進入 80 以上極度超買區，隨時有獲利了結賣壓。")
                elif current_macd_up and current_rsi < 80:
                    st.success("✅ **操作建議：持股續抱**。動能持續向上且尚未進入過熱區，讓獲利奔跑。")
                else:
                    st.info("🔎 **操作建議：觀望整理**。目前趨勢不明顯，建議以成本價為防線。")
        else:
            st.info("請在左側輸入「持有成本」，以獲得個人化的精準操作建議。")

        # --- 5 日軌跡表格 ---
        st.subheader("📅 近 5 個交易日量化軌跡")
        table_df = pd.DataFrame({'交易日期': full_dates, '收盤價': d_data['closes'], 'MACD柱狀': hist, 'RSI(14)': rsi_vals}).drop_duplicates(subset=['交易日期'], keep='last').tail(5)
        st.table(table_df)
    else:
        st.error("❌ 無法抓取數據。")
