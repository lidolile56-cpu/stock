import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime, timezone, timedelta

# ==========================================
# 📊 第一部分：量化核心邏輯
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
    if avg_loss == 0: rsi_series.append(100.0)
    else: rsi_series.append(100.0 - (100.0 / (1.0 + (avg_gain / avg_loss))))
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i-1]
        gain, loss = max(0, diff), max(0, -diff)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0: rsi_series.append(100.0)
        else: rsi_series.append(100.0 - (100.0 / (1.0 + (avg_gain / avg_loss))))
    return rsi_series

# ==========================================
# 🌐 第二部分：數據採集 (🎯 破甲強制對位)
# ==========================================
@st.cache_data(ttl=15)
def get_verified_data(ticker, interval="1d", lookback="2y"):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={lookback}&_ts={int(time.time())}"
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
                c_ts.append(ts[i]); c_c.append(safe_float(raw_c[i]))
                c_h.append(safe_float(raw_h[i]) if raw_h[i] else safe_float(raw_c[i]))
                c_l.append(safe_float(raw_l[i]) if raw_l[i] else safe_float(raw_c[i]))
        
        # 🎯 強制補強：若收盤後 API 未結算，手動注入 4/20 年份日期
        tz_tw = timezone(timedelta(hours=8))
        now_tw = datetime.now(tz_tw)
        if live_price and c_ts:
            today_str = now_tw.strftime('%Y/%m/%d')
            last_date_str = datetime.fromtimestamp(c_ts[-1], tz=tz_tw).strftime('%Y/%m/%d')
            if today_str != last_date_str:
                c_ts.append(now_tw.timestamp()); c_c.append(live_price)
                c_h.append(max(live_price, c_h[-1])); c_l.append(min(live_price, c_l[-1]))
        return {'name': meta.get('symbol'), 'price': live_price, 'ath': max(c_h), 'atl': min(c_l), 
                'closes': c_c, 'highs': c_h, 'lows': c_l, 'ts': c_ts}
    except: return None

# ==========================================
# 🚀 第三部分：網頁介面與強制年份圖表
# ==========================================
st.set_page_config(page_title="量化導航系統-年份版", layout="wide")
st.title("🌍 全球量化導航系統 (2026/04/20 精確年份版)")

st.sidebar.header("🔍 查詢設定")
stock_input = st.sidebar.text_input("輸入代碼 (台股需加 .TW)", value="2330.TW").upper()
cost_input = st.sidebar.number_input("持有成本", value=0.0)

if stock_input:
    d_data = get_verified_data(stock_input)
    if d_data:
        tz_tw = timezone(timedelta(hours=8))
        # 💡 強制建立包含年份的日期清單
        dates_with_year = [datetime.fromtimestamp(t, tz=tz_tw).strftime('%Y/%m/%d') for t in d_data['ts']]
        
        # --- 1. 收盤價走勢圖 (含年份) ---
        st.subheader("📈 收盤價走勢 (YYYY/MM/DD)")
        price_df = pd.DataFrame({'日期': dates_with_year, '收盤價': d_data['closes']}).set_index('日期')
        st.line_chart(price_df)

        # --- 2. MACD 走勢圖 ---
        dif, dea, hist = perform_macd_full(d_data['closes'], ".TW" in stock_input)
        if dif:
            st.subheader("📊 MACD 指標 (DIF / DEA / 柱狀)")
            macd_df = pd.DataFrame({'日期': dates_with_year, 'DIF': dif, 'DEA': dea, '柱狀值': hist}).set_index('日期')
            st.line_chart(macd_df[['DIF', 'DEA']])
            st.bar_chart(macd_df['柱狀值'])

        # --- 3. RSI 走勢圖 ---
        rsi_vals = calculate_rsi(d_data['closes'])
        st.subheader("📉 RSI (14) 走勢圖")
        rsi_df = pd.DataFrame({'日期': dates_with_year, 'RSI': rsi_vals}).set_index('日期')
        st.line_chart(rsi_df)

        # --- 4. 結果分析表格 ---
        st.subheader("📅 近 5 個交易日量化數據 (強制年份格式)")
        report = []
        for i in range(-5, 0):
            try:
                m_now = hist[i]
                r_now = rsi_vals[i]
                report.append({
                    '交易日期': dates_with_year[i], 
                    '收盤價': round(d_data['closes'][i], 2), 
                    'MACD柱狀': round(m_now, 3), 
                    'RSI(14)': round(r_now, 1)
                })
            except: continue
        st.table(pd.DataFrame(report))

        if cost_input > 0:
            roi = (d_data['price'] - cost_input) / cost_input
            st.info(f"📊 截至 {dates_with_year[-1]}，您的實時損益：**{roi:+.2%}**")
    else:
        st.error("抓取失敗，請核對代碼。")
