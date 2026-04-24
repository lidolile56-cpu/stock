# 檔名：20150424 MACD + RSI 終極裝甲防護版 (修復崩潰問題).py
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
st.set_page_config(page_title="量化導航 2026", layout="wide")

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
    }
    a:hover {
        text-decoration: underline !important;
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
# 🌐 第二部分：全方位資料抓取引擎
# ==========================================
def search_ticker(query):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;query={urllib.parse.quote(query)}"
        res = requests.get(url, headers=headers, timeout=5).json()
        results = res.get('ResultSet', {}).get('Result', [])
        for r in results:
            sym = r.get('symbol', '')
            if sym.endswith('.TW') or sym.endswith('.TWO') or sym.endswith('.TE'): return sym, r.get('name')
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

    fallback = {
        "光洋科": "3276.TWO", "鈊象": "3293.TWO", "元太": "8069.TWO",
        "台積電": "2330.TW", "鴻海": "2317.TW", "聯發科": "2454.TW",
        "長榮": "2603.TW", "星宇航空": "2646.TW", "乾杯": "1269.TE"
    }
    if query in fallback: return fallback[query], query
    for name, sym in fallback.items():
        if query == sym.split('.')[0]: return sym, name
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
        
        # 💡 防呆修復：過濾掉有時 API 會回傳的 None 值
        valid_ts = [t for t in ts if t is not None]
        if not valid_ts or len(valid_ts) < 5: return None 
        
        tz_tw = timezone(timedelta(hours=8))
        if (datetime.now(tz_tw) - datetime.fromtimestamp(valid_ts[-1], tz=tz_tw)).days > 30: return None
        
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
            
        official_name = meta.get('longName') or meta.get('shortName') or ticker
        return {'closes': c_c, 'ts': c_ts, 'price': live_price, 'name': official_name, 'symbol': meta.get('symbol')}
    except: return None

# 💡 裝甲防護版：強制型別轉換，避免算數崩潰
@st.cache_data(ttl=3600)
def get_revenue_info(symbol):
    headers = {'User-Agent': 'Mozilla/5.0'}
    result_data = {'total_revenue': '無資料', 'revenue_growth': '無資料', 'gross_margin': '無資料', 'profit_margin': '無資料'}
    
    pure_symbol = symbol.split('.')[0]
    is_tw = symbol.endswith('.TW') or symbol.endswith('.TWO') or symbol.endswith('.TE')

    if is_tw:
        try:
            start_date_rev = (datetime.now(timezone.utc) - timedelta(days=400)).strftime('%Y-%m-%d')
            url_rev = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMonthRevenue&data_id={pure_symbol}&start_date={start_date_rev}"
            res_rev = requests.get(url_rev, headers=headers, timeout=5).json()
            
            if res_rev.get('data'):
                df_rev = pd.DataFrame(res_rev['data'])
                # 強制轉換為數字，避免字串相減導致系統崩潰
                df_rev['revenue'] = pd.to_numeric(df_rev['revenue'], errors='coerce')
                df_rev['revenue_year'] = pd.to_numeric(df_rev['revenue_year'], errors='coerce')
                df_rev['revenue_month'] = pd.to_numeric(df_rev['revenue_month'], errors='coerce')
                df_rev = df_rev.dropna(subset=['revenue', 'revenue_year', 'revenue_month'])
                
                if not df_rev.empty:
                    latest_rev = df_rev.iloc[-1]
                    rev_val = float(latest_rev['revenue'])
                    
                    if rev_val > 0:
                        rev_yi = rev_val / 100000000 
                        result_data['total_revenue'] = f"{rev_yi:,.2f} 億 ({int(latest_rev['revenue_month'])}月)"
                    
                    last_year = int(latest_rev['revenue_year']) - 1
                    this_month = int(latest_rev['revenue_month'])
                    last_year_data = df_rev[(df_rev['revenue_year'] == last_year) & (df_rev['revenue_month'] == this_month)]
                    
                    if not last_year_data.empty:
                        last_year_rev = float(last_year_data.iloc[0]['revenue'])
                        if last_year_rev > 0:
                            yoy = ((rev_val - last_year_rev) / last_year_rev) * 100
                            result_data['revenue_growth'] = f"{yoy:+.2f}%"
        except: pass

        try:
            start_date_fin = (datetime.now(timezone.utc) - timedelta(days=400)).strftime('%Y-%m-%d')
            url_fin = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockFinancialStatements&data_id={pure_symbol}&start_date={start_date_fin}"
            res_fin = requests.get(url_fin, headers=headers, timeout=5).json()
            if res_fin.get('data'):
                df_fin = pd.DataFrame(res_fin['data'])
                if 'date' in df_fin.columns and 'type' in df_fin.columns and 'value' in df_fin.columns:
                    latest_date = df_fin['date'].max()
                    df_latest = df_fin[df_fin['date'] == latest_date].copy()
                    
                    # 強制處理可能有逗號的數字
                    df_latest['value'] = df_latest['value'].astype(str).str.replace(',', '')
                    df_latest['value'] = pd.to_numeric(df_latest['value'], errors='coerce')
                    
                    rev_mask = df_latest['type'].str.contains('Revenue|營業收入', case=False, regex=True, na=False)
                    gp_mask = df_latest['type'].str.contains('GrossProfit|營業毛利', case=False, regex=True, na=False)
                    ni_mask = df_latest['type'].str.contains('NetIncome|淨利', case=False, regex=True, na=False)
                    
                    rev_abs = float(df_latest[rev_mask]['value'].values[0]) if not df_latest[rev_mask].empty else 0
                    gp_abs = float(df_latest[gp_mask]['value'].values[0]) if not df_latest[gp_mask].empty else 0
                    ni_abs = float(df_latest[ni_mask]['value'].values[0]) if not df_latest[ni_mask].empty else 0
                    
                    if rev_abs > 0:
                        result_data['gross_margin'] = f"{(gp_abs / rev_abs) * 100:.2f}%"
                        result_data['profit_margin'] = f"{(ni_abs / rev_abs) * 100:.2f}%"
        except: pass

    # 美股備援
    if result_data['total_revenue'] == '無資料' or not is_tw:
        try:
            session = requests.Session()
            session.headers.update(headers)
            session.get('https://fc.yahoo.com', timeout=5) 
            crumb = session.get('https://query1.finance.yahoo.com/v1/test/getcrumb', timeout=5).text
            if crumb:
                url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=financialData&crumb={crumb}"
                res = session.get(url, timeout=5)
                if res.status_code == 200:
                    fin = res.json().get('quoteSummary', {}).get('result', [{}])[0].get('financialData', {})
                    if fin:
                        if result_data['total_revenue'] == '無資料': result_data['total_revenue'] = fin.get('totalRevenue', {}).get('fmt', '無資料')
                        if result_data['revenue_growth'] == '無資料': result_data['revenue_growth'] = f"{fin.get('revenueGrowth', {}).get('raw', 0)*100:.2f}%" if fin.get('revenueGrowth', {}).get('raw') else "無資料"
                        if result_data['gross_margin'] == '無資料': result_data['gross_margin'] = f"{fin.get('grossMargins', {}).get('raw', 0)*100:.2f}%" if fin.get('grossMargins', {}).get('raw') else "無資料"
                        if result_data['profit_margin'] == '無資料': result_data['profit_margin'] = f"{fin.get('profitMargins', {}).get('raw', 0)*100:.2f}%" if fin.get('profitMargins', {}).get('raw') else "無資料"
        except: pass

    return result_data

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
            
            if " - " in raw_title:
                title, publisher = raw_title.rsplit(" - ", 1)
            else:
                title = raw_title
                publisher = item.findtext('source', default='市場新聞')
                
            pub_date_str = "近期發布"
            if pubDate:
                try:
                    dt = datetime.strptime(pubDate, "%a, %d %b %Y %H:%M:%S GMT")
                    tz_tw = timezone(timedelta(hours=8))
                    pub_date_str = dt.replace(tzinfo=timezone.utc).astimezone(tz_tw).strftime('%Y/%m/%d %H:%M')
                except:
                    pub_date_str = pubDate[:16] 
                    
            news.append({'title': title, 'link': link, 'publisher': publisher, 'pubDate': pub_date_str})
    except: pass
    return news

# ==========================================
# 🧠 第三部分：深度診斷生成器 
# ==========================================
def generate_detailed_report(res_score, rsi, roi, cost, is_stock_held):
    report = "#### 🧭 1. 多週期趨勢診斷\n"
    if res_score == 3: report += "目前**月線、週線、日線的 MACD 動能皆同步向上**（共振得分 3 分）。大中小級別資金達成共識，具備高爆發力的「主升段」特徵，趨勢延續性強。\n\n"
    elif res_score == 2: report += "目前共振得分為 2 分，顯示**長短週期動能出現分歧**。此為長線保護短線的「良性回檔」，或短線轉強但長線未跟上的「打底階段」，走勢易震盪。\n\n"
    elif res_score == 1: report += "目前共振得分僅 1 分，代表**僅有單一短週期轉強**。整體大趨勢依然偏空，上漲極可能是「弱勢反彈」，需高度提防假突破。\n\n"
    else: report += "目前**月、週、日線動能全面向下**（共振得分 0 分）。市場處於「空頭排列」，賣壓沉重且趨勢未見底，屬於左側高風險區。\n\n"

    report += "#### ⚡ 2. 動能與風險水位 (RSI 指標)\n"
    if rsi >= 80: report += f"當前 RSI 高達 **{rsi:.1f}**，進入**「極度超買區」**。市場情緒極度狂熱，追高風險劇增，隨時面臨獲利了結的急跌回檔壓力。\n\n"
    elif rsi >= 50: report += f"當前 RSI 為 **{rsi:.1f}**，穩居 50 之上的**「多方優勢區」**。買盤力道大於賣盤，短期動能健康且具備上攻潛力。\n\n"
    elif rsi > 20: report += f"當前 RSI 為 **{rsi:.1f}**，落入**「空方壓制區」**。反彈易遇上方套牢反壓，需等待突破中線 50 才能確認正式轉強。\n\n"
    else: report += f"當前 RSI 僅 **{rsi:.1f}**，進入**「極度超賣區」**。恐慌拋售導致向下乖離過大，賣壓可能宣洩完畢，醞釀跌深反彈契機。\n\n"

    report += "#### 🎯 3. 綜合實戰策略建議\n"
    if is_stock_held:
        if roi < -0.07: report += f"> 🛑 **【防禦優先】執行止損**：虧損已達 **{roi:.2%}**，觸及 7% 防線。保護本金為首要任務，建議停損出場，避免深套。\n"
        elif res_score == 3 and rsi < 80: report += "> ✅ **【強勢進攻】持股續抱**：趨勢完美共振且未見過熱，建議以 10 日線或月線為移動停利點，讓獲利奔跑。\n"
        elif res_score == 3 and rsi >= 80: report += "> ⚠️ **【風險控管】逢高分批減碼**：大趨勢看好但短線乖離過大，建議分批獲利了結（如先賣 1/3），收回部分本金。\n"
        elif res_score == 0: report += "> 📉 **【資金抽離】逢反彈減碼**：大環境對多方極度不利，強烈建議趁盤中反彈果斷降低部位，切忌向下攤平。\n"
        else: report += "> 🔎 **【防守反擊】區間操作**：多空交戰無明確單邊趨勢。若在獲利狀態可續抱觀察；若已近成本價，嚴設跌破均線即退場。\n"
    else:
        report += "> 💡 **【空手觀望中】若您正在尋找進場點：**\n> "
        if res_score == 3 and rsi < 80: report += "趨勢明確向上，可尋找股價「量縮回測均線」的時機伺機佈局。"
        elif res_score == 3 and rsi >= 80: report += "標的極度強勢但追高風險大。建議耐心等待 RSI 回落消化浮額後再行評估。"
        elif res_score == 0: report += "趨勢全面偏空，強烈建議「多看少做」，切勿急於摸底接刀。"
        else: report += "方向混沌不明朗，建議等待共振得分提升（至少 2 分）確認趨勢後再考慮進場。"
    return report

# ==========================================
# 🚀 第四部分：網頁介面與圖表渲染
# ==========================================
st.title("🌍 全球量化導航系統")

st.markdown("---")
search_col, cost_col = st.columns([3, 1])
with search_col:
    stock_input = st.text_input("🔍 名稱/代碼", value="", placeholder="輸入個股名稱或股號 (例: 台積電, 3293)").strip()
with cost_col:
    cost_input = st.number_input("💰 持有成本", value=0.0)
st.markdown("---")

if stock_input:
    d_data, wk_data, mo_data = None, None, None
    found_symbol, display_name = None, None

    with st.spinner(f'全維度數據同步中 (圖表/營收/新聞)...'):
        found_symbol, display_name = search_ticker(stock_input)
        if not found_symbol:
            found_symbol, display_name = stock_input.upper(), stock_input.upper()

        if found_symbol:
            base_symbol = found_symbol.split('.')[0]
            tickers_to_try = [found_symbol]
            if base_symbol.isdigit():
                for sfx in ['.TW', '.TWO', '.TE']:
                    if f"{base_symbol}{sfx}" not in tickers_to_try: tickers_to_try.append(f"{base_symbol}{sfx}")
            
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
        
        full_dates = [datetime.fromtimestamp(t, tz=tz_tw).strftime('%Y/%m/%d') for t in d_data['ts']]
        dif, dea, hist = perform_macd_full(d_data['closes'], is_tw)
        rsi_vals = calculate_rsi(d_data['closes'])
        
        source = pd.DataFrame({
            '日期': full_dates,
            '收盤價': d_data['closes'],
            'MACD柱狀': hist,
            'RSI': rsi_vals
        }).drop_duplicates(subset=['日期'])

        # ==========================================
        # 💡 圖表渲染區 (莫蘭迪黃色 + 左側防遮擋)
        # ==========================================
        # 💡 防呆：相容新舊版本 Altair
        if hasattr(alt, 'selection_point'):
            nearest = alt.selection_point(nearest=True, on='mouseover', fields=['日期'], empty=False)
        else:
            nearest = alt.selection_single(nearest=True, on='mouseover', fields=['日期'], empty='none')
            
        x_axis = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))
        morandi_yellow = '#CBAE73'

        selectors = alt.Chart(source).mark_point().encode(x=x_axis, opacity=alt.value(0)).add_params(nearest)
        rules = alt.Chart(source).mark_rule(color='gray', strokeDash=[3,3]).encode(x=x_axis).transform_filter(nearest)

        line_price = alt.Chart(source).mark_line(color='#1f77b4', strokeWidth=2).encode(x=x_axis, y=alt.Y('收盤價', scale=alt.Scale(zero=False), title=None))
        points_price = line_price.mark_point(color='#1f77b4', size=60, filled=True).encode(opacity=alt.condition(nearest, alt.value(1), alt.value(0)))
        text_date_p = line_price.mark_text(align='right', dx=-10, dy=-25, fontSize=12, fontWeight='bold', color=morandi_yellow).encode(text='日期:N').transform_filter(nearest)
        text_price = line_price.mark_text(align='right', dx=-10, dy=-10, fontSize=14, fontWeight='bold', color=morandi_yellow).encode(text=alt.Text('收盤價:Q', format='.2f')).transform_filter(nearest)
        c_price = (line_price + selectors + rules + points_price + text_date_p + text_price).properties(height=200, title="股價走勢")

        bar_macd = alt.Chart(source).mark_bar().encode(
            x=x_axis, y=alt.Y('MACD柱狀', title=None),
            color=alt.condition(alt.datum['MACD柱狀'] > 0, alt.value('#ff4b4b'), alt.value('#00cc96'))
        )
        text_date_m = alt.Chart(source).mark_text(align='right', dx=-10, dy=-25, fontSize=12, fontWeight='bold', color=morandi_yellow).encode(x=x_axis, y=alt.Y('MACD柱狀'), text='日期:N').transform_filter(nearest)
        text_macd = alt.Chart(source).mark_text(align='right', dx=-10, dy=-10, fontSize=14, fontWeight='bold', color=morandi_yellow).encode(x=x_axis, y=alt.Y('MACD柱狀'), text=alt.Text('MACD柱狀:Q', format='.3f')).transform_filter(nearest)
        c_macd = (bar_macd + selectors + rules + text_date_m + text_macd).properties(height=150, title="MACD 動能")

        line_rsi = alt.Chart(source).mark_line(color='#9467bd', strokeWidth=2).encode(x=x_axis, y=alt.Y('RSI', scale=alt.Scale(domain=[0, 100]), title=None))
        points_rsi = line_rsi.mark_point(color='#9467bd', size=60, filled=True).encode(opacity=alt.condition(nearest, alt.value(1), alt.value(0)))
        text_date_r = line_rsi.mark_text(align='right', dx=-10, dy=-25, fontSize=12, fontWeight='bold', color=morandi_yellow).encode(text='日期:N').transform_filter(nearest)
        text_rsi = line_rsi.mark_text(align='right', dx=-10, dy=-10, fontSize=14, fontWeight='bold', color=morandi_yellow).encode(text=alt.Text('RSI:Q', format='.1f')).transform_filter(nearest)
        c_rsi = (line_rsi + selectors + rules + points_rsi + text_date_r + text_rsi).properties(height=150, title="RSI (14)")

        st.altair_chart(alt.vconcat(c_price, c_macd, c_rsi).resolve_scale(x='shared'), use_container_width=True)

        # ==========================================
        # 💡 深度診斷報告區塊
        # ==========================================
        st.divider()
        st.subheader(f"💡 {display_label} 深度量化診斷")
        h_d_up = hist[-1] > hist[-2] if hist else False
        _, _, h_w = perform_macd_full(wk_data['closes'], is_tw) if wk_data else (0,0,[0,0])
        _, _, h_m = perform_macd_full(mo_data['closes'], is_tw) if mo_data else (0,0,[0,0])
        res_score = sum([h_d_up, (len(h_w)>1 and h_w[-1]>h_w[-2]), (len(h_m)>1 and h_m[-1]>h_m[-2])])
        score_info = {3: "🟢 3 分 (主升共振)", 2: "🟡 2 分 (趨勢修復)", 1: "🟠 1 分 (弱勢反彈)", 0: "🔴 0 分 (空頭排列)"}
        
        c1, c2, c3 = st.columns(3)
        c1.metric("當前價位", f"${d_data['price']}")
        roi = 0
        if cost_input > 0:
            roi = (d_data['price'] - cost_input) / cost_input
            c2.metric("實時損益率", f"{roi:+.2%}")
        else: c2.metric("持有狀態", "空手觀望")
        c3.metric("共振得分", score_info[res_score])
        
        st.markdown("---")
        detailed_report = generate_detailed_report(res_score, rsi_vals[-1] if rsi_vals else 50, roi, cost_input, (cost_input > 0))
        st.markdown(detailed_report)

        st.subheader("📅 近 5 日量化軌跡")
        table_df = pd.DataFrame({'日期': full_dates, '收盤': d_data['closes'], 'MACD': [round(x,3) for x in hist], 'RSI': [round(x,1) for x in rsi_vals]}).drop_duplicates(subset=['日期'], keep='last').tail(5)
        st.table(table_df)

        # ==========================================
        # 💰 基本面營收與財務資訊
        # ==========================================
        st.divider()
        st.subheader(f"💰 {final_name} 最新營收與獲利指標")
        
        rev_data = get_revenue_info(d_data['symbol'])
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("最新單月營收", rev_data['total_revenue'])
        rc2.metric("營收年增率 (YoY)", rev_data['revenue_growth'])
        rc3.metric("毛利率", rev_data['gross_margin'])
        rc4.metric("淨利率", rev_data['profit_margin'])

        # ==========================================
        # 📰 即時市場新聞區塊
        # ==========================================
        st.divider()
        st.subheader(f"📰 {final_name} 最新市場新聞")
        
        news_items = get_stock_news(final_name) 
        
        if news_items:
            for item in news_items: 
                st.markdown(f"**[{item['title']}]({item['link']})**")
                st.caption(f"🗞️ {item['publisher']} ｜ 🕒 {item['pubDate']}")
                st.write("") 
        else:
            st.info("目前雲端伺服器未返回相關新聞，或該標的近期無重大新聞發布。")

    else:
        st.error(f"❌ 查無「{stock_input}」的數據，請檢查名稱或代碼。")
else:
    st.info("💡 請在上方輸入股票名稱或代號開始分析。")
