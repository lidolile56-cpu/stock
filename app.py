# 檔名：20150420 MACD + RSI 完整說明版.py
import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

# ==========================================
# 🛠️ 第一部分：基礎工具
# ==========================================
def safe_float(val, default=0.0):
    if val is None: return default
    try: return float(str(val).replace(',', ''))
    except: return default

def calculate_ema(data, n):
    if len(data) < n: return [data[-1]] * len(data)
    res = [sum(data[:n])/n]
    alpha = 2 / (n + 1)
    full_res = [data[0]] * (n - 1) + res
    for i in range(n, len(data)):
        full_res.append(data[i] * alpha + full_res[-1] * (1 - alpha))
    return full_res

# ==========================================
# 📊 第二部分：核心量化引擎 (MACD + RSI)
# ==========================================
def perform_macd_analysis(closes, is_tw):
    if not closes or len(closes) < 35: return None
    e12 = calculate_ema(closes, 12)
    e26 = calculate_ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = calculate_ema(dif, 9)
    multiplier = 2.0 if is_tw else 1.0
    hist = [(d - a) * multiplier for d, a in zip(dif, dea)]
    return hist

def calculate_rsi(closes, period=14):
    if not closes or len(closes) < period + 1: return [50.0] * len(closes)
    rsi_series = [50.0] * period
    avg_gain = sum(max(0, closes[i] - closes[i-1]) for i in range(1, period+1)) / period
    avg_loss = sum(max(0, closes[i-1] - closes[i]) for i in range(1, period+1)) / period
    if avg_loss == 0: rsi_series.append(100.0)
    else: rsi_series.append(100.0 - (100.0 / (1.0 + (avg_gain / avg_loss))))
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i-1]
        gain, loss = max(0, diff), max(0, -diff)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0: rsi_series.append(100.0)
        else: rsi_series.append(100.0 - (100.0 / (1.0 + (avg_gain / avg_loss))))
    return rsi_series

def analyze_indicators_5day(closes, highs, lows, timestamps, is_tw_market):
    hist = perform_macd_analysis(closes, is_tw_market)
    rsi = calculate_rsi(closes, 14)
    if not hist or not rsi: return None
    report = []
    for i in range(-5, 0):
        try:
            m_now, m_pre = hist[i], hist[i-1]
            m_up = m_now > m_pre
            status = ("🔴紅柱" if m_now > 0 else "🟢綠柱") + ("放大" if m_up else "縮減")
            r_val = rsi[i]
            if r_val >= 80: r_status = "🔥 超買警戒"
            elif r_val <= 20: r_status = "❄️ 超賣低接"
            elif r_val >= 50: r_status = "📈 多方控盤"
            else: r_status = "📉 空方壓制"
            p_range = highs[i] - lows[i]
            pos = ((closes[i] - lows[i]) / p_range * 100) if p_range > 0 else 50
            pos_label = "強勢鎖碼" if pos > 80 else "弱勢殺尾" if pos < 20 else "區間對峙"
            tz_tw = timezone(timedelta(hours=8))
            # ✨ 加入年份顯示格式
            dt = datetime.fromtimestamp(timestamps[i], tz=tz_tw).strftime('%Y/%m/%d') 
            report.append({
                '交易日期': dt, '收盤價': round(closes[i], 2), '當日位階': f"{pos:.1f}% ({pos_label})", 
                'MACD柱狀': round(m_now, 3), '動能趨勢': status, 'RSI(14)': round(r_val, 1), 'RSI狀態': r_status,
                'macd_up': m_up, 'rsi_val': r_val
            })
        except: continue
    return report

# ==========================================
# 🌐 第三部分：數據採集 (含 4/20 強制對位補強)
# ==========================================
@st.cache_data(ttl=60)
def get_verified_data(ticker, interval="1d", lookback="2y"):
    us_name_map = {'AAPL': '蘋果', 'NVDA': '輝達', 'TSLA': '特斯拉', 'TSM': '台積電ADR'}
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={lookback}"
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        result = res.get('chart', {}).get('result', [])[0]
        meta = result.get('meta', {})
        live_price = meta.get('regularMarketPrice')
        live_time = meta.get('regularMarketTime')
        
        ts = result.get('timestamp', [])
        quote = result.get('indicators', {}).get('quote', [{}])[0]
        raw_c = quote.get('close', [])
        raw_h, raw_l = quote.get('high', []), quote.get('low', [])
        
        c_ts, c_c, c_h, c_l = [], [], [], []
        for i in range(len(ts)):
            if raw_c[i] is not None:
                c_ts.append(ts[i]); c_c.append(safe_float(raw_c[i]))
                c_h.append(safe_float(raw_h[i]) if raw_h[i] else safe_float(raw_c[i]))
                c_l.append(safe_float(raw_l[i]) if raw_l[i] else safe_float(raw_c[i]))
        
        # 💡 強制補強邏輯：若 Yahoo 尚未將今日 (4/20) 結算進 K 線陣列，手動補入
        if live_price and c_ts:
            if live_time > c_ts[-1] + 3600: 
                c_ts.append(live_time); c_c.append(live_price)
                c_h.append(max(live_price, c_h[-1])); c_l.append(min(live_price, c_l[-1]))

        symbol = meta.get('symbol', '').split('.')[0]
        name = us_name_map.get(symbol, meta.get('symbol'))
        return {'name': name, 'price': live_price, 'ath': max(c_h), 'atl': min(c_l), 
                'closes': c_c, 'highs': c_h, 'lows': c_l, 'ts': c_ts, 
                'status': "🚨 注意/處置監控" if meta.get('exchangeDataDelayedBy', 0) > 0 else "✅ 正常交易"}
    except: return None

