# 檔名：20260428_持股分析系統_穩定版.py
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
# 🚀 網頁基本設定與 CSS 非對稱邊界優化
# ==========================================
st.set_page_config(page_title="持股分析系統 2026", layout="wide")

# 💡 核心佈局：左 2% 右 15% 的完美非對稱防誤觸邊距
st.markdown("""
    <style>
    .block-container {
        padding-top: 2rem !important; 
        padding-left: 2% !important;  
        padding-right: 15% !important; 
        max-width: 1200px;
    }
    a {
        text-decoration: none !important;
        color: #1f77b4 !important;
    }
    a:hover {
        text-decoration: underline !important;
    }
    /* 調整表格字體大小適合手機閱讀 */
    .stTable {
        font-size: 14px !important;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 📊 第一部分：量化核心邏輯
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

# ==========================================
# 🌐 第二部分：數據採集引擎 (搜尋 + K線 + 新聞)
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
def get_verified_data(ticker, interval="1d", range_val="2y"):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_val}&_ts={int(time.time())}"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200: return None
        json_data = res.json()
        result = json_data['chart']['result'][0]
        meta = result.get('meta', {})
        ts = result.get('timestamp', [])
        if not ts or len(ts) < 5: return None 
        tz_tw = timezone(timedelta(hours=8))
        if (datetime.now(tz_tw) - datetime.fromtimestamp(ts[-1], tz=tz_tw)).days > 30: return None
        quote = result.get('indicators', {}).get('quote', [{}])[0]
        raw_c = quote.get('close', [])
        c_ts, c_c = [], []
        for i in range(len(ts)):
            if raw_c[i] is not None:
                c_ts.append(ts[i]); c_c.append(float(raw_c[i]))
        live_price = meta.get('regularMarketPrice')
        if live_price is None and c_c: live_price = c_c[-1]
        if interval == "1d" and live_price and c_ts:
            if datetime.now(tz_tw).date() > datetime.fromtimestamp(c_ts[-1], tz=tz_tw).date():
                c_ts.append(datetime.now(tz_tw).timestamp()); c_c.append(live_price)
            else: c_c[-1] = live_price
        return {'closes': c_c, 'ts': c_ts, 'price': live_price, 'name': meta.get('longName') or ticker, 'symbol': meta.get('symbol')}
    except: return None

@st.cache_data(ttl=300)
def get_stock_news(name):
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
            if " - " in raw_title: title, publisher = raw_title.rsplit(" - ", 1)
            else: title, publisher = raw_title, item.findtext('source', default='市場新聞')
            pub_date_str = "近期發布"
            if pubDate:
                try:
                    dt = datetime.strptime(pubDate, "%a, %d %b %Y %H:%M:%S GMT")
                    pub_date_str = dt.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime('%Y/%m/%d %H:%M')
                except: pub_date_str = pubDate[:16] 
            news.append({'title': title, 'link': link, 'publisher': publisher, 'pubDate': pub_date_str})
    except: pass
    return news

# ==========================================
# 🧠 第三部分：深度診斷生成器
# ==========================================
def generate_detailed_report(res_score, rsi, roi, cost, is_held):
    report = "#### 🧭 1. 多週期趨勢診斷\n"
    if res_score == 3: report += "目前**月、週、日線 MACD 皆同步向上**（3 分）。資金共識達成，具備主升段特徵，趨勢延續性強。\n\n"
    elif res_score == 2: report += "共振得分 2 分，顯示**長短週期動能分歧**。此為震盪整理期，或良性回檔，走勢較顛簸。\n\n"
    elif res_score == 1: report += "得分僅 1 分，代表**僅短週期轉強**。大勢依然偏空，上漲多屬弱勢反彈，提防誘多。\n\n"
    else: report += "動能全面向下（0 分）。處於**空頭排列**，賣壓沉重且尚未見底，屬高風險區。\n\n"
    
    report += "#### ⚡ 2. 動能與風險水位 (RSI)\n"
    if rsi >= 80: report += f"當前 RSI 為 **{rsi:.1f}**，進入**「極度超買區」**。市場情緒極度狂熱，追高風險大，隨時面臨獲利了結壓力。\n\n"
    elif rsi >= 50: report += f"當前 RSI 為 **{rsi:.1f}**，穩居 **「多方優勢區」**。買盤強於賣盤，短期動能健康，尚未過熱。\n\n"
    else: report += f"當前 RSI 為 **{rsi:.1f}**，處於偏弱狀態。反彈易遇反壓，需等待突破 50 重新轉強。\n\n"
    
    report += "#### 🎯 3. 綜合實戰策略建議\n"
    if is_held:
        if roi < -0.07: report += f"> 🛑 **【執行止損】**：目前虧損已達 {roi:.2%}，觸及 7% 停損紀律線，建議回收資金避免深套。\n"
        elif res_score == 3 and rsi < 80: report += "> ✅ **【持股續抱】**：趨勢強勁且未見過熱，讓獲利奔跑，守住移動停利點即可。\n"
        else: report += "> 🔎 **【守好防線】**：多空動能分歧，建議依據持股成本嚴守支撐，觀望趨勢明朗。\n"
    else:
        report += "> 💡 **【空手觀察中】**："
        if res_score == 3 and rsi < 80: report += "趨勢明確向上，可尋找股價回測均線時伺機佈局。"
        else: report += "方向混沌或風險過高，建議等待共振得分提升或 RSI 回落後再行評估。"
    return report

# ==========================================
# 🚀 第四部分：介面與圖表渲染
# ==========================================
st.title("🌍 持股分析系統")
st.markdown("---")
search_col, cost_col = st.columns([3, 1])
with search_col:
    stock_input = st.text_input("🔍 名稱/代碼", value="", placeholder="輸入個股名稱或代碼 (例: 台積電, 3293)").strip()
with cost_col:
    cost_input = st.number_input("💰 持有成本", value=0.0)
st.markdown("---")

if stock_input:
    d_data = None
    with st.spinner(f'正在同步雲端數據與即時新聞...'):
        symbol, display_name = search_ticker(stock_input)
        if not symbol: symbol, display_name = stock_input.upper(), stock_input.upper()
        
        # 嘗試對應台灣後綴
        tickers_to_try = [symbol]
        if symbol.split('.')[0].isdigit():
            for sfx in ['.TW', '.TWO', '.TE']:
                if f"{symbol.split('.')[0]}{sfx}" not in tickers_to_try: tickers_to_try.append(f"{symbol.split('.')[0]}{sfx}")
        
        for t in tickers_to_try:
            d_data = get_verified_data(t, "1d", "2y")
            if d_data:
                wk_data = get_verified_data(t, "1wk", "max")
                mo_data = get_verified_data(t, "1mo", "max")
                break 

    if d_data:
        tz = timezone(timedelta(hours=8))
        is_tw = d_data['symbol'].endswith(('.TW', '.TWO', '.TE'))
        final_name = display_name if re.search(r'[\u4e00-\u9fff]', str(display_name)) else d_data['name']
        st.success(f"✅ 成功對位標的：{final_name} ({d_data['symbol']})")
        
        # 數據準備
        full_dates = [datetime.fromtimestamp(t, tz=tz).strftime('%Y/%m/%d') for t in d_data['ts']]
        dif, dea, hist = perform_macd_full(d_data['closes'], is_tw)
        rsi_vals = calculate_rsi(d_data['closes'])
        source = pd.DataFrame({'日期': full_dates, '收盤價': d_data['closes'], 'MACD柱狀': hist, 'RSI': rsi_vals}).drop_duplicates(subset=['日期'])

        # 💡 行動互動核心：莫蘭迪黃標籤 + 左側上方對齊
        nearest = alt.selection_point(nearest=True, on='mouseover', fields=['日期'], empty=False)
        x_axis = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))
        morandi_yellow = '#CBAE73'

        selectors = alt.Chart(source).mark_point().encode(x=x_axis, opacity=alt.value(0)).add_params(nearest)
        rules = alt.Chart(source).mark_rule(color='gray', strokeDash=[3,3]).encode(x=x_axis).transform_filter(nearest)

        # 1. 價格圖
        line_p = alt.Chart(source).mark_line(color='#1f77b4', strokeWidth=2).encode(x=x_axis, y=alt.Y('收盤價', scale=alt.Scale(zero=False), title=None))
        pts_p = line_p.mark_point(color='#1f77b4', size=60, filled=True).encode(opacity=alt.condition(nearest, alt.value(1), alt.value(0)))
        txt_d_p = line_p.mark_text(align='right', dx=-10, dy=-25, fontSize=12, fontWeight='bold', color=morandi_yellow).encode(text='日期:N').transform_filter(nearest)
        txt_v_p = line_p.mark_text(align='right', dx=-10, dy=-10, fontSize=14, fontWeight='bold', color=morandi_yellow).encode(text=alt.Text('收盤價:Q', format='.2f')).transform_filter(nearest)
        c_p = (line_p + selectors + rules + pts_p + txt_d_p + txt_v_p).properties(height=200, title="股價走勢")

        # 2. MACD 圖
        bar_m = alt.Chart(source).mark_bar().encode(x=x_axis, y=alt.Y('MACD柱狀', title=None), color=alt.condition(alt.datum['MACD柱狀'] > 0, alt.value('#ff4b4b'), alt.value('#00cc96')))
        txt_v_m = alt.Chart(source).mark_text(align='right', dx=-10, dy=-10, fontSize=14, fontWeight='bold', color=morandi_yellow).encode(x=x_axis, y=alt.Y('MACD柱狀'), text=alt.Text('MACD柱狀:Q', format='.3f')).transform_filter(nearest)
        c_m = (bar_m + selectors + rules + txt_v_m).properties(height=150, title="MACD 動能")

        # 3. RSI 圖
        line_r = alt.Chart(source).mark_line(color='#9467bd', strokeWidth=2).encode(x=x_axis, y=alt.Y('RSI', scale=alt.Scale(domain=[0, 100]), title=None))
        txt_v_r = line_r.mark_text(align='right', dx=-10, dy=-10, fontSize=14, fontWeight='bold', color=morandi_yellow).encode(text=alt.Text('RSI:Q', format='.1f')).transform_filter(nearest)
        c_r = (line_r + selectors + rules + txt_v_r).properties(height=150, title="RSI (14)")

        st.altair_chart(alt.vconcat(c_p, c_m, c_r).resolve_scale(x='shared'), use_container_width=True)

        # 診斷報告
        st.divider()
        st.subheader(f"💡 {final_name} 深度量化診斷報告")
        h_up = hist[-1] > hist[-2] if len(hist)>1 else False
        _, _, h_w = perform_macd_full(wk_data['closes'], is_tw) if wk_data else (0,0,[0,0])
        _, _, h_m = perform_macd_full(mo_data['closes'], is_tw) if mo_data else (0,0,[0,0])
        score = sum([h_up, (len(h_w)>1 and h_w[-1]>h_w[-2]), (len(h_m)>1 and h_m[-1]>h_m[-2])])
        
        m1, m2, m3 = st.columns(3)
        m1.metric("當前成交價", f"${d_data['price']}")
        roi = (d_data['price'] - cost_input) / cost_input if cost_input > 0 else 0
        m2.metric("即時損益率", f"{roi:+.2%}" if cost_input > 0 else "空手觀望")
        m3.metric("共振得分", f"{score} 分")
        
        st.markdown(generate_detailed_report(score, rsi_vals[-1], roi, cost_input, cost_input > 0))

        st.subheader("📅 近 5 個交易日軌跡")
        st.table(source.tail(5))

        # 即時新聞
        st.divider()
        st.subheader(f"📰 {final_name} 最新市場新聞")
        news = get_stock_news(final_name)
        if news:
            for n in news:
                st.markdown(f"**[{n['title']}]({n['link']})**")
                st.caption(f"🗞️ {n['publisher']} ｜ 🕒 {n['pubDate']}")
                st.write("")
        else: st.info("近期暫無相關新聞報導。")
        
    else: st.error(f"❌ 查無「{stock_input}」的數據，請確認名稱或代碼是否正確。")
else: st.info("💡 請在上方輸入個股名稱或代號（例：2330 或 台積電）以開始分析。")
