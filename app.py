# 檔名：20260428_持股分析系統_官方數據對位版.py
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
# 📊 第一部分：量化核心邏輯 (長度防錯與 KD)
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
# 🛡️ 核心升級：官方數據對位引擎 (含容錯切換)
# ==========================================
def fetch_actual_chips(symbol):
    """嘗試從 FinMind 獲取官方三大法人數據，失敗則返回 None 以觸發模擬邏輯"""
    sid = symbol.split('.')[0]
    try:
        # 設定回推 30 天以獲取足夠的歷史數據
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={sid}&start_date={start_date}"
        res = requests.get(url, timeout=5).json()
        data = res.get('data', [])
        if not data: return None
        
        df_chip = pd.DataFrame(data)
        df_pivot = df_chip.pivot(index='date', columns='name', values='buy').fillna(0)
        # 將真實張數縮放至 0-100 以對齊 UI 線圖
        def scale_chip(series):
            return ((series - series.min()) / (series.max() - series.min() + 1) * 90 + 5).tolist()
        
        f_flow = scale_chip(df_pivot.get('Foreign_Investor', pd.Series([50]*len(df_pivot))))
        s_flow = scale_chip(df_pivot.get('Investment_Trust', pd.Series([50]*len(df_pivot))))
        return f_flow, s_flow, df_pivot.index.tolist()
    except:
        return None

def estimate_chip_flow(df):
    """原本的量價模擬模型 (容錯用備援邏輯)"""
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
# 🚀 第三部分：介面與全圖表互動渲染
# ==========================================
st.markdown('<div class="responsive-title">🌍 持股分析系統 PRO</div>', unsafe_allow_html=True)
st.markdown("---")

c_in1, c_in2 = st.columns([3, 1])
with c_in1: stock_input = st.text_input("🔍 名稱/代碼", placeholder="例如: 2330").strip()
with c_in2: cost_input = st.number_input("💰 持有成本", value=0.0)

if stock_input:
    with st.spinner('掃描官方與量化數據中...'):
        symbol, display_name = search_ticker(stock_input)
        if not symbol: symbol = stock_input.upper() if stock_input.upper().endswith(('.TW', '.TWO')) else stock_input + ".TW"
        df, meta = get_stock_data(symbol)
        
        if df is not None:
            tz = timezone(timedelta(hours=8))
            
            # --- 籌碼數據獲取 (雙軌制) ---
            actual_chips = fetch_actual_chips(symbol)
            is_actual = False
            if actual_chips:
                f_raw, s_raw, _ = actual_chips
                f_sim, s_sim = f_raw, s_raw
                r_sim = [100 - (f + s)/2 for f, s in zip(f_sim, s_sim)]
                is_actual = True
            else:
                f_sim, s_sim, r_sim = estimate_chip_flow(df)
            
            _, _, hist = perform_macd_full(df['close'].tolist(), True)
            rsi_vals = calculate_rsi(df['close'].tolist())
            k_vals, d_vals = calculate_kd(df['high'].tolist(), df['low'].tolist(), df['close'].tolist())
            
            # 陣列長度對齊
            target_len = len(df)
            def align_len(arr, pad_val=50.0):
                arr = list(arr)
                if len(arr) == target_len: return arr
                elif len(arr) > target_len: return arr[-target_len:]
                else: return [pad_val] * (target_len - len(arr)) + arr

            source = pd.DataFrame({
                '日期': [datetime.fromtimestamp(t, tz=tz).strftime('%Y/%m/%d') for t in df['ts']],
                '收盤價': df['close'].values,
                '外資': align_len(f_sim), '投信': align_len(s_sim), '散戶': align_len(r_sim),
                'MACD': align_len(hist, 0), 'RSI': align_len(rsi_vals), 'K': align_len(k_vals), 'D': align_len(d_vals)
            }).drop_duplicates(subset=['日期'])

            # 視覺與互動
            morandi_yellow = '#CBAE73'
            nearest = alt.selection_point(nearest=True, on='mouseover', fields=['日期'], empty=False)
            x_axis = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))
            selectors = alt.Chart(source).mark_point().encode(x=x_axis, opacity=alt.value(0)).add_params(nearest)
            rules = alt.Chart(source).mark_rule(color='gray', strokeDash=[3,3]).encode(x=x_axis).transform_filter(nearest)
            
            # 1. 價格
            c_price = (alt.Chart(source).mark_line(color='#1f77b4', strokeWidth=2).encode(x=x_axis, y=alt.Y('收盤價', scale=alt.Scale(zero=False))) + 
                       alt.Chart(source).mark_text(align='right', dx=-10, dy=-10, color=morandi_yellow, fontWeight='bold').encode(x=x_axis, y='收盤價', text=alt.Text('收盤價:Q', format='.2f')).transform_filter(nearest)).properties(height=200, title="股價走勢")

            # 2. 籌碼 (加上來源標記)
            chip_title = "三大勢力動向 (🟦外資 🟧投信 🟥散戶)" + (" - [官方真實數據]" if is_actual else " - [量價模擬動態]")
            chip_melt = source.melt('日期', value_vars=['外資', '投信', '散戶'], var_name='勢力', value_name='力道')
            c_chip = alt.Chart(chip_melt).mark_line(strokeWidth=2).encode(
                x=x_axis, y=alt.Y('力道', scale=alt.Scale(domain=[0, 100])),
                color=alt.Color('勢力:N', scale=alt.Scale(domain=['外資', '投信', '散戶'], range=['#1f77b4', '#ff7f0e', '#d62728']), legend=alt.Legend(orient="right", title=None))
            ).properties(height=150, title=chip_title)

            # 3. MACD/KD/RSI (圖例右置)
            c_macd = alt.Chart(source).mark_bar().encode(x=x_axis, y='MACD', color=alt.condition(alt.datum.MACD > 0, alt.value('#ff4b4b'), alt.value('#00cc96'))).properties(height=100, title="MACD 動能")
            
            kd_melt = source.melt('日期', value_vars=['K', 'D'], var_name='指標', value_name='數值')
            c_kd = alt.Chart(kd_melt).mark_line().encode(x=x_axis, y='數值', color=alt.Color('指標:N', scale=alt.Scale(domain=['K', 'D'], range=['#e377c2', '#17becf']), legend=alt.Legend(orient="right"))).properties(height=120, title="KD 指標")

            st.altair_chart(alt.vconcat(c_price, c_chip, c_macd, c_kd).resolve_scale(x='shared', color='independent'), use_container_width=True)

            # 診斷與看板
            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("現價", f"${df['close'].iloc[-1]:.2f}")
            m2.metric("官方數據狀態", "已同步" if is_actual else "模擬中")
            score = sum([source['MACD'].iloc[-1] > source['MACD'].iloc[-2], source['RSI'].iloc[-1] > 50]) + 1
            m3.metric("共振得分", f"{score} 分")
            roi = (df['close'].iloc[-1] - cost_input) / cost_input if cost_input > 0 else 0
            m4.metric("損益率", f"{roi:+.2%}" if cost_input > 0 else "--")

            # 新聞與來源
            st.subheader(f"📰 {display_name} 焦點新聞")
            news = get_google_news(display_name)
            for n in news: st.markdown(f"**[{n['title']}]({n['link']})** \n<small>🕒 {n['pubDate']}</small>", unsafe_allow_html=True)
            
            st.caption("📊 數據來源：Yahoo Finance / FinMind 官方資料庫 (三大法人買賣超數據於每日盤後更新)")
        else:
            st.error("❌ 無法取得數據。")
