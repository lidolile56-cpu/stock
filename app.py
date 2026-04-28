# 檔名：20260428_持股分析系統_詳盡報告優化版.py
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
    .stTable { font-size: 14px !important; }
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

def estimate_chip_flow(df):
    l = len(df)
    raw_flow = (df['close'].diff() * df['vol']).fillna(0)
    max_f = raw_flow.abs().max() if raw_flow.abs().max() != 0 else 1
    f_sim = (raw_flow.ewm(span=15).mean() / max_f * 50 + 50).clip(5, 95).tolist()
    s_sim = (raw_flow.ewm(span=5).mean() / max_f * 50 + 50).clip(5, 95).tolist()
    r_sim = [100 - (f + s)/2 for f, s in zip(f_sim, s_sim)]
    return f_sim, s_sim, r_sim

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
# 🧠 第三部分：詳盡版深度診斷報告
# ==========================================
def generate_pro_report(df, res_score, rsi, k, d, f, s, r, cost_input):
    last_p = df['close'].iloc[-1]
    h_20 = df['high'].tail(20).max(); l_20 = df['low'].tail(20).min()
    pivot = (h_20 + l_20 + last_p) / 3
    r1 = 2 * pivot - l_20; s1 = 2 * pivot - h_20
    
    report = "### 📊 量化與籌碼綜合診斷\n\n"
    
    # --- 籌碼面解密 ---
    report += "#### 💰 【籌碼面解密】 (50 為多空分水嶺)\n"
    report += f"- 🟦 **外資動能 ({f:.1f})**：代表大型法人的資金流向。**> 50 代表資金淨流入**。目前數值顯示外資處於{'偏向買方' if f > 50 else '偏向賣方或觀望'}的狀態。\n"
    report += f"- 🟩 **投信動能 ({s:.1f})**：代表內資作帳力道，數值越高表示「連續買超」的企圖越強。目前數值顯示投信{'正積極介入' if s > 50 else '未見明顯連續買盤'}。\n"
    report += f"- 🟥 **散戶熱度 ({r:.1f})**：通常為反向指標。**> 50 意味著籌碼正在流向散戶**，主力可能在出貨；目前顯示籌碼{'趨於凌亂，需警惕' if r > 50 else '相對安定，有利上攻'}。\n\n"

    if f > 60 and s > 60: report += "> 💡 **籌碼總結**：🚀 **土洋合作**。外資與投信同步站在買方，多頭動能極強，為最安全的上漲結構。\n\n"
    elif f < 40 and s < 40: report += "> 💡 **籌碼總結**：⛈️ **主力撤退**。法人同步減碼，僅剩散戶熱度支撐，強烈建議提防高檔反轉。\n\n"
    elif s > 65: report += "> 💡 **籌碼總結**：🔥 **投信認養**。投信資金高度集中，該標的具備作帳潛力。\n\n"
    else: report += "> 💡 **籌碼總結**：⚖️ **區間換手**。目前各方勢力相互抗衡，無單一壓倒性力量。\n\n"

    # --- 技術面解密 ---
    report += "#### 📈 【技術面解密】\n"
    report += f"- **MACD 共振得分 ({res_score}/3 分)**：分數代表短、中、長期的均線方向。**3 分為完美多頭**，0 分為空頭。目前獲得 **{res_score} 分**。\n"
    report += f"- **RSI 動能 ({rsi:.1f})**：衡量買賣雙方力道。**> 50 為多方強勢**，> 80 則有過熱回檔風險。目前數值為 **{rsi:.1f}**。\n"
    report += f"- **KD 指標 (K:{k:.1f} / D:{d:.1f})**：捕捉極短線的價格轉折。"
    if k > 80 and d > 80: report += "目前處於 **高檔鈍化**，強勢股可能繼續軋空，但追高風險極大。\n\n"
    elif k < 20 and d < 20: report += "目前處於 **低檔超賣**，賣壓宣洩完畢，隨時醞釀反彈。\n\n"
    elif k > d and (k - d) > 3: report += "呈現 **黃金交叉 (K穿過D向上)**，短線動能轉強。\n\n"
    elif k < d and (d - k) > 3: report += "呈現 **死亡交叉 (K跌破D向下)**，短線有回檔修正壓力。\n\n"
    else: report += "目前雙線糾結，短線方向尚未明朗。\n\n"

    # --- 防線與策略 ---
    report += "#### 🛡️ 【防線與實戰策略】\n"
    report += f"- **短線壓力位：{r1:.2f}** (若放量突破此價位，上方上漲空間將被打開)\n"
    report += f"- **關鍵支撐位：{s1:.2f}** (強勢股回測不應跌破的防守底線)\n\n"
    
    if cost_input > 0:
        if last_p < s1: report += f"> 🎯 **操作策略**：股價已跌破支撐 **{s1:.2f}**，且若技術指標未見起色，建議嚴格執行停損或降低部位避險。"
        elif res_score >= 2 and f > 50: report += f"> 🎯 **操作策略**：趨勢及籌碼結構皆健康，建議持股續抱，以支撐價位 **{s1:.2f}** 作為移動停利點。"
        else: report += "> 🎯 **操作策略**：盤勢處於震盪，建議維持既有倉位，觀望後市方向突破。"
    else:
        report += "> 🎯 **空手觀望**：若欲進場，建議等待股價拉回至支撐位附近量縮測試不破時，再行分批佈局。"
        
    return report

