# 檔名：20150424 MACD + RSI 深度診斷引擎版.py
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
# 🌐 第二部分：全天候雙向反查搜尋引擎
# ==========================================
def search_ticker(query):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
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
    
    try:
        fm_url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
        res = requests.get(fm_url, headers=headers, timeout=5).json()
        for item in res.get('data', []):
            sid = item.get('stock_id')
            sname = item.get('stock_name', '')
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

# ==========================================
# 🚀 第三部分：深度診斷生成器
# ==========================================
def generate_detailed_report(res_score, rsi, roi, cost, is_stock_held):
    report = ""
    # 1. 趨勢診斷
    report += "#### 🧭 1. 多週期趨勢診斷\n"
    if res_score == 3:
        report += "目前**月線、週線、日線的 MACD 動能皆同步向上**（共振得分 3 分）。這代表大、中、小級別的資金方向達成共識，屬於具備高爆發力的「主升段」特徵，多方控盤力道極強，趨勢具備延續性。\n\n"
    elif res_score == 2:
        report += "目前共振得分為 2 分，顯示**長短週期動能出現分歧**。這通常發生在長線保護短線的「良性回檔」，或是短線轉強但長線尚未跟上的「打底階段」。此時走勢較為顛簸，屬於震盪整理期。\n\n"
    elif res_score == 1:
        report += "目前共振得分僅 1 分，代表**僅有單一短週期出現轉強訊號**。整體大趨勢依然偏空或極度發散，此處的上漲極可能只是「弱勢反彈」或誘多，需高度提防假突破。\n\n"
    else:
        report += "目前**月、週、日線的 MACD 動能全面向下**（共振得分 0 分）。市場處於標準的「空頭排列」，賣壓沉重且趨勢尚未見底，屬於典型的左側風險區。\n\n"

    # 2. 動能與風險水位
    report += "#### ⚡ 2. 動能與風險水位 (RSI 指標)\n"
    if rsi >= 80:
        report += f"當前 RSI 高達 **{rsi:.1f}**，已進入**「極度超買區」**。市場情緒處於極度狂熱狀態，雖然強勢股可能在高檔鈍化續強，但技術面的追高風險劇增，隨時可能面臨獲利了結的急跌回檔壓力。\n\n"
    elif rsi >= 50:
        report += f"當前 RSI 為 **{rsi:.1f}**，穩居 50 之上的**「多方優勢區」**。買盤力道大於賣盤，短期動能表現健康且具備上攻潛力，尚未出現過熱失控的跡象。\n\n"
    elif rsi > 20:
        report += f"當前 RSI 為 **{rsi:.1f}**，落在 50 之下的**「空方壓制區」**。市場交投相對偏弱，股價反彈容易遇到上方套牢反壓，需等待指標突破中線 50 才能確認正式轉強。\n\n"
    else:
        report += f"當前 RSI 僅 **{rsi:.1f}**，已落入**「極度超賣區」**。市場出現恐慌性拋售，技術面上向下乖離過大，短期內賣壓可能已宣洩完畢，隨時醞釀跌深反彈的契機。\n\n"

    # 3. 綜合操作策略
    report += "#### 🎯 3. 綜合實戰策略建議\n"
    if is_stock_held:
        if roi < -0.07:
            report += f"> 🛑 **【防禦優先】執行止損紀律**：您的目前虧損已達 **{roi:.2%}**，觸及 7% 絕對防線。在量化交易中，保護本金是首要任務，建議嚴格停損出場觀望，避免陷入深套陷阱。\n"
        elif res_score == 3 and rsi < 80:
            report += "> ✅ **【強勢進攻】持股續抱，讓獲利奔跑**：目前趨勢完美共振且未見過熱，您擁有持股成本優勢。建議無需預設高點，可沿著 10 日線或月線作為移動停利點，享受趨勢利潤。\n"
        elif res_score == 3 and rsi >= 80:
            report += "> ⚠️ **【風險控管】逢高分批減碼**：雖然大趨勢依舊看好，但短線乖離過大。建議可將部位分批獲利了結（如先賣出 1/3 或一半），收回部分本金，剩餘部位留倉參與後續行情。\n"
        elif res_score == 0:
            report += "> 📉 **【資金抽離】嚴格觀望 / 逢反彈減碼**：整體大環境對多方極度不利，強烈建議趁盤中反彈時果斷降低部位，切忌在此時「向下攤平」擴大風險。\n"
        else:
            report += "> 🔎 **【防守反擊】區間操作，嚴設防線**：目前多空勢力正在交戰，無明確單邊大趨勢。若在獲利狀態可續抱觀察；若已接近成本價，請嚴格設定跌破重要支撐（如前低或均線）即果斷退場。\n"
    else:
        report += "> 💡 **【空手觀望中】若您正在尋找進場點：**\n> "
        if res_score == 3 and rsi < 80:
            report += "目前趨勢明確向上，可尋找股價「量縮回測均線」的時機伺機佈局，順勢而為。"
        elif res_score == 3 and rsi >= 80:
            report += "雖然標的極度強勢，但現價追高風險極大。建議發揮耐心，等待 RSI 回落或橫盤整理消化浮額後再行評估。"
        elif res_score == 0:
            report += "趨勢全面偏空，強烈建議「多看少做」，不要急於摸底接刀，等待底部型態出現。"
        else:
            report += "方向混沌不明朗，勝率不高。建議等待共振得分提升（至少 2 分以上）、趨勢確認後再考慮進場。"

    return report

