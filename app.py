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

# 💡 核心佈局：左 2% 右 15% 非對稱防誤觸邊距
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
# 📊 第一部分：量化核心邏輯 (含進階指標)
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

# 💡 新增：模擬法人資金流向 (Money Flow Index)
def calculate_mfi(highs, lows, closes, volumes, period=14):
    if len(closes) < period + 1: return [50.0] * len(closes)
    tp = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    mf = [p * v for p, v in zip(tp, volumes)]
    mfi_series = [50.0] * period
    for i in range(period, len(mf)):
        pos_mf = sum(mf[j] for j in range(i-period+1, i+1) if tp[j] > tp[j-1])
        neg_mf = sum(mf[j] for j in range(i-period+1, i+1) if tp[j] < tp[j-1])
        mfi_series.append(100 - (100 / (1 + pos_mf / (neg_mf if neg_mf != 0 else 0.0001))))
    return mfi_series

# ==========================================
# 🌐 第二部分：數據採集與搜尋
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
        meta = result['meta']
        quote = result['indicators']['quote'][0]
        df = pd.DataFrame({
            'ts': result['timestamp'],
            'close': quote['close'],
            'high': quote['high'],
            'low': quote['low'],
            'vol': quote['volume']
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
            link = item.findtext('link', default='#')
            pubDate = item.findtext('pubDate', default='')
            title = raw_title.rsplit(" - ", 1)[0] if " - " in raw_title else raw_title
            news.append({'title': title, 'link': link, 'pubDate': pubDate[:16]})
    except: pass
    return news

# ==========================================
# 🧠 第三部分：深度診斷報告 (核心邏輯升級)
# ==========================================
def generate_pro_report(df, res_score, rsi, mfi, roi, cost_input):
    last_p = df['close'].iloc[-1]
    # 壓力支撐計算 (Pivot Points)
    h_20 = df['high'].tail(20).max()
    l_20 = df['low'].tail(20).min()
    pivot = (h_20 + l_20 + last_p) / 3
    r1 = 2 * pivot - l_20  # 近期壓力
    s1 = 2 * pivot - h_20  # 近期支撐
    
    report = "#### 🏛️ 1. 關鍵價位診斷\n"
    report += f"- **波段壓力位：{r1:.2f}** (向上突破則空間打開)\n"
    report += f"- **關鍵支撐位：{s1:.2f}** (強勢股回測不應跌破)\n"
    report += f"- **目前位階**：股價距離支撐約 {((last_p/s1)-1)*100:.1f}%，位階屬於{'偏高' if last_p > pivot else '打底'}區間。\n\n"
    
    report += "#### 💹 2. 籌碼動態 (模擬法人資金流 MFI)\n"
    if mfi > 70: report += f"- **MFI {mfi:.1f} (過熱)**：資金瘋狂湧入，法人鎖籌碼中，但需提防短線利多出盡。\n\n"
    elif mfi < 30: report += f"- **MFI {mfi:.1f} (超賣)**：資金持續流出，法人減碼，目前仍在尋找底部支撐。\n\n"
    else: report += f"- **MFI {mfi:.1f} (平穩)**：資金流向穩定，處於量價均勻的換手階段。\n\n"
    
    report += "#### 🎯 3. 綜合操作建議\n"
    if cost_input > 0:
        if last_p < s1: report += "> 🛑 **【執行警示】**：已跌破關鍵支撐，若明日無法站回，建議減碼保護資本。\n"
        elif res_score == 3 and mfi > 50: report += "> ✅ **【持股續抱】**：趨勢共振且資金進場，目標看向上方壓力位。\n"
        else: report += "> 🔎 **【守好防線】**：多空動能分歧，維持既有部位，嚴守成本價。\n"
    else:
        if res_score == 3 and mfi > 60: report += "> 💡 **【進場觀察】**：趨勢與資金同步轉強，可於回測支撐位時小量佈局。"
        else: report += "> 💡 **【耐心等待】**：目前尚未出現明確攻擊訊號，建議等待放量突破壓力位。"
    return report

# ==========================================
# 🚀 第四部分：介面渲染
# ==========================================
st.title("🌍 持股分析系統 PRO")
st.markdown("---")

c_input1, c_input2 = st.columns([3, 1])
with c_input1:
    stock_input = st.text_input("🔍 名稱/代碼", placeholder="輸入個股名稱或股號 (例: 2330)").strip()
with c_input2:
    cost_input = st.number_input("💰 持有成本", value=0.0)

if stock_input:
    with st.spinner('深度掃描市場數據中...'):
        symbol, display_name = search_ticker(stock_input)
        if not symbol: symbol = stock_input.upper() if stock_input.upper().endswith(('.TW', '.TWO')) else stock_input + ".TW"
        
        df, meta = get_stock_data(symbol)
        
        if df is not None:
            tz = timezone(timedelta(hours=8))
            closes = df['close'].tolist()
            is_tw = symbol.endswith(('.TW', '.TWO', '.TE'))
            
            # 指標計算
            dif, dea, hist = perform_macd_full(closes, is_tw)
            rsi_vals = calculate_rsi(closes)
            mfi_vals = calculate_mfi(df['high'].tolist(), df['low'].tolist(), closes, df['vol'].tolist())
            
            # 圖表準備
            source = pd.DataFrame({
                '日期': [datetime.fromtimestamp(t, tz=tz).strftime('%Y/%m/%d') for t in df['ts']],
                '收盤價': closes,
                'MACD': hist,
                'RSI': rsi_vals,
                'MFI': mfi_vals
            }).drop_duplicates(subset=['日期'])

            # 莫蘭迪黃色互動標籤
            nearest = alt.selection_point(nearest=True, on='mouseover', fields=['日期'], empty=False)
            x_axis = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))
            morandi_yellow = '#CBAE73'
            
            selectors = alt.Chart(source).mark_point().encode(x=x_axis, opacity=alt.value(0)).add_params(nearest)
            rules = alt.Chart(source).mark_rule(color='gray', strokeDash=[3,3]).encode(x=x_axis).transform_filter(nearest)

            # 1. 價格圖 (含壓力支撐可視化)
            line_p = alt.Chart(source).mark_line(color='#1f77b4').encode(x=x_axis, y=alt.Y('收盤價', scale=alt.Scale(zero=False)))
            txt_d = line_p.mark_text(align='right', dx=-10, dy=-25, color=morandi_yellow, fontWeight='bold').encode(text='日期:N').transform_filter(nearest)
            txt_v = line_p.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=14, fontWeight='bold').encode(text=alt.Text('收盤價:Q', format='.2f')).transform_filter(nearest)
            c_price = (line_p + selectors + rules + txt_d + txt_v).properties(height=220, title="股價走勢")

            # 2. MFI 法人資金流圖
            line_mfi = alt.Chart(source).mark_area(color='#ff7f0e', opacity=0.3).encode(x=x_axis, y=alt.Y('MFI', scale=alt.Scale(domain=[0, 100]), title="MFI"))
            txt_mfi = line_mfi.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontWeight='bold').encode(text=alt.Text('MFI:Q', format='.1f')).transform_filter(nearest)
            c_mfi = (line_mfi + selectors + rules + txt_mfi).properties(height=120, title="資金流向 (MFI)")

            # 3. MACD 動能圖
            bar_m = alt.Chart(source).mark_bar().encode(x=x_axis, y='MACD', color=alt.condition(alt.datum.MACD > 0, alt.value('#ff4b4b'), alt.value('#00cc96')))
            c_macd = (bar_m + selectors + rules).properties(height=120, title="MACD 動能")

            st.altair_chart(alt.vconcat(c_price, c_mfi, c_macd).resolve_scale(x='shared'), use_container_width=True)

            # 深度分析看板
            st.divider()
            h_up = hist[-1] > hist[-2] if len(hist)>1 else False
            # 模擬簡易共振分數
            score = 3 if (h_up and rsi_vals[-1] > 50) else (2 if h_up else 1)
            
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("現價", f"${closes[-1]:.2f}")
            m2.metric("資金流 MFI", f"{mfi_vals[-1]:.1f}")
            m3.metric("共振得分", f"{score} 分")
            roi = (closes[-1] - cost_input) / cost_input if cost_input > 0 else 0
            m4.metric("損益率", f"{roi:+.2%}" if cost_input > 0 else "空手")

            st.markdown(generate_pro_report(df, score, rsi_vals[-1], mfi_vals[-1], roi, cost_input))

            # 近期數據與新聞
            st.subheader("📅 歷史量化數據")
            st.table(source.tail(5))

            st.divider()
            st.subheader(f"📰 {display_name} 相關焦點新聞")
            news_items = get_google_news(display_name)
            if news_items:
                for n in news_items:
                    st.markdown(f"**[{n['title']}]({n['link']})** \n<small>🕒 {n['pubDate']}</small>", unsafe_allow_html=True)
            else: st.info("近期無重大相關新聞。")
        else: st.error("❌ 無法取得該標的數據，請檢查代碼後再試。")
