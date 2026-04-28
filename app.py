# 檔名：20260428_持股分析系統_極致渲染穩定版.py
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

# 💡 核心佈局：等比例加寬左右邊界，確保標題自適應
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
    
    .responsive-title {
        white-space: nowrap;
        font-size: clamp(1.2rem, 5vw, 2.5rem);
        font-weight: bold;
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

    report += "#### 📈 【技術指標白話分解】\n"
    
    report += f"- **🎯 多週期 MACD 共振 ({res_score}/3 分)**：\n"
    report += "  - *指標意義*：結合短、中、長的均線方向。分數越高代表趨勢越一致。\n"
    if res_score == 3: report += "  - *當前診斷*：**滿分 3 分 (完美多頭)**。大中小級別方向一致，趨勢保護短線，拉回皆是買點。\n"
    elif res_score == 2: report += "  - *當前診斷*：**2 分 (震盪偏多)**。中長線與短線出現分歧，可能正在進行良性回檔或換手整理。\n"
    elif res_score == 1: report += "  - *當前診斷*：**1 分 (弱勢反彈)**。整體趨勢偏空，目前僅短線出現反彈訊號，需嚴防誘多陷阱。\n"
    else: report += "  - *當前診斷*：**0 分 (空頭排列)**。各週期皆呈現下跌趨勢，上方賣壓沉重，切忌隨意摸底。\n"

    report += f"\n- **🔥 RSI 相對強弱指標 ({rsi:.1f})**：\n"
    report += "  - *指標意義*：反映近期買盤與賣盤力量對比。50 為多空分水嶺。\n"
    if rsi >= 80: report += "  - *當前診斷*：**極度超買 (>80)**。市場情緒狂熱，短線隨時面臨獲利了結急跌，切忌追高。\n"
    elif rsi >= 50: report += "  - *當前診斷*：**多方控盤 (50~80)**。買盤力道大於賣盤，趨勢健康向上。\n"
    elif rsi >= 30: report += "  - *當前診斷*：**空方控盤 (30~50)**。股價弱勢整理，反彈易遇反壓。\n"
    else: report += "  - *當前診斷*：**極度超賣 (<30)**。恐慌情緒蔓延，短線跌幅深，隨時醞釀跌深反彈。\n"

    report += f"\n- **⚡ KD 隨機指標 (K: {k:.1f} / D: {d:.1f})**：\n"
    report += "  - *指標意義*：極短線靈敏轉折指標。K 穿過 D 的方向決定短期爆發力。\n"
    if k > 80 and d > 80: report += "  - *當前診斷*：**高檔鈍化**。買盤源源不絕強勢軋空，跌破五日線前可續抱。\n"
    elif k < 20 and d < 20: report += "  - *當前診斷*：**低檔超賣**。股價過度拋售，隨時可能出現黃金交叉反轉。\n"
    elif k > d and (k - d) > 2: report += "  - *當前診斷*：**黃金交叉 (K穿過D向上)**。短線攻擊訊號浮現，多頭動能轉強。\n"
    elif k < d and (d - k) > 2: report += "  - *當前診斷*：**死亡交叉 (K跌破D向下)**。短線漲多休息或轉弱，面臨回檔壓力。\n"
    else: report += "  - *當前診斷*：**雙線糾結**。多空交戰中，短線方向未明。\n"

    report += "\n#### 🛡️ 【防線與實戰策略】\n"
    report += f"- **短線壓力位：{r1:.2f}** (若帶量突破此價位，上方上漲空間將打開)\n"
    report += f"- **關鍵支撐位：{s1:.2f}** (強勢股回測不應跌破的防守底線)\n\n"
    
    if cost_input > 0:
        if last_p < s1: report += f"> 🚨 **【風險警示】**：股價已跌破支撐 **{s1:.2f}**，若短期內無法站回，建議嚴格執行停損/停利，收回資金避險。"
        elif res_score >= 2 and rsi > 50: report += f"> ✅ **【安心續抱】**：趨勢與動能皆處多頭格局。建議持股續抱，以支撐位 **{s1:.2f}** 作為移動停利點。"
        else: report += "> ⚠️ **【防守觀望】**：盤勢震盪，建議不輕易加碼攤平，維持既有倉位，靜待指標明確轉強。"
    else:
        if res_score >= 2 and k > d and rsi > 50: report += f"> 💡 **【進場評估】**：多方共振，為不錯的右側交易時機，可考慮回測支撐位 **{s1:.2f}** 附近分批試單。"
        elif k < 20 and d < 20: report += "> 💡 **【進場評估】**：股價處於嚴重超賣區。若近期出現帶量紅K或黃金交叉，可嘗試小量搶反彈，嚴守停損。"
        else: report += "> 💡 **【空手觀望】**：尚無絕佳風險報酬比進場點。建議耐心等待拉回支撐或指標修正。"
        
    return report

# ==========================================
# 🚀 第四部分：主介面與極致防錯圖表渲染
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
            
            target_len = len(df)
            def align_len(arr, pad_val=0):
                arr = list(arr)
                if len(arr) == target_len: return arr
                elif len(arr) > target_len: return arr[-target_len:]
                else: return [pad_val] * (target_len - len(arr)) + arr

            # 組裝完美長度的 DataFrame
            source = pd.DataFrame({
                '日期': [datetime.fromtimestamp(t, tz=tz).strftime('%Y/%m/%d') for t in df['ts']],
                '收盤價': df['close'].values,
                'MACD': align_len(hist, 0), 
                'RSI': align_len(rsi_vals, 50.0), 
                'K': align_len(k_vals, 50.0), 
                'D': align_len(d_vals, 50.0)
            }).drop_duplicates(subset=['日期'])

            morandi_yellow = '#CBAE73'
            
            # 💡 核心修復：強制定義 X 軸為 Temporal (時間連續軸:T)
            # 這能徹底解決因為 Nominal 分類軸擠爆而造成的「4個大空白」當機問題！
            x_axis = alt.X('日期:T', axis=alt.Axis(labels=False, title=None, ticks=False))
            nearest = alt.selection_point(nearest=True, on='mouseover', fields=['日期'], empty=False)
            
            selectors = alt.Chart(source).mark_point().encode(x=x_axis, opacity=alt.value(0)).add_params(nearest)
            rules = alt.Chart(source).mark_rule(color='gray', strokeDash=[3,3]).encode(x=x_axis).transform_filter(nearest)
            
            # 1. 價格圖
            line_p = alt.Chart(source).mark_line(color='#1f77b4', strokeWidth=2).encode(x=x_axis, y=alt.Y('收盤價:Q', scale=alt.Scale(zero=False)))
            txt_d = line_p.mark_text(align='right', dx=-10, dy=-25, color=morandi_yellow, fontWeight='bold').encode(
                text=alt.Text('日期:T', timeUnit='yearmonthdate', format='%Y/%m/%d')
            ).transform_filter(nearest)
            txt_v = line_p.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=14, fontWeight='bold').encode(
                text=alt.Text('收盤價:Q', format='.2f')
            ).transform_filter(nearest)
            c_price = (line_p + selectors + rules + txt_d + txt_v).properties(height=200, title="股價走勢")

            # 2. MACD 動能圖
            bar_m = alt.Chart(source).mark_bar().encode(
                x=x_axis, y=alt.Y('MACD:Q', title=None), 
                color=alt.condition(alt.datum.MACD > 0, alt.value('#ff4b4b'), alt.value('#00cc96'))
            )
            txt_m = bar_m.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=12, fontWeight='bold').encode(
                text=alt.Text('MACD:Q', format='.3f')
            ).transform_filter(nearest)
            c_macd = (bar_m + selectors + rules + txt_m).properties(height=100, title="MACD 動能 (🔴正 / 🟢負)")

            # 3. KD 指標圖 (💡 捨棄 Legend，改用純線條疊加與標題提示，確保左右寬度絕對對齊不破版)
            line_k = alt.Chart(source).mark_line(color='#e377c2', strokeWidth=2).encode(x=x_axis, y=alt.Y('K:Q', scale=alt.Scale(domain=[0, 100])))
            line_d = alt.Chart(source).mark_line(color='#17becf', strokeWidth=2).encode(x=x_axis, y=alt.Y('D:Q', scale=alt.Scale(domain=[0, 100])))
            
            txt_k = line_k.mark_text(align='right', dx=-10, dy=-25, color=morandi_yellow, fontSize=12, fontWeight='bold').encode(text=alt.Text('K:Q', format='.1f')).transform_filter(nearest)
            txt_d_kd = line_d.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=12, fontWeight='bold').encode(text=alt.Text('D:Q', format='.1f')).transform_filter(nearest)
            
            c_kd = (line_k + line_d + selectors + rules + txt_k + txt_d_kd).properties(height=120, title="KD 指標 (🟣K線 / 🔵D線)")

            # 4. RSI 圖
            line_rsi = alt.Chart(source).mark_line(color='#8c564b', strokeWidth=2).encode