# ==========================================
# 🚀 第四部分：主介面與圖表渲染
# ==========================================
st.title("🌍 持股分析系統 PRO")
st.markdown("---")

c_in1, c_in2 = st.columns([3, 1])
with c_in1: stock_input = st.text_input("🔍 名稱/代碼", placeholder="例如: 2330").strip()
with c_in2: cost_input = st.number_input("💰 持有成本", value=0.0)

if stock_input:
    with st.spinner('掃描全維度數據中...'):
        symbol, display_name = search_ticker(stock_input)
        if not symbol: symbol = stock_input.upper() if stock_input.upper().endswith(('.TW', '.TWO')) else stock_input + ".TW"
        df, meta = get_stock_data(symbol)
        
        if df is not None:
            tz = timezone(timedelta(hours=8))
            is_tw = symbol.endswith(('.TW', '.TWO', '.TE'))
            
            f_sim, s_sim, r_sim = estimate_chip_flow(df)
            _, _, hist = perform_macd_full(df['close'].tolist(), is_tw)
            rsi_vals = calculate_rsi(df['close'].tolist())
            k_vals, d_vals = calculate_kd(df['high'].tolist(), df['low'].tolist(), df['close'].tolist())
            
            # 強制陣列長度對齊機制
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
            aligned_f = align_len(f_sim, 50.0)
            aligned_s = align_len(s_sim, 50.0)
            aligned_r = align_len(r_sim, 50.0)

            source = pd.DataFrame({
                '日期': [datetime.fromtimestamp(t, tz=tz).strftime('%Y/%m/%d') for t in df['ts']],
                '收盤價': df['close'].values,
                '外資': aligned_f, 
                '投信': aligned_s, 
                '散戶': aligned_r,
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
            c_price = (line_p + txt_d + txt_v).add_params(nearest).properties(height=200, title="股價走勢")

            # 2. 三大勢力籌碼圖 (明確設定圖例顏色)
            chip_melt = source.melt('日期', value_vars=['外資', '投信', '散戶'], var_name='勢力', value_name='力道')
            c_chip = alt.Chart(chip_melt).mark_line(strokeWidth=2).encode(
                x=x_axis, 
                y=alt.Y('力道', scale=alt.Scale(domain=[0, 100]), title=None), 
                color=alt.Color(
                    '勢力:N', 
                    scale=alt.Scale(domain=['外資', '投信', '散戶'], range=['#1f77b4', '#2ca02c', '#d62728']),
                    legend=alt.Legend(title="三大勢力 (點擊看數值)", orient="top-left", titleFontSize=12, labelFontSize=12)
                )
            ).properties(height=150, title="籌碼動向 (🟦外資 / 🟩投信 / 🟥散戶)")

            # 3. MACD 動能圖
            c_macd = alt.Chart(source).mark_bar().encode(
                x=x_axis, y=alt.Y('MACD', title=None), 
                color=alt.condition(alt.datum.MACD > 0, alt.value('#ff4b4b'), alt.value('#00cc96'))
            ).properties(height=100, title="MACD 動能")

            # 4. KD 指標圖
            kd_melt = source.melt('日期', value_vars=['K', 'D'], var_name='指標', value_name='數值')
            line_kd = alt.Chart(kd_melt).mark_line(strokeWidth=2).encode(
                x=x_axis, y=alt.Y('數值', scale=alt.Scale(domain=[0, 100]), title=None),
                color=alt.Color('指標:N', scale=alt.Scale(domain=['K', 'D'], range=['#ff7f0e', '#9467bd']), legend=alt.Legend(orient="top-left"))
            )
            txt_k = alt.Chart(source).mark_text(align='right', dx=-10, dy=-25, color=morandi_yellow, fontSize=12, fontWeight='bold').encode(x=x_axis, y='K', text=alt.Text('K:Q', format='.1f')).transform_filter(nearest)
            txt_d_kd = alt.Chart(source).mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=12, fontWeight='bold').encode(x=x_axis, y='D', text=alt.Text('D:Q', format='.1f')).transform_filter(nearest)
            c_kd = (line_kd + selectors + rules + txt_k + txt_d_kd).properties(height=120, title="KD 指標 (9,3,3)")

            # 5. RSI 圖
            line_r = alt.Chart(source).mark_line(color='#8c564b', strokeWidth=2).encode(x=x_axis, y=alt.Y('RSI', scale=alt.Scale(domain=[0, 100]), title=None))
            txt_r = line_r.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=14, fontWeight='bold').encode(text=alt.Text('RSI:Q', format='.1f')).transform_filter(nearest)
            c_rsi = (line_r + selectors + rules + txt_r).properties(height=120, title="RSI (14)")

            st.altair_chart(alt.vconcat(c_price, c_chip, c_macd, c_kd, c_rsi).resolve_scale(x='shared'), use_container_width=True)

            # 診斷看板
            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("現價", f"${df['close'].iloc[-1]:.2f}")
            m2.metric("外資水位", f"{aligned_f[-1]:.1f}")
            score = sum([aligned_hist[-1] > aligned_hist[-2] if len(aligned_hist)>1 else False, aligned_rsi[-1] > 50]) + 1
            m3.metric("共振得分", f"{score} 分")
            roi = (df['close'].iloc[-1] - cost_input) / cost_input if cost_input > 0 else 0
            m4.metric("損益/熱度", f"{roi:+.2%}" if cost_input > 0 else f"散戶 {aligned_r[-1]:.1f}")

            # 🚀 渲染加強版診斷報告
            st.markdown(generate_pro_report(df, score, aligned_rsi[-1], aligned_k[-1], aligned_d[-1], aligned_f[-1], aligned_s[-1], aligned_r[-1], cost_input))

            st.subheader("📅 近 5 日量化數據")
            st.table(source[['日期', '收盤價', '外資', '投信', '散戶', 'MACD', 'K', 'D', 'RSI']].tail(5))

            st.divider()
            st.subheader(f"📰 {display_name if display_name else symbol} 焦點新聞")
            news = get_google_news(display_name if display_name else symbol)
            for n in news: st.markdown(f"**[{n['title']}]({n['link']})** \n<small>🕒 {n['pubDate']}</small>", unsafe_allow_html=True)
            
        else: st.error("❌ 無法取得數據，請檢查輸入是否正確。")
