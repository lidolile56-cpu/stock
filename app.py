# 檔名：20260428_持股分析系統_最終修復版.py
import streamlit as st
import requests
import pandas as pd
import time
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# ==========================================
# 🚀 網頁基本設定與 CSS 佈局
# ==========================================
st.set_page_config(page_title="持股分析系統 PRO", layout="wide")

# 💡 加寬邊距，優化閱讀體驗
st.markdown("""
    <style>
    .block-container { 
        padding-top: 1.5rem !important; 
        padding-left: 5% !important;   
        padding-right: 15% !important; 
        max-width: 1100px; 
    }
    .stMetric { background-color: #fcfcfc; padding: 10px; border-radius: 10px; border: 1px solid #eee; }
    /* 標題強制縮小單行不切割 */
    .custom-title {
        font-size: 24px !important;
        font-weight: bold;
        color: #31333F;
        white-space: nowrap;
        margin-bottom: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 📊 第一部分：量化核心邏輯
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
    e12 = calculate_ema(closes, 12); e26 = calculate_ema(closes, 26)
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
        window_h = max(highs[i-n+1:i+1]); window_l = min(lows[i-n+1:i+1])
        rsv = (closes[i] - window_l) / (window_h - window_l) * 100.0 if window_h != window_l else 50.0
        k = (2/3) * k + (1/3) * rsv
        d = (2/3) * d + (1/3) * k
        k_series.append(k); d_series.append(d)
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
def generate_pro_report(score, rsi, k, d, cost, last_p, r1, s1):
    report = "### 📊 深度技術量化診斷\n\n"
    report += "#### 📈 【技術指標白話分解】\n"
    
    report += f"- **🎯 多週期 MACD 共振 ({score}/3 分)**：\n"
    if score == 3: report += "  - *診斷*：**滿分 (完美多頭)**。大中小週期同步向上，趨勢極強。\n"
    elif score == 2: report += "  - *診斷*：**2 分 (震盪偏多)**。中長線與短線分歧，等待方向再次表態。\n"
    else: report += "  - *診斷*：**低分 (弱勢格局)**。大趨勢仍偏空，提防反彈無力。\n"

    report += f"\n- **🔥 RSI 強弱指標 ({rsi:.1f})**：\n"
    if rsi >= 75: report += "  - *診斷*：**超買過熱**。買盤狂熱，隨時有獲利了結壓力，切忌追高。\n"
    elif rsi >= 50: report += "  - *診斷*：**多方控盤**。買盤強於賣盤，趨勢健康向上。\n"
    else: report += "  - *診斷*：**弱勢整理**。賣壓較重，需等待站回 50 分水嶺。\n"

    report += f"\n- **⚡ KD 隨機指標 (K:{k:.1f} / D:{d:.1f})**：\n"
    if k > d: report += "  - *診斷*：**黃金交叉**。短線動能增強，具備上攻力道。\n"
    else: report += "  - *診斷*：**死亡交叉**。短線動能轉弱，面臨回檔修正。\n"

    report += f"\n#### 🛡️ 【關鍵防線】\n- **🚀 壓力位：{r1:.2f}** ｜ **🧱 支撐位：{s1:.2f}**\n"
    
    if cost > 0:
        if last_p < s1: report += f"\n> 🚨 **策略建議**：已跌破支撐 **{s1:.2f}**，建議嚴格執行避險，保留資金。"
        else: report += f"\n> ✅ **策略建議**：守住支撐位 **{s1:.2f}** 即可持股續抱，讓獲利奔跑。"
    return report

# ==========================================
# 🚀 第四部分：主介面 (修復標題與空白框)
# ==========================================
st.markdown('<div class="custom-title">🌍 持股分析系統 PRO</div>', unsafe_allow_html=True)

c_in1, c_in2 = st.columns([3, 1])
with c_in1: stock_input = st.text_input("🔍 名稱/代碼", placeholder="例如: 2330").strip()
with c_in2: cost_input = st.number_input("💰 持有成本", value=0.0)

if stock_input:
    with st.spinner('掃描數據中...'):
        symbol, display_name = search_ticker(stock_input)
        if not symbol: symbol = stock_input.upper() if stock_input.upper().endswith(('.TW', '.TWO')) else stock_input + ".TW"
        df, meta = get_stock_data(symbol)
        
        if df is not None:
            # 計算指標
            tz = timezone(timedelta(hours=8))
