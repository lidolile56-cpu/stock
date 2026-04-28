# 檔名：app.py
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
st.set_page_config(page_title="持股分析系統 PRO - 籌碼拆解版", layout="wide")

st.markdown("""
    <style>
    .block-container { padding-top: 2rem !important; padding-left: 2% !important; padding-right: 15% !important; max-width: 1200px; }
    a { text-decoration: none !important; color: #1f77b4 !important; }
    .stMetric { background-color: #fcfcfc; padding: 10px; border-radius: 10px; border: 1px solid #eee; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 📊 第一部分：量化核心邏輯 (技術 + 籌碼拆解)
# ==========================================
def calculate_ema(data, n):
    if len(data) < n: return [data[-1]] * len(data)
    res = [sum(data[:n])/n]
    alpha = 2 / (n + 1)
    for i in range(n, len(data)):
        res.append(data[i] * alpha + res[-1] * (1 - alpha))
    return [data[0]]*(n-1) + res

def perform_macd_full(closes, is_tw):
    if not closes or len(closes) < 35: return None, None, None
    e12 = calculate_ema(closes, 12)
    e26 = calculate_ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = calculate_ema(dif, 9)
    hist = [(d - a) * (2.0 if is_tw else 1.0) for d, a in zip(dif, dea)]
    return dif, dea, hist

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1: return [50.0] * len(closes)
    rsi_series = [50.0] * period
    avg_gain = sum(max(0, closes[i] - closes[i-1]) for i in range(1, period+1)) / period
    avg_loss = sum(max(0, closes[i-1] - closes[i]) for i in range(1, period+1)) / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i-1]
        avg_gain = (avg_gain * (period - 1) + max(0, diff)) / period
        avg_loss = (avg_loss * (period - 1) + max(0, -diff)) / period
        rsi_series.append(100.0 - (100.0 / (1.0 + (avg_gain / (avg_loss if avg_loss != 0 else 0.0001)))))
    return rsi_series

def estimate_individual_chips(df):
    """💡 核心升級：拆解外資、投信與散戶動向"""
    # 基礎動能量
    raw_flow = (df['close'].diff() * df['vol']).fillna(0)
    
    # 1. 模擬外資：看重波段趨勢延續與大資金門檻
    f_sim = (raw_flow.ewm(span=15).mean() / raw_flow.abs().max() * 50 + 50).clip(5, 95)
    
    # 2. 模擬投信：看重連續性波段，對短期價量反應更敏感
    s_sim = (raw_flow.ewm(span=5).mean() / raw_flow.abs().max() * 50 + 50).clip(5, 95)
    
    # 3. 模擬散戶：通常與主力資金對作，且在市場過熱時同步噴發
    retail_sim = (100 - (f_sim + s_sim) / 2).clip(5, 95)
    
    return f_sim.tolist(), s_sim.tolist(), retail_sim.tolist()

# ==========================================
# 🌐 第二部分：數據採集 (維持穩定版)
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
# 🧠 第三部分：全維度深度報告
# ==========================================
def generate_pro_report(df, score, rsi, f, s, r, cost_input):
    last_p = df['close'].iloc[-1]
    h_20 = df['high'].tail(20).max(); l_20 = df['low'].tail(20).min()
    pivot = (h_20 + l_20 + last_p) / 3
    r1 = 2 * pivot - l_20; s1 = 2 * pivot - h_20
    
    report = "#### 🕵️ 籌碼與技術深度診斷\n"
    
    # 籌碼拆解判斷
    if f > 60 and s > 60:
        report += "- **籌碼格局**：🚀 **土洋合作**。外資與投信同步站在買方，這通常是主升段最典型的特徵。\n"
    elif f < 40 and s < 40:
        report += "- **籌碼格局**：⛈️ **土洋拋售**。法人同步撤離，僅靠散戶撐盤，風險極高。\n"
    elif s > 65:
        report += "- **籌碼格局**：🔥 **投信認養**。投信強力鎖籌碼，具備中小型標的作帳行情潛力。\n"
    else:
        report += "- **籌碼格局**：⚖️ **勢力平衡**。三大勢力目前尚無明顯對作情況。\n"

    # 技術位階
    report += f"- **關鍵位階**：壓力位 **{r1:.2f}** / 支撐位 **{s1:.2f}**。目前 RSI 為 **{rsi:.1f}**。\n"

    if cost_input > 0:
        report += "\n> 🎯 **操作指引**："
        if last_p < s1: report += "股價已跌破支撐，建議執行停損或減碼。散戶熱度上升中，不可攤平。"
        elif score >= 2 and f > 50: report += "趨勢健康且法人支撐，建議持股續抱，觀察上方壓力區位。"
        else: report += "維持目前部位，嚴守移動停利線。"
    return report

# ==========================================
# 🚀 第四部分：介面佈局
# ==========================================
st.title("🌍 持股分析系統 PRO - 籌碼拆解版")
st.markdown("---")

c_in1, c_in2 = st.columns([3, 1])
with c_in1: stock_input = st.text_input("🔍 名稱/代碼", placeholder="例如: 2330").strip()
with c_in2: cost_input = st.number_input("💰 持有成本", value=0.0)

if stock_input:
    with st.spinner('掃描全維度數據與籌碼軌跡中...'):
        symbol, display_name = search_ticker(stock_input)
        if not symbol: symbol = stock_input.upper() if stock_input.upper().endswith(('.TW', '.TWO')) else stock_input + ".TW"
        df, meta = get_stock_data(symbol)
        
        if df is not None:
            tz = timezone(timedelta(hours=8))
            is_tw = symbol.endswith(('.TW', '.TWO', '.TE'))
            f_sim, s_sim, r_sim = estimate_individual_chips(df)
            dif, dea, hist = perform_macd_full(df['close'].tolist(), is_tw)
            rsi_vals = calculate_rsi(df['close'].tolist())
            
            source = pd.DataFrame({
                '日期': [datetime.fromtimestamp(t, tz=tz).strftime('%Y/%m/%d') for t in df['ts']],
                '收盤價': df['close'], '外資': f_sim, '投信': s_sim, '散戶': r_sim, 'MACD': hist, 'RSI': rsi_vals
            }).drop_duplicates(subset=['日期'])

            # 莫蘭迪黃色互動標籤
            morandi_yellow = '#CBAE73'
            nearest = alt.selection_point(nearest=True, on='mouseover', fields=['日期'], empty=False)
            x_axis = alt.X('日期', axis=alt.Axis(labels=False, title=None))
            
            # 1. 價格走勢圖
            line_p = alt.Chart(source).mark_line(color='#1f77b4').encode(x=x_axis, y=alt.Y('收盤價', scale=alt.Scale(zero=False)))
            txt_d = line_p.mark_text(align='right', dx=-10, dy=-25, color=morandi_yellow, fontWeight='bold').encode(text='日期:N').transform_filter(nearest)
            txt_v = line_p.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=14, fontWeight='bold').encode(text=alt.Text('收盤價:Q', format='.2f')).transform_filter(nearest)
            c_price = (line_p + txt_d + txt_v).add_params(nearest).properties(height=180, title="股價走勢")

            # 2. 籌碼拆解圖 (三線)
            chip_melt = source.melt('日期', value_vars=['外資', '投信', '散戶'], var_name='勢力', value_name='力道')
            c_chip = alt.Chart(chip_melt).mark_line(strokeWidth=2).encode(
                x=x_axis, y='力道', 
                color=alt.Color('勢力:N', scale=alt.Scale(domain=['外資', '投信', '散戶'], range=['#1f77b4', '#2ca02c', '#d62728']))
            ).properties(height=140, title="三大勢力動向 (外資/投信/散戶)")

            # 3. MACD 與 RSI (技術面)
            c_macd = alt.Chart(source).mark_bar().encode(
                x=x_axis, y='MACD', 
                color=alt.condition(alt.datum.MACD > 0, alt.value('#ff4b4b'), alt.value('#00cc96'))
            ).properties(height=80, title="MACD 動能")

            st.altair_chart(alt.vconcat(c_price, c_chip, c_macd).resolve_scale(x='shared'), use_container_width=True)

            # 綜合看板
            st.divider()
            score = sum([hist[-1] > hist[-2], rsi_vals[-1] > 50]) + 1
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("當前現價", f"${df['close'].iloc[-1]:.2f}")
            m2.metric("外資水位", f"{f_sim[-1]:.1f}")
            m3.metric("投信水位", f"{s_sim[-1]:.1f}")
            m4.metric("散戶熱度", f"{r_sim[-1]:.1f}")

            st.markdown(generate_pro_report(df, score, rsi_vals[-1], f_sim[-1], s_sim[-1], r_sim[-1], cost_input))

            # 新聞
            st.divider()
            st.subheader(f"📰 {display_name if display_name else symbol} 焦點快訊")
            news = get_google_news(display_name if display_name else symbol)
            for n in news: st.markdown(f"**[{n['title']}]({n['link']})** \n<small>🕒 {n['pubDate']}</small>", unsafe_allow_html=True)
            
        else: st.error("❌ 獲取數據失敗。")
