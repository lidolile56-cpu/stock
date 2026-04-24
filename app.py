# 檔名：20150424 MACD + RSI 終極互動版.py
import streamlit as st
import requests
import pandas as pd
import time
import altair as alt
import re
import urllib.parse
from datetime import datetime, timezone, timedelta

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
# 🌐 第二部分：搜尋與數據採集
# ==========================================
def search_ticker(query):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;query={urllib.parse.quote(query)}"
        res = requests.get(url, headers=headers, timeout=5).json()
        results = res.get('ResultSet', {}).get('Result', [])
        for r in results:
            sym = r.get('symbol', '')
            if sym.endswith('.TW') or sym.endswith('.TWO') or sym.endswith('.TE'):
                return sym, r.get('name')
        if results: return results[0].get('symbol'), results[0].get('name')
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

# ==========================================
# 🚀 第三部分：網頁介面與互動圖表
# ==========================================
st.set_page_config(page_title="量化導航 2026", layout="wide")
st.title("🌍 全球量化導航系統")

# 頂部查詢列
search_col, cost_col = st.columns([3, 1])
with search_col:
    stock_input = st.text_input("🔍 名稱/代碼", value="", placeholder="輸入個股名稱或股號").strip()
with cost_col:
    cost_input = st.number_input("💰 持有成本", value=0.0)

if stock_input:
    d_data, wk_data, mo_data = None, None, None
    found_symbol, display_name = None, None

    with st.spinner(f'同步數據中...'):
        found_symbol, display_name = search_ticker(stock_input)
        if not found_symbol:
            found_symbol = stock_input.upper()
            display_name = stock_input.upper()

        if found_symbol:
            base_symbol = found_symbol.split('.')[0]
            tickers_to_try = [found_symbol]
            if base_symbol.isdigit():
                for sfx in ['.TW', '.TWO', '.TE']:
                    t = f"{base_symbol}{sfx}"
                    if t not in tickers_to_try: tickers_to_try.append(t)
            
            for t in tickers_to_try:
                d_data = get_verified_data(t, "1d", "2y")
                if d_data:
                    wk_data = get_verified_data(t, "1wk", "max")
                    mo_data = get_verified_data(t, "1mo", "max")
                    break 

    if d_data:
        tz_tw = timezone(timedelta(hours=8))
        report_time = datetime.now(tz_tw).strftime('%Y/%m/%d %H:%M:%S')
        is_tw = d_data['symbol'].endswith('.TW') or d_data['symbol'].endswith('.TWO') or d_data['symbol'].endswith('.TE')
        
        final_name = display_name if re.search(r'[\u4e00-\u9fff]', str(display_name)) else d_data['name']
        display_label = f"{final_name} ({d_data['symbol']})"
        st.success(f"✅ 標的：{display_label} ｜ {report_time}")
        
        # 準備數據與指標
        full_dates = [datetime.fromtimestamp(t, tz=tz_tw).strftime('%Y/%m/%d') for t in d_data['ts']]
        dif, dea, hist = perform_macd_full(d_data['closes'], is_tw)
        rsi_vals = calculate_rsi(d_data['closes'])
        
        # 💡 核心：整合 DataFrame 以利 Altair 同步互動
        source = pd.DataFrame({
            '日期': full_dates,
            '收盤價': d_data['closes'],
            'MACD柱狀': hist,
            'RSI': rsi_vals
        }).drop_duplicates(subset=['日期'])

        # 💡 互動選取器 (觸碰同步導引線)
        nearest = alt.selection_point(nearest=True, on='mouseover', fields=['日期'], empty=False)

        # 基礎 X 軸配置
        x_axis = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))

        # 1. 價格走勢圖
        line = alt.Chart(source).mark_line(color='#1f77b4').encode(x=x_axis, y=alt.Y('收盤價', scale=alt.Scale(zero=False), title=None))
        # 導引點與資訊卡
        selectors = alt.Chart(source).mark_point().encode(x=x_axis, opacity=alt.value(0)).add_params(nearest)
        points = line.mark_point().encode(opacity=alt.condition(nearest, alt.value(1), alt.value(0)))
        text = line.mark_text(align='left', dx=5, dy=-5).encode(text=alt.condition(nearest, '收盤價:Q', alt.value(' ')))
        rules = alt.Chart(source).mark_rule(color='gray').encode(x=x_axis).transform_filter(nearest)
        
        c_price = (line + selectors + points + text + rules).properties(height=200)

        # 2. MACD 柱狀圖
        c_macd = alt.Chart(source).mark_bar().encode(
            x=x_axis,
            y=alt.Y('MACD柱狀', title=None),
            color=alt.condition(alt.datum['MACD柱狀'] > 0, alt.value('#ff4b4b'), alt.value('#00cc96')),
            tooltip=['日期', 'MACD柱狀']
        ).properties(height=150) + rules

        # 3. RSI 折線圖
        c_rsi = alt.Chart(source).mark_line(color='#9467bd').encode(
            x=x_axis,
            y=alt.Y('RSI', scale=alt.Scale(domain=[0, 100]), title=None),
            tooltip=['日期', 'RSI']
        ).properties(height=150) + rules

        # 顯示同步圖表
        st.altair_chart(alt.vconcat(c_price, c_macd, c_rsi).resolve_scale(x='shared'), use_container_width=True)

        # --- 決策建議與表格 ---
        st.divider()
        st.subheader("💡 深度量化診斷")
        h_d_up = hist[-1] > hist[-2] if hist else False
        _, _, h_w = perform_macd_full(wk_data['closes'], is_tw) if wk_data else (0,0,[0,0])
        _, _, h_m = perform_macd_full(mo_data['closes'], is_tw) if mo_data else (0,0,[0,0])
        res_score = sum([h_d_up, (len(h_w)>1 and h_w[-1]>h_w[-2]), (len(h_m)>1 and h_m[-1]>h_m[-2])])
        
        c1, c2, c3 = st.columns(3)
        c1.metric("現價", f"${d_data['price']}")
        if cost_input > 0:
            roi = (d_data['price'] - cost_input) / cost_input
            c2.metric("損益率", f"{roi:+.2%}")
        c3.metric("共振得分", f"{res_score} 分")
        
        st.info("💡 手機使用者：可直接在圖表上滑動或點擊，查看當日精確數據。")
        st.table(source.tail(5))
else:
    st.info("💡 請輸入股票名稱或代號開始分析。")
