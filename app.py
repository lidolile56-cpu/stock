# 檔名：20260428_持股分析系統_純技術面版.py
import streamlit as st
import requests
import pandas as pd
import time
import altair as alt
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# ==========================================
# 🚀 網頁基本設定與 CSS 佈局
# ==========================================
st.set_page_config(page_title="持股分析系統 PRO", layout="wide")

# 💡 核心佈局：等比例加寬左右邊界，並確保標題單行顯示
st.markdown("""
    <style>
    .block-container { 
        padding-top: 2rem !important; 
        padding-left: 4% !important;   
        padding-right: 25% !important; 
        max-width: 1200px; 
    }
    a { text-decoration: none !important; color: #1f77b4 !important; }
    .stMetric { background-color: #fcfcfc; padding: 10px; border-radius: 10px; border: 1px solid #eee; }
    .stTable { font-size: 14px !important; }
    
    /* 確保標題絕對不換行，並隨螢幕自動縮小 */
    .responsive-title {
        white-space: nowrap;
        font-size: clamp(1.2rem, 5vw, 2.5rem);
        font-weight: bold;
        margin-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 📊 第一部分：量化核心邏輯 (長度防錯對齊)
# ==========================================
def calculate_ema(data, n):
    l = len(data)
    if l < n: return [data[-1]] * l
    alpha = 2 / (n + 1)
    res = [sum(data[:n])/n]
    for i in range(n, l):
        res.append(data[i] * alpha + res[-1] * (1 - alpha))
    return [res[0]] * (n - 1) + res

def perform_macd_full(closes, is_tw):
    l = len(closes)
    if l < 35: return [0]*l, [0]*l, [0]*l
    e12 = calculate_ema(closes, 12)
    e26 = calculate_ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = calculate_ema(dif, 9)
    hist = [(d - a) * (2.0 if is_tw else 1.0) for d, a in zip(dif, dea)]
    return dif, dea, hist

def calculate_rsi(closes, period=14):
    l = len(closes)
    if l < period: return [50.0] * l
    rsi_series = [50.0] * period
    avg_gain = sum(max(0, closes[i] - closes[i-1]) for i in range(1, period+1)) / period
    avg_loss = sum(max(0, closes[i-1] - closes[i]) for i in range(1, period+1)) / period
    for i in range(period, l):
        diff = closes[i] - closes[i-1]
        avg_gain = (avg_gain * (period - 1) + max(0, diff)) / period
        avg_loss = (avg_loss * (period - 1) + max(0, -diff)) / period
        rsi_val = 100.0 - (100.0 / (1.0 + (avg_gain / (avg_loss if avg_loss != 0 else 0.0001))))
        rsi_series.append(rsi_val)
    return rsi_series

def calculate_kd(highs, lows, closes, n=9):
    l = len(closes)
    if l < n: return [50.0]*l, [50.0]*l
    k_series, d_series = [50.0]*(n-1), [50.0]*(n-1)
    k, d = 50.0, 50.0
    for i in range(n-1, l):
        window_h = max(highs[i-n+1:i+1])
        window_l = min(lows[i-n+1:i+1])
        if window_h == window_l: rsv = 50.0
        else: rsv = (closes[i] - window_l) / (window_h - window_l) * 100.0
        k = (2/3) * k + (1/3) * rsv
        d = (2/3) * d + (1/3) * k
        k_series.append(k)
        d_series.append(d)
    return k_series, d_series

# ==========================================
# 🌐 第二部分：數據採集
# ==========================================
def search_ticker(query):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;query={urllib.parse.quote(query)}"
        res = requests.get(url, headers=headers, timeout=5).json()
        results = res.get('ResultSet', {}).get('Result', [])
        for r in results:
            sym = r.get('symbol', '')
            if sym.endswith(('.TW', '.TWO', '.TE')): return sym, r.get('name')
        if results: return results[0].get('symbol'), results[0].get('name')
    except: pass
    return None, None

@st.cache_data(ttl=10)
def get_stock_data(ticker):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2y"
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        result = res['chart']['result'][0]
        quote = result['indicators']['quote'][0]
        df = pd.DataFrame({
            'ts': result['timestamp'], 'close': quote['close'],
            'high': quote['high'], 'low': quote['low'], 'vol': quote['volume']
        }).dropna()
        return df, result['meta']
    except: return None, None

@st.cache_data(ttl=300)
def get_google_news(name):
    news = []
    try:
        query = urllib.parse.quote(f"{name} 股市")
        url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        res = requests.get(url, timeout=5)
        root = ET.fromstring(res.content)
        for item in root.findall('.//item')[:5]:
            title = item.findtext('title', default='無標題').rsplit(" - ", 1)[0]
            news.append({'title': title, 'link': item.findtext('link', default='#'), 'pubDate': item.findtext('pubDate', default='')[:16]})
    except: pass
    return news

# ==========================================
# 🧠 第三部分：技術面深度診斷報告
# ==========================================
def generate_pro_report(df, res_score, rsi, k, d, cost_input):
    last_p = df['close'].iloc[-1]
    h_20 = df['high'].tail(20).max(); l_20 = df['low'].tail(20).min()
    pivot = (h_20 + l_20 + last_p) / 3
    r1 = 2 * pivot - l_20; s1 = 2 * pivot - h_20
    
    report = "### 📊 深度技術量化診斷\n\n"

    report += "#### 📈 【技術面解密】\n"
    report += f"- **MACD 共振 ({res_score}/3 分)**：分數代表短中長期均線方向。**3分為完美多頭**，目前為 **{res_score} 分**。\n"
    report += f"- **RSI 動能 ({rsi:.1f})**：衡量買賣力道。**> 50 為多方強勢**，> 80 有過熱風險。目前為 **{rsi:.1f}**。\n"
    report += f"- **KD 指標 (K:{k:.1f} / D:{d:.1f})**：捕捉極短線轉折。"
    if k > 80 and d > 80: report += "目前處於 **高檔鈍化**，強勢股可能繼續軋空，但追高風險極大。\n\n"
    elif k < 20 and d < 20: report += "目前處於 **低檔超賣**，賣壓宣洩完畢，隨時醞釀反彈。\n\n"
    elif k > d and (k - d) > 3: report += "呈現 **黃金交叉 (K穿過D向上)**，短線動能轉強。\n\n"
    elif k < d and (d - k) > 3: report += "呈現 **死亡交叉 (K跌破D向下)**，短線有回檔修正壓力。\n\n"
    else: report += "目前雙線糾結，短線方向尚未明朗。\n\n"

    report += "#### 🛡️ 【防線與實戰策略】\n"
    report += f"- **短線壓力位：{r1:.2f}** (若放量突破此價位，上方空間將被打開)\n"
    report += f"- **關鍵支撐位：{s1:.2f}** (強勢股回測不應跌破的防守底線)\n\n"
    
    if cost_input > 0:
        if last_p < s1: report += f"> 🎯 **策略**：股價已跌破支撐 **{s1:.2f}**，若指標未見起色，建議嚴格停損或降低部位。"
        elif res_score >= 2: report += f"> 🎯 **策略**：技術指標健康，建議持股續抱，以支撐價 **{s1:.2f}** 作為移動停利點。"
        else: report += "> 🎯 **策略**：盤勢震盪，建議維持既有倉位，觀望後市方向突破。"
    else:
        report += "> 🎯 **空手觀望**：建議等待股價拉回至支撐位附近量縮測試不破時，再行分批佈局。"
        
    return report

# ==========================================
# 🚀 第四部分：主介面與全圖表互動渲染
# ==========================================
st.markdown('<div class="responsive-title">🌍 持股分析系統 PRO</div>', unsafe_allow_html=True)
st.markdown("---")

c_in1, c_in2 = st.columns([3, 1])
with c_in1: stock_input = st.text_input("🔍 名稱/代碼", placeholder="例如: 2330").strip()
with c_in2: cost_input = st.number_input("💰 持有成本", value=0.0)

if stock_input:
    with st.spinner('掃描量化數據中...'):
        symbol, display_name = search_ticker(stock_input)
        if not symbol: symbol = stock_input.upper() if stock_input.upper().endswith(('.TW', '.TWO')) else stock_input + ".TW"
        df, meta = get_stock_data(symbol)
        
        if df is not None:
            tz = timezone(timedelta(hours=8))
            is_tw = symbol.endswith(('.TW', '.TWO', '.TE'))
            
            _, _, hist = perform_macd_full(df['close'].tolist(), is_tw)
            rsi_vals = calculate_rsi(df['close'].tolist())
            k_vals, d_vals = calculate_kd(df['high'].tolist(), df['low'].tolist(), df['close'].tolist())
