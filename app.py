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

# 💡 核心佈局：左 2% 右 15% 非對稱邊距
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
    /* 調整表格字體大小適合手機閱讀 */
    .stTable { font-size: 14px !important; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 📊 第一部分：量化核心邏輯 (長度防錯對齊版)
# ==========================================
def calculate_ema(data, n):
    if len(data) < n: return [data[-1]] * len(data)
    alpha = 2 / (n + 1)
    res = [sum(data[:n])/n]
    for i in range(n, len(data)):
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
    if l < period + 1: return [50.0] * l
    rsi_series = [50.0] * period
    avg_gain = sum(max(0, closes[i] - closes[i-1]) for i in range(1, period+1)) / period
    avg_loss = sum(max(0, closes[i-1] - closes[i]) for i in range(1, period+1)) / period
    for i in range(period + 1, l):
        diff = closes[i] - closes[i-1]
        avg_gain = (avg_gain * (period - 1) + max(0, diff)) / period
        avg_loss = (avg_loss * (period - 1) + max(0, -diff)) / period
        rsi_val = 100.0 - (100.0 / (1.0 + (avg_gain / (avg_loss if avg_loss != 0 else 0.0001))))
        rsi_series.append(rsi_val)
    return rsi_series[:l]

def estimate_chip_flow(df):
    """模擬外資、投信、散戶個別籌碼動向"""
    l = len(df)
    raw_flow = (df['close'].diff() * df['vol']).fillna(0)
    max_f = raw_flow.abs().max() if raw_flow.abs().max() != 0 else 1
    
    # 1. 外資模擬 (趨勢延續大單)
    f_sim = (raw_flow.ewm(span=15).mean() / max_f * 50 + 50).clip(5, 95).tolist()
    # 2. 投信模擬 (連續性波段)
    s_sim = (raw_flow.ewm(span=5).mean() / max_f * 50 + 50).clip(5, 95).tolist()
    # 3. 散戶模擬 (市場過熱與對作)
    r_sim = [100 - (f + s)/2 for f, s in zip(f_sim, s_sim)]
    
    return f_sim[:l], s_sim[:l], r_sim[:l]

# ==========================================
# 🌐 第二部分：數據採集與新聞引擎
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
    
    try:
        fm_url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
        res = requests.get(fm_url, headers=headers, timeout=5).json()
        for item in res.get('data', []):
            sid, sname = item.get('stock_id'), item.get('stock_name', '')
            if query == sid or query in sname:
                stype = item.get('type')
                if stype == 'twse': return f"{sid}.TW", sname
                elif stype == 'tpex': return f"{sid}.TWO", sname
                elif stype == 'emerging': return f"{sid}.TE", sname
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
            'ts': result['timestamp'], 'close': quote['close'],
            'high': quote['high'], 'low': quote['low'], 'vol': quote['volume']
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
            pub_date_str = "近期發布"
            if pubDate:
                try:
                    dt = datetime.strptime(pubDate, "%a, %d %b %Y %H:%M:%S GMT")
                    pub_date_str = dt.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime('%Y/%m/%d %H:%M')
                except: pub_date_str = pubDate[:16] 
            news.append({'title': title, 'link': link, 'pubDate': pub_date_str})
    except: pass
    return news

# ==========================================
# 🧠 第三部分：全方位深度診斷報告
# ==========================================
def generate_combined_report(df, macd_score, rsi, f, s, r, cost_input):
    last_p = df['close'].iloc[-1]
    h_20 = df['high'].tail(20).max(); l_20 = df['low'].tail(20).min()
    pivot = (h_20 + l_20 + last_p) / 3
    r1 = 2 * pivot - l_20; s1 = 2 * pivot - h_20
    
    report = "#### 🕵️ 籌碼與技術深度診斷\n"
    # 籌碼判斷
    if f > 55 and s > 55: report += "- **籌碼格局**：🚀 **土洋大買**。外資與投信同步吸籌，多頭結構紮實，後市具爆發力。\n"
    elif f < 45 and s < 45: report += "- **籌碼格局**：⛈️ **主力撤退**。法人同步撤出，僅剩散戶熱度支撐，應提防高檔反轉。\n"
    elif s > 65: report += "- **籌碼格局**：🔥 **投信認養**。投信力道強勁，具備中小型標的作帳潛力。\n"
    else: report += "- **籌碼格局**：⚖️ **整理格局**。三大勢力目前動向趨於平穩。\n"

    # 技術判斷
    report += f"- **技術動能**：共振得分 **{macd_score} 分**。RSI 為 **{rsi:.1f}**，"
    if rsi >= 80: report += "處於**極度超買區**，短線追高風險大。\n"
    elif rsi >= 50: report += "穩居**多方優勢區**，動能健康。\n"
    else: report += "落入**偏弱狀態**，需等待突破 50 重新轉強。\n"

    # 價位判斷
    report += f"- **關鍵位階**：壓力 **{r1:.2f}** / 支撐 **{s1:.2f}**。目前價位距離支撐約 {((last_p/s1)-1)*100:.1f}%。\n"
    
    # 實戰建議
    if cost_input > 0:
        report += "\n> 🎯 **操作策略**："
        if last_p < s1: report += "股價已破支撐，建議降低部位避險，勿輕易攤平。"
        elif macd_score >= 2 and f > 50: report += "趨勢與籌碼結構健全，建議持股續抱，目標看向波段壓力位。"
        else: report += "盤勢震盪，嚴守移動停利線即可。"
    else:
        report += "\n> 💡 **空手觀察**："
        if macd_score == 3 and f > 50: report += "趨勢明確向上，可尋找股價回測均線時伺機佈局。"
        else: report += "方向混沌或風險過高，建議等待共振得分提升或 RSI 回落後再行評估。"
    return report

# ==========================================
# 🚀 第四部分：主介面與四重圖表渲染
# ==========================================
st.title("🌍 持股分析系統 PRO")
st.markdown("---")

c_in1, c_in2 = st.columns([3, 1])
with c_in1: stock_input = st.text_input("🔍 名稱/代碼", value="", placeholder="例如: 2330 或 台積電").strip()
with c_in2: cost_input = st.number_input("💰 持有成本", value=0.0)
st.markdown("---")

if stock_input:
    with st.spinner('掃描全維度量化數據中...'):
        symbol, display_name = search_ticker(stock_input)
        if not symbol: symbol = stock_input.upper() if stock_input.upper().endswith(('.TW', '.TWO', '.TE')) else stock_input + ".TW"
        df, meta = get_stock_data(symbol)
        
        if df is not None:
            tz = timezone(timedelta(hours=8))
            is_tw = symbol.endswith(('.TW', '.TWO', '.TE'))
            
            # 計算各項指標
            f_sim, s_sim, r_sim = estimate_chip_flow(df)
            _, _, hist = perform_macd_full(df['close'].tolist(), is_tw)
            rsi_vals = calculate_rsi(df['close'].tolist())
            
            # 強制對齊長度
            l_df = len(df)
            source = pd.DataFrame({
                '日期': [datetime.fromtimestamp(t, tz=tz).strftime('%Y/%m/%d') for t in df['ts']][:l_df],
                '收盤價': df['close'].values[:l_df],
                '外資': f_sim[:l_df], '投信': s_sim[:l_df], '散戶': r_sim[:l_df],
                'MACD': hist[:l_df], 'RSI': rsi_vals[:l_df]
            }).drop_duplicates(subset=['日期'])

            final_name = display_name if re.search(r'[\u4e00-\u9fff]', str(display_name)) else meta.get('longName') or symbol
            st.success(f"✅ 標的：{final_name} ({symbol}) ｜ {datetime.now(tz).strftime('%Y/%m/%d %H:%M')}")

            # 圖表互動與莫蘭迪美學設定
            morandi_yellow = '#CBAE73'
            nearest = alt.selection_point(nearest=True, on='mouseover', fields=['日期'], empty=False)
            x_axis = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))
            selectors = alt.Chart(source).mark_point().encode(x=x_axis, opacity=alt.value(0)).add_params(nearest)
            rules = alt.Chart(source).mark_rule(color='gray', strokeDash=[3,3]).encode(x=x_axis).transform_filter(nearest)
            
            # 1. 價格圖 (標籤左側偏上)
            line_p = alt.Chart(source).mark_line(color='#1f77b4', strokeWidth=2).encode(x=x_axis, y=alt.Y('收盤價', scale=alt.Scale(zero=False)))
            pts_p = line_p.mark_point(color='#1f77b4', size=60, filled=True).encode(opacity=alt.condition(nearest, alt.value(1), alt.value(0)))
            txt_d_p = line_p.mark_text(align='right', dx=-10, dy=-25, color=morandi_yellow, fontWeight='bold').encode(text='日期:N').transform_filter(nearest)
            txt_v_p = line_p.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=14, fontWeight='bold').encode(text=alt.Text('收盤價:Q', format='.2f')).transform_filter(nearest)
            c_price = (line_p + selectors + rules + pts_p + txt_d_p + txt_v_p).properties(height=200, title="股價走勢")

            # 2. 籌碼拆解圖 (三線)
            chip_melt = source.melt('日期', value_vars=['外資', '投信', '散戶'], var_name='勢力', value_name='力道')
            c_chip = alt.Chart(chip_melt).mark_line(strokeWidth=2).encode(
                x=x_axis, y=alt.Y('力道', scale=alt.Scale(domain=[0, 100]), title="籌碼動能"), 
                color=alt.Color('勢力:N', scale=alt.Scale(domain=['外資', '投信', '散戶'], range=['#1f77b4', '#2ca02c', '#d62728']))
            ).properties(height=140, title="三大勢力動向 (外資/投信/散戶)")

            # 3. MACD 圖
            bar_m = alt.Chart(source).mark_bar().encode(
                x=x_axis, y=alt.Y('MACD', title=None), 
                color=alt.condition(alt.datum.MACD > 0, alt.value('#ff4b4b'), alt.value('#00cc96'))
            )
            txt_v_m = alt.Chart(source).mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=14, fontWeight='bold').encode(x=x_axis, y='MACD', text=alt.Text('MACD:Q', format='.3f')).transform_filter(nearest)
            c_macd = (bar_m + selectors + rules + txt_v_m).properties(height=120, title="MACD 動能")

            # 4. RSI 圖
            line_r = alt.Chart(source).mark_line(color='#9467bd', strokeWidth=2).encode(x=x_axis, y=alt.Y('RSI', scale=alt.Scale(domain=[0, 100]), title=None))
            txt_v_r = line_r.mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontSize=14, fontWeight='bold').encode(text=alt.Text('RSI:Q', format='.1f')).transform_filter(nearest)
            c_rsi = (line_r + selectors + rules + txt_v_r).properties(height=120, title="RSI (14)")

            # 垂直拼合 4 張圖表
            st.altair_chart(alt.vconcat(c_price, c_chip, c_macd, c_rsi).resolve_scale(x='shared'), use_container_width=True)

            # 診斷看板
            st.divider()
            st.subheader(f"💡 {final_name} 深度量化診斷")
            h_up = hist[-1] > hist[-2] if len(hist)>1 else False
            score = sum([h_up, rsi_vals[-1] > 50]) + 1
            
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("當前現價", f"${df['close'].iloc[-1]:.2f}")
            m2.metric("外資水位", f"{f_sim[-1]:.1f}")
            m3.metric("投信水位", f"{s_sim[-1]:.1f}")
            roi = (df['close'].iloc[-1] - cost_input) / cost_input if cost_input > 0 else 0
            m4.metric("即時損益", f"{roi:+.2%}" if cost_input > 0 else "空手觀望")

            st.markdown(generate_combined_report(df, score, rsi_vals[-1], f_sim[-1], s_sim[-1], r_sim[-1], cost_input))

            # 歷史數據與新聞
            st.subheader("📅 近 5 日量化數據")
            st.table(source[['日期', '收盤價', '外資', '投信', '散戶', 'MACD', 'RSI']].tail(5))

            st.divider()
            st.subheader(f"📰 {final_name} 最新市場新聞")
            news = get_google_news(final_name)
            if news:
                for n in news: 
                    st.markdown(f"**[{n['title']}]({n['link']})** \n<small>🕒 {n['pubDate']}</small>", unsafe_allow_html=True)
            else: st.info("近期暫無相關新聞。")
            
        else: st.error("❌ 獲取數據失敗，請檢查輸入內容。")