# ==========================================
# 🚀 第四部分：網頁介面
# ==========================================
st.set_page_config(page_title="量化導航系統 2026版", layout="wide")
st.title("🌍 全球多週期全量量化導航系統")
st.markdown(f"🕒 **最後更新時間：{datetime.now(timezone(timedelta(hours=8))).strftime('%Y/%m/%d %H:%M:%S')}**")

st.sidebar.header("🔍 查詢設定")
stock_input = st.sidebar.text_input("輸入股票代碼 (台股請加 .TW)", value="2330.TW").upper()
cost_input = st.sidebar.number_input("持有成本 (0 代表觀望)", value=0.0)

if stock_input:
    is_tw = ".TW" in stock_input or ".TWO" in stock_input or stock_input.isdigit()
    ticker = f"{stock_input}.TW" if stock_input.isdigit() else stock_input
    
    with st.spinner('正在分析數據，請稍候...'):
        d_data = get_verified_data(ticker)
        mo_data = get_verified_data(ticker, interval="1mo", lookback="max")
        wk_data = get_verified_data(ticker, interval="1wk", lookback="max")

    if d_data:
        # 頂部儀表板
        col1, col2, col3 = st.columns(3)
        with col1: st.metric(f"📊 {d_data['name']} 當前價", f"${d_data['price']}", d_data['status'])
        with col2:
            hist_pos = ((d_data['price']-d_data['atl'])/(d_data['ath']-d_data['atl'])*100)
            st.metric("歷史位階", f"{hist_pos:.1f}%")
        
        # 5日軌跡表格
        st.subheader("📈 近 5 個交易日動能軌跡 (精確日期對位)")
        history = analyze_indicators_5day(d_data['closes'], d_data['highs'], d_data['lows'], d_data['ts'], is_tw)
        if history:
            df_display = pd.DataFrame(history).drop(columns=['macd_up', 'rsi_val'])
            st.table(df_display)
            
            # 共振得分計算
            mo_up = (perform_macd_analysis(mo_data['closes'], is_tw)[-1] > perform_macd_analysis(mo_data['closes'], is_tw)[-2]) if mo_data else False
            wk_up = (perform_macd_analysis(wk_data['closes'], is_tw)[-1] > perform_macd_analysis(wk_data['closes'], is_tw)[-2]) if wk_data else False
            resonance_score = sum([history[-1]['macd_up'], wk_up, mo_up])
            score_visual = {3: "🟢 3 分 (主升)", 2: "🟡 2 分 (修復)", 1: "🟠 1 分 (弱彈)", 0: "🔴 0 分 (空頭)"}[resonance_score]
            st.subheader(f"🧠 實時共振得分：{score_visual}")

            # 損益解析與操作建議
            if cost_input > 0:
                roi = (d_data['price'] - cost_input) / cost_input
                st.info(f"📊 實時損益：**{roi:+.2%}**")
                current_rsi = history[-1]['rsi_val']
                if resonance_score == 3 and current_rsi < 80: st.success("✅ **操作建議**：三強共振標的且 RSI 尚未超買，建議持股續抱，讓獲利奔跑。")
                elif current_rsi >= 80: st.error("🚨 **操作建議**：RSI 已進入極度超買區，短線漲幅過大，建議逢高分批減碼，切忌追高。")
                elif roi < -0.07: st.error("🛑 **操作建議**：已觸及 7% 紀律止損線，應嚴格執行停損。")
                else: st.info("🔎 **操作建議**：目前趨勢不明，建議以成本價為防線，觀望為主。")

            # 說明指南
            with st.expander("📖 查看指標定義與操作手冊"):
                st.markdown("""
                **➤ 【共振得分定義與操作建議】：**
                * 🟢 **3 分 (主升共振)**：月、週、日線動能皆向上。波段爆發力強。
                * 🟡 **2 分 (趨勢修復)**：長短週期動能分歧。屬震盪整理格局。
                * 🟠 **1 分 (弱勢反彈)**：僅單一週期轉強，大勢依然向下。易遇假突破。
                * 🔴 **0 分 (空頭排列)**：月、週、日線動能皆向下。建議嚴格迴避。
                
                **➤ 【RSI (14日) 狀態定義與操作指南】：**
                * 🔥 **RSI ≥ 80 (超買警戒)**：市場極度狂熱，隨時面臨獲利了結賣壓。
                * 📈 **RSI 50~79 (多方控盤)**：買盤力道勝出，趨勢偏多運行。
                * 📉 **RSI 21~49 (空方壓制)**：賣盤力道勝出，趨勢偏空運行。
                * ❄️ **RSI ≤ 20 (超賣低接)**：市場恐慌拋售，可留意跌深反彈契機。
                """)
    else:
        st.error("❌ 無法抓取數據。請檢查股票代碼，台股請務必加後綴 (如: 2330.TW)。")
