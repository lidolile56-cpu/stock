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
# 🚀 網頁基本設定與 CSS 佈局優化
# ==========================================
st.set_page_config(page_title="持股分析系統 PRO", layout="wide")

# 💡 核心佈局：左 2% 右 15% 非對稱邊距，避免單手操作誤觸
st.markdown("""
    <style>
    .block-container {
        padding-top: 2rem !important; 
        padding-left: 2% !important;  
        padding-right: 15% !important; 
        max-width: 1200px;
    }
    a { text-decoration: none !important; color: #1f77b4 !important; }
    .stMetric { background-color: #fcfcfc; padding: 10px; border-radius: 10px; border: 1px solid #eee; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 📊 第一部分：量化核心邏輯 (籌碼對作模擬引擎)
# ==========================================
def perform_macd_full(closes, is_tw):
    if not closes or len(closes) < 35: return None, None, None
    def calc_ema(data, n):
        if len(data) < n: return [data[-1]] * len(data)
        res = [sum(data[:n])/n]
        alpha = 2 / (n + 1)
        for i in range(n, len(data)):
            res.append(data[i] * alpha + res[-1] * (1 - alpha))
        return [data[0]]*(n-1) + res
    e12 = calc_ema(closes, 12)
    e26 = calc_ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = calc_ema(dif, 9)
    hist = [(d - a) * (2.0 if is_tw else 1.0) for d, a in zip(dif, dea)]
    return dif, dea, hist

def estimate_vs_chips(df):
    """
    💡 核心創新：模擬三大法人與散戶對作情況
    - 三大法人：以『價穩量增』與『連續趨勢』作為主力進場特徵。
    - 散戶：通常與趨勢反向（跌時攤平）或在市場熱度過高時追漲。
    """
    # 模擬法人：計算資金流入加權
    money_flow = (df['close'].diff() * df['vol']).ewm(span=10).mean()
    inst_sim = (money_flow / money_flow.abs().max() * 50 + 50).clip(5, 95)
    
    # 模擬散戶：利用反向指標邏輯與波動率修正
    retail_raw = 100 - inst_sim.rolling(window=3).mean()
    retail_sim = retail_raw.fillna(50).clip(5, 95)
    
    return inst_sim.tolist(), retail_sim.tolist()

# ==========================================
# 🌐 第二部分：數據採集與搜尋引擎
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
        meta = result.get('meta', {})
        quote = result['indicators']['quote'][0]
        df = pd.DataFrame({
            'ts': result['timestamp'],
            'close': quote['close'], 'high': quote['high'], 'low': quote['low'], 'vol': quote['volume']
        }).dropna()
        return df, meta
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
            raw_title = item.findtext('title', default='無標題')
            title = raw_title.rsplit(" - ", 1)[0] if " - " in raw_title else raw_title
            news.append({'title': title, 'link': item.findtext('link', default='#'), 'pubDate': item.findtext('pubDate', default='')[:16]})
    except: pass
    return news

# ==========================================
# 🧠 第三部分：深度對作分析診斷報告
# ==========================================
def generate_vs_report(df, inst, retail, cost_input):
    last_p = df['close'].iloc[-1]
    # 壓力支撐點位
    h_20 = df['high'].tail(20).max()
    l_20 = df['low'].tail(20).min()
    pivot = (h_20 + l_20 + last_p) / 3
    s1 = 2 * pivot - h_20 # 支撐線
    
    report = "#### ⚔️ 籌碼對作診斷\n"
    if inst > 58 and retail < 42:
        report += "- **目前格局**：🔥 **法人進、散戶退**。籌碼由散戶手中集中至法人大戶，這是最典型的「起漲強勢盤」，建議續抱。\n"
    elif inst < 42 and retail > 58:
        report += "- **目前格局**：⚠️ **法人跑、散戶接**。大戶正在撤退，散戶進場接刀，籌碼結構轉壞，需提防急跌風險。\n"
    else:
        report += "- **目前格局**：⚖️ **多空拉鋸**。法人與散戶動向出現重疊，預計進入窄幅區間震盪，等待方向明朗。\n"
    
    report += f"\n#### 🏛️ 關鍵防守位\n- **短線支撐：{s1:.2f}**。只要股價守住此位且法人買盤未連續縮減，多頭格局依然成立。\n"
    
    if cost_input > 0:
        roi = (last_p - cost_input) / cost_input
        if inst > 55: report += "\n> ✅ **策略建議**：法人籌碼尚未鬆動，目前位階安全，持股可繼續觀察目標價。"
        else: report += "\n> 🔎 **策略建議**：籌碼趨向不穩，建議降低持股成數，並以支撐位作為最後退場點。"
    return report

# ==========================================
# 🚀 第四部分：介面渲染與圖表
# ==========================================
st.title("🌍 持股分析系統 PRO")
st.markdown("---")

# 輸入區
c_in1, c_in2 = st.columns([3, 1])
with c_in1: 
    stock_input = st.text_input("🔍 名稱/代碼", placeholder="例如: 2330 或 台積電").strip()
with c_in2: 
    cost_input = st.number_input("💰 持有成本", value=0.0)

if stock_input:
    with st.spinner('掃描籌碼對作數據中...'):
        symbol, display_name = search_ticker(stock_input)
        if not symbol: 
            symbol = stock_input.upper() if stock_input.upper().endswith(('.TW', '.TWO')) else stock_input + ".TW"
        
        df, meta = get_stock_data(symbol)
        
        if df is not None:
            tz = timezone(timedelta(hours=8))
            is_tw = symbol.endswith(('.TW', '.TWO', '.TE'))
            inst_sim, retail_sim = estimate_vs_chips(df)
            
            source = pd.DataFrame({
                '日期': [datetime.fromtimestamp(t, tz=tz).strftime('%Y/%m/%d') for t in df['ts']],
                '收盤價': df['close'],
                '三大法人': inst_sim,
                '散戶': retail_sim
            }).drop_duplicates(subset=['日期'])

            # 莫蘭迪黃色互動標籤設定
            morandi_yellow = '#CBAE73'
            nearest = alt.selection_point(nearest=True, on='mouseover', fields=['日期'], empty=False)
            x_axis = alt.X('日期', axis=alt.Axis(labels=False, title=None))
            
            # 1. 價格圖 (標籤往左斜上方偏移)
            line_p = alt.Chart(source).mark_line(color='#1f77b4').encode(x=x_axis, y=alt.Y('收盤價', scale=alt.Scale(zero=False)))
            txt_d = line_p.mark_text(align='right', dx=-10, dy=-25, color=morandi_yellow, fontWeight='bold').encode(text='日期:N').transform_filter(nearest)
            txt_v = line_p.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=14, fontWeight='bold').encode(text=alt.Text('收盤價:Q', format='.2f')).transform_filter(nearest)
            c_price = (line_p + txt_d + txt_v).add_params(nearest).properties(height=200, title="股價走勢")

            # 2. 籌碼對作圖 (交叉訊號)
            chip_melt = source.melt('日期', value_vars=['三大法人', '散戶'], var_name='勢力', value_name='買賣水位')
            c_chip = alt.Chart(chip_melt).mark_line(strokeWidth=2.5).encode(
                x=x_axis, 
                y=alt.Y('買賣水位', scale=alt.Scale(domain=[0, 100]), title="籌碼水位"),
                color=alt.Color('勢力:N', scale=alt.Scale(domain=['三大法人', '散戶'], range=['#1f77b4', '#d62728']))
            ).properties(height=180, title="籌碼對作：三大法人 (藍) vs 散戶 (紅)")

            st.altair_chart(alt.vconcat(c_price, c_chip).resolve_scale(x='shared'), use_container_width=True)

            # 深度分析看板
            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("當前現價", f"${df['close'].iloc[-1]:.2f}")
            m2.metric("法人水位", f"{inst_sim[-1]:.1f}")
            m3.metric("散戶水位", f"{retail_sim[-1]:.1f}")
            roi = (df['close'].iloc[-1] - cost_input) / cost_input if cost_input > 0 else 0
            m4.metric("損益狀態", f"{roi:+.2%}" if cost_input > 0 else "空手觀望")

            st.markdown(generate_vs_report(df, inst_sim[-1], retail_sim[-1], cost_input))

            # 焦點新聞
            st.divider()
            st.subheader(f"📰 {display_name if display_name else symbol} 焦點新聞")
            news_items = get_google_news(display_name if display_name else symbol)
            if news_items:
                for n in news_items:
                    st.markdown(f"**[{n['title']}]({n['link']})** \n<small>🕒 {n['pubDate']}</small>", unsafe_allow_html=True)
            else: st.info("近期暫無重大新聞報導。")
            
        else: st.error("❌ 無法取得該標的數據，請確認名稱或代號是否正確。")
