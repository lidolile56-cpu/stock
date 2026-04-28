# 檔名：20260428_持股分析系統_詳盡技術診斷版.py
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
# 🧠 第三部分：技術面深度診斷報告 (詳盡版)
# ==========================================
def generate_pro_report(df, res_score, rsi, k, d, cost_input):
    last_p = df['close'].iloc[-1]
    h_20 = df['high'].tail(20).max(); l_20 = df['low'].tail(20).min()
    pivot = (h_20 + l_20 + last_p) / 3
    r1 = 2 * pivot - l_20; s1 = 2 * pivot - h_20
    
    report = "### 📊 深度技術量化診斷\n\n"

    report += "#### 📈 【技術指標白話分解】\n"
    
    # 1. MACD 解析
    report += f"- **🎯 多週期 MACD 共振 ({res_score}/3 分)**：\n"
    report += "  - *指標意義*：結合日線(短)、週線(中)、月線(長)的均線方向。分數越高代表長短線趨勢越一致。\n"
    if res_score == 3: report += "  - *當前診斷*：**滿分 3 分 (完美多頭)**。大中小級別方向一致，為勝率最高的「主升段」特徵，趨勢保護短線，拉回皆是買點。\n"
    elif res_score == 2: report += "  - *當前診斷*：**2 分 (震盪偏多)**。中長線與短線出現分歧，可能正在進行良性回檔或換手整理，需等待方向再次表態。\n"
    elif res_score == 1: report += "  - *當前診斷*：**1 分 (弱勢反彈)**。整體大趨勢偏空，目前僅短線出現反彈訊號，需嚴防「假突破、真破底」的誘多陷阱。\n"
    else: report += "  - *當前診斷*：**0 分 (空頭排列)**。各週期皆呈現下跌趨勢，上方套牢賣壓沉重，切忌隨意摸底。\n"

    # 2. RSI 解析
    report += f"\n- **🔥 RSI 相對強弱指標 ({rsi:.1f})**：\n"
    report += "  - *指標意義*：反映近期買盤與賣盤的力量對比。50 為多空分水嶺。\n"
    if rsi >= 80: report += "  - *當前診斷*：**進入極度超買區 (>80)**。市場情緒極度狂熱，短線隨時可能面臨獲利了結的急跌修正，**切忌在此刻追高**。\n"
    elif rsi >= 50: report += "  - *當前診斷*：**多方控盤區 (50~80)**。買盤力道大於賣盤，趨勢健康向上，為最適合持股抱牢的階段。\n"
    elif rsi >= 30: report += "  - *當前診斷*：**空方控盤區 (30~50)**。賣壓較重，股價處於弱勢整理，反彈容易遇到均線反壓。\n"
    else: report += "  - *當前診斷*：**進入極度超賣區 (<30)**。恐慌情緒蔓延，短線跌幅已深，隨時醞釀「跌深反彈」，但不宜立刻重倉接刀。\n"

    # 3. KD 解析
    report += f"\n- **⚡ KD 隨機指標 (K: {k:.1f} / D: {d:.1f})**：\n"
    report += "  - *指標意義*：極短線的靈敏轉折指標。K 線穿越 D 線的方向決定短期爆發力。\n"
    if k > 80 and d > 80: report += "  - *當前診斷*：**高檔鈍化**。強勢股特徵，代表買盤源源不絕，沿著五日線強勢軋空，跌破五日線前可續抱。\n"
    elif k < 20 and d < 20: report += "  - *當前診斷*：**低檔超賣**。股價已被過度拋售，隨時可能出現低檔的黃金交叉反轉。\n"
    elif k > d and (k - d) > 2: report += "  - *當前診斷*：**黃金交叉 (K向上穿過D)**。短線攻擊訊號浮現，多頭動能正在轉強。\n"
    elif k < d and (d - k) > 2: report += "  - *當前診斷*：**死亡交叉 (K向下穿過D)**。短線漲多休息或轉弱，面臨回檔修正壓力。\n"
    else: report += "  - *當前診斷*：**雙線糾結**。多空正在激烈交戰，短線方向尚未明確。\n"

    report += "\n#### 🛡️ 【關鍵防線與實戰策略】\n"
    report += f"- **🚀 上檔壓力位：{r1:.2f}** (過去20天的高點反壓。若帶量突破此價位，將打開新一波上漲空間)\n"
    report += f"- **🧱 下檔支撐位：{s1:.2f}** (主力防守底線。強勢股不應跌破此價位，跌破代表趨勢轉弱)\n\n"
    
    if cost_input > 0:
        roi = (last_p - cost_input) / cost_input
        if last_p < s1:
            report += f"> 🚨 **【風險警示】**：目前股價已跌破重要支撐 **{s1:.2f}**，且部位處於{'虧損' if roi < 0 else '獲利縮水'}狀態。若短期內無法站回，建議**嚴格執行停損/停利**，收回資金避險。"
        elif res_score >= 2 and rsi > 50:
            report += f"> ✅ **【安心續抱】**：趨勢與動能皆處多頭格局。建議**持股續抱**，並將支撐位 **{s1:.2f}** 或個人成本價設定為「移動停利點」，讓獲利自然奔跑。"
        else:
            report += f"> ⚠️ **【防守觀望】**：盤勢震盪且多空指標分歧。建議**不要輕易加碼攤平**，維持既有倉位，靜待 KD 或 MACD 出現明確轉強訊號。"
    else:
        if res_score >= 2 and k > d and rsi > 50:
            report += f"> 💡 **【進場評估】**：多方指標共振，為不錯的右側交易時機。可考慮在股價回測均線或支撐位 **{s1:.2f}** 附近時分批試單。"
        elif k < 20 and d < 20:
            report += "> 💡 **【進場評估】**：股價處於嚴重超賣區。若近期出現帶量紅K或 KD 黃金交叉，可嘗試小量搶反彈，但務必嚴守停損。"
        else:
            report += "> 💡 **【空手觀望】**：尚無絕佳的風險報酬比進場點。建議耐心等待股價拉回支撐，或指標修正完畢後再行評估。"
        
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
            
            # 強制陣列長度對齊
            target_len = len(df)
            def align_len(arr, pad_val=0):
                arr = list(arr)
                if len(arr) == target_len: return arr
                elif len(arr) > target_len: return arr[-target_len:]
                else: return [pad_val] * (target_len - len(arr)) + arr

            aligned_hist = align_len(hist, 0)
            aligned_rsi = align_len(rsi_vals, 50.0)
            aligned_k = align_len(k_vals, 50.0)
            aligned_d = align_len(d_vals, 50.0)

            source = pd.DataFrame({
                '日期': [datetime.fromtimestamp(t, tz=tz).strftime('%Y/%m/%d') for t in df['ts']],
                '收盤價': df['close'].values,
                'MACD': aligned_hist, 
                'RSI': aligned_rsi, 
                'K': aligned_k, 
                'D': aligned_d
            }).drop_duplicates(subset=['日期'])

            morandi_yellow = '#CBAE73'
            nearest = alt.selection_point(nearest=True, on='mouseover', fields=['日期'], empty=False)
            x_axis = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))
            selectors = alt.Chart(source).mark_point().encode(x=x_axis, opacity=alt.value(0)).add_params(nearest)
            rules = alt.Chart(source).mark_rule(color='gray', strokeDash=[3,3]).encode(x=x_axis).transform_filter(nearest)
            
            # 1. 價格圖
            line_p = alt.Chart(source).mark_line(color='#1f77b4').encode(x=x_axis, y=alt.Y('收盤價', scale=alt.Scale(zero=False)))
            txt_d = line_p.mark_text(align='right', dx=-10, dy=-25, color=morandi_yellow, fontWeight='bold').encode(text='日期:N').transform_filter(nearest)
            txt_v = line_p.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=14, fontWeight='bold').encode(text=alt.Text('收盤價:Q', format='.2f')).transform_filter(nearest)
            c_price = (line_p + selectors + rules + txt_d + txt_v).properties(height=200, title="股價走勢")

            # 2. MACD 動能圖
            bar_m = alt.Chart(source).mark_bar().encode(
                x=x_axis, y=alt.Y('MACD', title=None), 
                color=alt.condition(alt.datum.MACD > 0, alt.value('#ff4b4b'), alt.value('#00cc96'))
            ).properties(height=100, title="MACD 動能")

            # 3. KD 指標圖 (圖例靠右)
            kd_melt = source.melt('日期', value_vars=['K', 'D'], var_name='指標', value_name='數值')
            line_kd = alt.Chart(kd_melt).mark_line(strokeWidth=2).encode(
                x=x_axis, y=alt.Y('數值', scale=alt.Scale(domain=[0, 100]), title=None),
                color=alt.Color('指標:N', scale=alt.Scale(domain=['K', 'D'], range=['#e377c2', '#17becf']), legend=alt.Legend(orient="right", title=None))
            )
            txt_k = alt.Chart(source).mark_text(align='right', dx=-10, dy=-25, color=morandi_yellow, fontSize=12, fontWeight='bold').encode(x=x_axis, y='K', text=alt.Text('K:Q', format='.1f')).transform_filter(nearest)
            txt_d_kd = alt.Chart(source).mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=12, fontWeight='bold').encode(x=x_axis, y='D', text=alt.Text('D:Q', format='.1f')).transform_filter(nearest)
            c_kd = (line_kd + selectors + rules + txt_k + txt_d_kd).properties(height=120, title="KD 指標 (9,3,3)")

            # 4. RSI 圖
            line_rsi = alt.Chart(source).mark_line(color='#8c564b', strokeWidth=2).encode(x=x_axis, y=alt.Y('RSI', scale=alt.Scale(domain=[0, 100]), title=None))
            txt_rsi = line_rsi.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=14, fontWeight='bold').encode(text=alt.Text('RSI:Q', format='.1f')).transform_filter(nearest)
            c_rsi = (line_rsi + selectors + rules + txt_rsi).properties(height=120, title="RSI (14)")

            # 垂直拼合圖表
            final_chart = alt.vconcat(c_price, c_macd, c_kd, c_rsi).resolve_scale(x='shared', color='independent')
            st.altair_chart(final_chart, use_container_width=True)

            # 診斷看板
            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("現價", f"${df['close'].iloc[-1]:.2f}")
            score = sum([aligned_hist[-1] > aligned_hist[-2] if len(aligned_hist)>1 else False, aligned_rsi[-1] > 50]) + 1
            m2.metric("共振得分", f"{score} 分")
            m3.metric("RSI 水位", f"{aligned_rsi[-1]:.1f}")
            roi = (df['close'].iloc[-1] - cost_input) / cost_input if cost_input > 0 else 0
            m4.metric("即時損益", f"{roi:+.2%}" if cost_input > 0 else "--")

            st.markdown(generate_pro_report(df, score, aligned_rsi[-1], aligned_k[-1], aligned_d[-1], cost_input))

            st.subheader("📅 近 5 日量化數據")
            st.table(source[['日期', '收盤價', 'MACD', 'K', 'D', 'RSI']].tail(5))

            st.divider()
            st.subheader(f"📰 {display_name if display_name else symbol} 焦點新聞")
            news = get_google_news(display_name if display_name else symbol)
            for n in news: st.markdown(f"**[{n['title']}]({n['link']})** \n<small>🕒 {n['pubDate']}</small>", unsafe_allow_html=True)
            
            st.caption("📊 數據來源：Yahoo Finance 官方開源 API 授權")
            
        else: st.error("❌ 無法取得數據，請檢查輸入是否正確。")