# ==========================================
# 🚀 第四部分：網頁介面佈局
# ==========================================
st.set_page_config(page_title="量化導航 2026", layout="wide")
st.title("🌍 全球量化導航系統")

st.markdown("---")
search_col, cost_col = st.columns([3, 1])
with search_col:
    stock_input = st.text_input("🔍 輸入名稱或代碼 (上市/上櫃/興櫃/美股)", value="", placeholder="例如: 台積電 或 2330").strip()
with cost_col:
    cost_input = st.number_input("💰 持有成本", value=0.0, help="輸入 0 代表純觀望分析")
st.markdown("---")

if stock_input:
    d_data, wk_data, mo_data = None, None, None
    found_symbol, display_name = None, None

    with st.spinner(f'正在解析「{stock_input}」並同步雲端數據...'):
        found_symbol, display_name = search_ticker(stock_input)
        if not found_symbol:
            found_symbol = stock_input.upper()
            display_name = stock_input.upper()

        if found_symbol:
            tickers_to_try = []
            base_symbol = found_symbol.split('.')[0]
            if base_symbol.isdigit():
                if '.' in found_symbol: tickers_to_try.append(found_symbol)
                for sfx in ['.TW', '.TWO', '.TE']:
                    candidate = f"{base_symbol}{sfx}"
                    if candidate not in tickers_to_try: tickers_to_try.append(candidate)
            else:
                tickers_to_try = [found_symbol] 
            
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
        
        st.success(f"✅ 分析完成！標的：{display_label} ｜ 時間：{report_time}")
        
        full_dates = [datetime.fromtimestamp(t, tz=tz_tw).strftime('%Y/%m/%d') for t in d_data['ts']]
        x_axis_clean = alt.X('日期', axis=alt.Axis(labels=False, title=None, ticks=False))
        
        dif, dea, hist = perform_macd_full(d_data['closes'], is_tw)
        rsi_vals = calculate_rsi(d_data['closes'])

        col1, col2, col3 = st.columns(3)
        with col1:
            st.subheader("價格走勢")
            df = pd.DataFrame({'日期': full_dates, '價格': d_data['closes']}).drop_duplicates(subset=['日期'])
            st.altair_chart(alt.Chart(df).mark_line(color='#1f77b4').encode(x=x_axis_clean, y=alt.Y('價格', scale=alt.Scale(zero=False), title=None), tooltip=['日期', '價格']), use_container_width=True)
        with col2:
            st.subheader("MACD 柱狀")
            df = pd.DataFrame({'日期': full_dates, '柱狀': hist}).drop_duplicates(subset=['日期'])
            st.altair_chart(alt.Chart(df).mark_bar().encode(x=x_axis_clean, y=alt.Y('柱狀', title=None), color=alt.condition(alt.datum['柱狀'] > 0, alt.value('#ff4b4b'), alt.value('#00cc96')), tooltip=['日期', '柱狀']), use_container_width=True)
        with col3:
            st.subheader("RSI (14)")
            df = pd.DataFrame({'日期': full_dates, 'RSI': rsi_vals}).drop_duplicates(subset=['日期'])
            st.altair_chart(alt.Chart(df).mark_line(color='#9467bd').encode(x=x_axis_clean, y=alt.Y('RSI', scale=alt.Scale(domain=[0, 100]), title=None), tooltip=['日期', 'RSI']), use_container_width=True)

        # ==================================
        # 💡 升級版：深度量化診斷報告區塊
        # ==================================
        st.divider()
        st.subheader(f"💡 {display_label} 深度量化診斷報告")
        
        h_d_up = hist[-1] > hist[-2] if hist else False
        _, _, h_w = perform_macd_full(wk_data['closes'], is_tw) if wk_data else (0,0,[0,0])
        _, _, h_m = perform_macd_full(mo_data['closes'], is_tw) if mo_data else (0,0,[0,0])
        resonance_score = sum([h_d_up, (len(h_w)>1 and h_w[-1]>h_w[-2]), (len(h_m)>1 and h_m[-1]>h_m[-2])])
        score_info = {3: "🟢 3 分 (主升共振)", 2: "🟡 2 分 (趨勢修復)", 1: "🟠 1 分 (弱勢反彈)", 0: "🔴 0 分 (空頭排列)"}
        
        # 狀態儀表板
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("當前價位", f"${d_data['price']}")
        roi = 0
        if cost_input > 0:
            roi = (d_data['price'] - cost_input) / cost_input
            col_m2.metric("實時損益率", f"{roi:+.2%}")
        else:
            col_m2.metric("持有狀態", "空手觀望")
        col_m3.metric("共振得分", score_info[resonance_score])
        
        st.markdown("---")
        
        # 呼叫深度分析產生器
        detailed_report = generate_detailed_report(
            res_score=resonance_score, 
            rsi=rsi_vals[-1] if rsi_vals else 50, 
            roi=roi, 
            cost=cost_input, 
            is_stock_held=(cost_input > 0)
        )
        st.markdown(detailed_report)

        st.subheader("📅 近 5 日軌跡")
        table_df = pd.DataFrame({'日期': full_dates, '收盤': d_data['closes'], 'MACD': [round(x,3) for x in hist], 'RSI': [round(x,1) for x in rsi_vals]}).drop_duplicates(subset=['日期'], keep='last').tail(5)
        st.table(table_df)
    else:
        st.error(f"❌ 查無「{stock_input}」的數據，請檢查名稱或代碼。")
else:
    st.info("💡 **請在上方輸入框輸入股票名稱 (如: 台積電) 或代號 (如: 2330) 以開啟量化分析。**")
