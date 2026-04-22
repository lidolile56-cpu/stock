# 檔名：20150422 MACD + RSI 終極校準版.py
import streamlit as st
import requests
import pandas as pd
import time
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
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i-1]
        avg_gain = (avg_gain * (period - 1) + max(0, diff)) / period
        avg_loss = (avg_loss * (period - 1) + max(0, -diff)) / period
        rsi_series.append(100.0 - (100.0 / (1.0 + (avg_gain / (avg_loss if avg_loss != 0 else 0.0001)))))
    return rsi_series

# ==========================================
# 🌐 第二部分：數據採集 (🎯 徹底解決日期重複問題)
# ==========================================
@st.cache_data(ttl=10)
def get_verified_data(ticker):
    headers = {'User-Agent': 'Mozilla/5.0'}
    # 加入隨機參數防止 Yahoo 快取
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2y&_ts={int(time.time())}"
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        result = res.get('chart', {}).get('result', [])[0]
        meta = result.get('meta', {})
        live_price = meta.get('regularMarketPrice')
        ts = result.get('timestamp', [])
        quote = result.get('indicators', {}).get('quote', [{}])[0]
        raw_c, raw_h, raw_l = quote.get('close', []), quote.get('high', []), quote.get('low', [])
        
        c_ts, c_c, c_h, c_l = [], [], [], []
        for i in range(len(ts)):
            if raw_c[i] is not None:
                c_ts.append(ts[i]); c_c.append(float(raw_c[i]))
                c_h.append(float(raw_h[i]) if raw_h[i] else float(raw_c[i]))
                c_l.append(float(raw_l[i]) if raw_l[i] else float(raw_c[i]))

        # 💡 修正日期重複的核心邏輯
        tz_tw = timezone(timedelta(hours=8))
        now_tw = datetime.now(tz_tw)
        if live_price and c_ts:
            today_date = now_tw.date()
            last_k_date = datetime.fromtimestamp(c_ts[-1], tz=tz_tw).date()
            
            if today_date > last_k_date: 
                # 只有當今天日期大於陣列最後日期時，才新增一列
                c_ts.append(now_tw.timestamp()); c_c.append(live_price)
                c_h.append(max(live_price, c_h[-1])); c_l.append(min(live_price, c_l[-1]))
            else:
                # 否則只更新最後一筆的即時價格，不准新增
                c_c[-1] = live_price
                c_h[-1] = max(c_h[-1], live_price); c_l[-1] = min(c_l[-1], live_price)

        return {'name': meta.get('symbol'), 'price': live_price, 'ath': max(c_h), 'atl': min(c_l), 
                'closes': c_c, 'highs': c_h, 'lows': c_l, 'ts': c_ts}
    except: return None

# ==========================================
# 🚀 第三部分：網頁介面 (新增產製時間標註)
# ==========================================
st.set_page_config(page_title="量化導航 2026", layout="wide")
st.title("🌍 全球量化導航系統 (精確時間與年份版)")

st.sidebar.header("🔍 查詢設定")
stock_input = st.sidebar.text_input("輸入股票代碼 (例: 2330.TW)", value="2330.TW").upper()
cost_input = st.sidebar.number_input("持有成本 (0 代表觀望)", value=0.0)

if stock_input:
    # 紀錄產製時間
    tz_tw = timezone(timedelta(hours=8))
    report_time = datetime.now(tz_tw).strftime('%Y/%m/%d %H:%M:%S')
    
    d_data = get_verified_data(stock_input)
    if d_data:
        # 💡 顯現日期跟時間：在報告最醒目的地方
        st.success(f"✅ 分析完成！報告產製時間：{report_time}")
        
        full_dates = [datetime.fromtimestamp(t, tz=tz_tw).strftime('%Y/%m/%d') for t in d_data['ts']]
        
        # --- 走勢圖表與年份顯示 ---
        st.subheader("📈 收盤價走勢 (包含年份)")
        price_df = pd.DataFrame({'日期': full_dates, '收盤價': d_data['closes']}).drop_duplicates(subset=['日期']).set_index('日期')
        st.line_chart(price_df)

        # --- MACD 與 RSI 圖表 ---
        dif, dea, hist = perform_macd_full(d_data['closes'], ".TW" in stock_input)
        rsi_vals = calculate_rsi(d_data['closes'])
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📊 MACD 柱狀與曲線")
            macd_df = pd.DataFrame({'日期': full_dates, 'DIF': dif, 'DEA': dea, '柱狀': hist}).drop_duplicates(subset=['日期']).set_index('日期')
            st.line_chart(macd_df[['DIF', 'DEA']])
            st.bar_chart(macd_df['柱狀'])
        with col2:
            st.subheader("📉 RSI (14) 走勢")
            rsi_df = pd.DataFrame({'日期': full_dates, 'RSI': rsi_vals}).drop_duplicates(subset=['日期']).set_index('日期')
            st.line_chart(rsi_df)

        # --- 近 5 日軌跡 (強制去重並顯示年份) ---
        st.subheader("📅 近 5 個交易日量化軌跡")
        table_df = pd.DataFrame({
            '交易日期': full_dates,
            '收盤價': d_data['closes'],
            'MACD柱狀': hist,
            'RSI(14)': rsi_vals
        }).drop_duplicates(subset=['交易日期'], keep='last').tail(5)
        st.table(table_df)

        if cost_input > 0:
            roi = (d_data['price'] - cost_input) / cost_input
            st.info(f"💰 持有成本：{cost_input} ｜ 📊 實時損益：**{roi:+.2%}** (更新至 {report_time})")
    else:
        st.error("❌ 無法抓取數據。請檢查代碼格式。")
