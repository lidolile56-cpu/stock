# 檔名：20150420 MACD + RSI 完整說明版.py
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
        gain, loss = max(0, diff), max(0, -diff)
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
            m_now, m_pre = hist[i], hist[i-1]
            status = ("🔴紅柱" if m_now > 0 else "🟢綠柱") + ("放大" if m_now > m_pre else "縮減")
            r_val = rsi[i]
            r_status = "🔥 超買" if r_val >= 80 else "❄️ 超賣" if r_val <= 20 else "📈 多方" if r_val >= 50 else "📉 空方"
            p_range = highs[i] - lows[i]
            pos = ((closes[i] - lows[i]) / p_range * 100) if p_range > 0 else 50
            tz_tw = timezone(timedelta(hours=8))
            # 💡 關鍵更新：日期格式包含完整年份
            dt = datetime.fromtimestamp(timestamps[i], tz=tz_tw).strftime('%Y/%m/%d') 
            report.append({
                '交易日期': dt, '收盤價': round(closes[i], 2), '位階': f"{pos:.1f}%", 
                'MACD柱狀': round(m_now, 3), '動能': status, 'RSI(14)': round(r_val, 1), 'RSI狀態': r_status,
                'macd_up': m_now > m_pre, 'rsi_val': r_val
            })
        except: continue
    return report

# ==========================================
# 🌐 第三部分：數據採集 (含強制年份補強與快取穿透)
# ==========================================
@st.cache_data(ttl=10) # 僅快取 10 秒，確保即時性
def get_verified_data(ticker, interval="1d", lookback="2y"):
    headers = {'User-Agent': 'Mozilla/5.0', 'Cache-Control': 'no-cache'}
    # 加入隨機參數防止 Yahoo 回傳舊數據
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
        
        # 💡 強制補強：若最後一根 K 線日期不是今天，強制注入即時數據
        tz_tw = timezone(timedelta(hours=8))
        now_tw = datetime.now(tz_tw)
        if live_price and c_ts:
            today_str = now_tw.strftime('%Y/%m/%d')
            last_date_str = datetime.fromtimestamp(c_ts[-1], tz=tz_tw).strftime('%Y/%m/%d')
            if today_str != last_date_str:
                c_ts.append(now_tw.timestamp())
                c_c.append(live_price)
                c_h.append(max(live_price, c_h[-1]))
                c_l.append(min(live_price, c_l[-1]))
            else:
                c_c[-1] = live_price # 日期對了就直接更新最新價

        return {'name': meta.get('symbol'), 'price': live_price, 'ath': max(c_h), 'atl': min(c_l), 
                'closes': c_c, 'highs': c_h, 'lows': c_l, 'ts': c_ts}
    except: return None

# ==========================================
# 🚀 第四部分：網頁介面
# ==========================================
st.set_page_config(page_title="量化導航系統", layout="wide")
st.title("🌍 全球多週期量化導航系統 (2026/04/20 版)")
st.markdown(f"📊 **系統對時：{datetime.now(timezone(timedelta(hours=8))).strftime('%Y/%m/%d %H:%M:%S')}**")

st.sidebar.header("🔍 查詢設定")
stock_input = st.sidebar.text_input("代碼 (例: 2330.TW)", value="2330.TW").upper()
cost_input = st.sidebar.number_input("持有成本", value=0.0)

if stock_input:
    d_data = get_verified_data(stock_input)
    mo_data = get_verified_data(stock_input, interval="1mo", lookback="max")
    wk_data = get_verified_data(stock_input, interval="1wk", lookback="max")

    if d_data:
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric(f"📊 {d_data['name']} 當前價", f"${d_data['price']}")
            hist_pos = ((d_data['price']-d_data['atl'])/(d_data['ath']-d_data['atl'])*100)
            st.metric("歷史位階", f"{hist_pos:.1f}%")
        
        with col2:
            st.subheader("📈 價格趨勢 (含年份)")
            tz_tw = timezone(timedelta(hours=8))
            chart_df = pd.DataFrame({
                '日期': [datetime.fromtimestamp(t, tz=tz_tw).strftime('%Y/%m/%d') for t in d_data['ts']],
                '收盤價': d_data['closes']
            }).set_index('日期')
            st.line_chart(chart_df)

        st.subheader("📅 近 5 個交易日量化軌跡 (精確日期)")
        history = analyze_indicators_5day(d_data['closes'], d_data['highs'], d_data['lows'], d_data['ts'], True)
        if history:
            st.table(pd.DataFrame(history).drop(columns=['macd_up', 'rsi_val']))
            
            # 共振得分解析
            mo_up = (perform_macd_analysis(mo_data['closes'], True)[-1] > perform_macd_analysis(mo_data['closes'], True)[-2]) if mo_data else False
            wk_up = (perform_macd_analysis(wk_data['closes'], True)[-1] > perform_macd_analysis(wk_data['closes'], True)[-2]) if wk_data else False
            resonance_score = sum([history[-1]['macd_up'], wk_up, mo_up])
            st.subheader(f"🧠 實時共振得分：{ {3:'🟢 3 分', 2:'🟡 2 分', 1:'🟠 1 分', 0:'🔴 0 分'}[resonance_score] }")

            if cost_input > 0:
                roi = (d_data['price'] - cost_input) / cost_input
                st.info(f"📊 實時損益：**{roi:+.2%}**")
    else:
        st.error("數據抓取失敗，請確認代碼後綴 (.TW)")
