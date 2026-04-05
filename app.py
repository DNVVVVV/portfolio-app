import os
import psycopg2
from sqlalchemy import create_engine
import yfinance as yf
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
db_url = os.getenv("DATABASE_URL")

if api_key:
    client = genai.Client(api_key=api_key)
else:
    st.error("מפתח הגישה חסר בקובץ ההגדרות.")

if not db_url:
    st.error("כתובת מסד הנתונים חסרה בקובץ ההגדרות.")
else:
    engine = create_engine(db_url)

@st.cache_data(ttl=129600)
def get_ai_analysis(ticker, summary, metrics_text):
    prompt = f"""
    אתה אנליסט פיננסי בכיר. נתח את החברה {ticker} על בסיס הנתונים:
    סקירה עסקית: {summary}
    מדדים: {metrics_text}
    
    חוקי ברזל לכתיבה:
    1. כתוב משפטים זורמים בעברית בלבד.
    2. כל שם חברה, מוצר או מונח פיננסי חייב להופיע כתרגום עברי ומיד לאחריו המונח באנגלית בתוך סוגריים.
    3. אסור להשתמש בנקודתיים ליצירת רשימות הסבר. הכל כמשפטים רציפים.
    4. נתח את המודל העסקי, החוזקות, הסיכונים והתמחור באובייקטיביות מוחלטת.
    """
    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return response.text
    except Exception as e:
        return f"שגיאה בתקשורת השרת: {str(e)}"

@st.cache_data(ttl=300)
def get_stock_info(ticker):
    try: return yf.Ticker(ticker).info
    except: return {}

@st.cache_data(ttl=60)
def get_live_price(ticker_symbol):
    if ticker_symbol == 'CASH': return 1.0
    try: return yf.Ticker(ticker_symbol).fast_info['last_price']
    except: return None

def format_large_number(num):
    if pd.isna(num) or num is None: return "N/A"
    if num >= 1e12: return f"${num/1e12:.2f}T"
    if num >= 1e9: return f"${num/1e9:.2f}B"
    if num >= 1e6: return f"${num/1e6:.2f}M"
    return f"${num:,.2f}"

def format_percent(num):
    if pd.isna(num) or num is None: return "N/A"
    return f"{num * 100:.2f}%"

def db_action(query, params=(), fetch=False):
    pg_query = query.replace('?', '%s')
    if fetch:
        with engine.connect() as conn:
            res = pd.read_sql_query(pg_query, conn, params=params)
        return res
    else:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(pg_query, params)
        conn.commit()
        cur.close()
        conn.close()

def calculate_portfolio_metrics():
    df_tx = db_action("SELECT * FROM transactions WHERE user_id = 1", fetch=True)
    if df_tx.empty: return pd.DataFrame(), 0.0, 0.0, pd.DataFrame()

    df_cash = df_tx[df_tx['ticker_symbol'] == 'CASH']
    deposits = df_cash[df_cash['transaction_type'] == 'DEPOSIT']['quantity'].sum()
    withdrawals = df_cash[df_cash['transaction_type'] == 'WITHDRAW']['quantity'].sum()
    
    df_stocks = df_tx[df_tx['ticker_symbol'] != 'CASH']
    portfolio_data = []
    realized_total = 0.0
    stock_buys_cash = 0.0
    stock_sells_cash = 0.0

    for ticker in df_stocks['ticker_symbol'].unique():
        t_df = df_stocks[df_stocks['ticker_symbol'] == ticker]
        buys = t_df[t_df['transaction_type'] == 'BUY']
        sells = t_df[t_df['transaction_type'] == 'SELL']
        
        bought_qty = buys['quantity'].sum()
        bought_cost = (buys['quantity'] * buys['price_per_unit']).sum()
        avg_buy_price = bought_cost / bought_qty if bought_qty > 0 else 0
        
        sold_qty = sells['quantity'].sum()
        sold_rev = (sells['quantity'] * sells['price_per_unit']).sum()
        
        stock_buys_cash += bought_cost
        stock_sells_cash += sold_rev
        realized_total += sold_rev - (sold_qty * avg_buy_price)
        
        current_qty = bought_qty - sold_qty
        if current_qty > 0:
            portfolio_data.append({
                'סמל': ticker, 'כמות': current_qty,
                'מחיר קנייה ממוצע': avg_buy_price, 'עלות כוללת': current_qty * avg_buy_price
            })
            
    cash_balance = deposits - withdrawals - stock_buys_cash + stock_sells_cash
    open_positions = []
    for pos in portfolio_data:
        lp = get_live_price(pos['סמל'])
        if lp:
            current_val = pos['כמות'] * lp
            open_pl = current_val - pos['עלות כוללת']
            open_pl_pct = (open_pl / pos['עלות כוללת']) * 100 if pos['עלות כוללת'] > 0 else 0
            pos['מחיר נוכחי'] = lp
            pos['שווי שוק'] = current_val
            pos['רווח פתוח ($)'] = open_pl
            pos['רווח פתוח (%)'] = open_pl_pct
            open_positions.append(pos)
            
    return pd.DataFrame(open_positions), cash_balance, realized_total, df_tx

def render_custom_metric(label, value, theme_style):
    bg_color = "#ffffff"
    text_color = "#0f172a"
    label_color = "#64748b"
    border_color = "#2563eb"
    
    if theme_style == "הייטק כהה":
        bg_color = "#1e293b"
        text_color = "#f8fafc"
        label_color = "#94a3b8"
        border_color = "#38bdf8"
    elif theme_style == "חוויתי צבעוני":
        bg_color = "linear-gradient(135deg, #fdf4ff 0%, #f3e8ff 100%)"
        border_color = "#c026d3"
        
    return f"""
    <div style="background: {bg_color}; border-right: 5px solid {border_color}; padding: 18px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); margin-bottom: 20px; direction: rtl; text-align: right;">
        <div style="color: {label_color}; font-size: 0.95rem; font-weight: 600; margin-bottom: 8px;">{label}</div>
        <div style="color: {text_color}; font-size: 1.7rem; font-weight: 800;">{value}</div>
    </div>
    """

st.set_page_config(page_title="ניהול השקעות - דוד נפתלי", layout="wide")

if 'ui_theme' not in st.session_state:
    st.session_state.ui_theme = "מקצועי נקי"

def get_theme_css(theme_name):
    if theme_name == "הייטק כהה":
        return """
        <style>
        .main, .stApp { background-color: #0f172a; color: #f8fafc; direction: rtl; text-align: right; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        [data-testid="stSidebar"] { background-color: #1e293b; color: #f8fafc; direction: rtl; text-align: right; }
        .report-container { background-color: #1e293b; padding: 40px; border-radius: 15px; border: 1px solid #334155; box-shadow: 0 10px 25px rgba(0,0,0,0.5); margin-top: 30px; direction: rtl; text-align: right; color: #f8fafc; }
        .report-container p, .report-container h1, .report-container h2, .report-container h3, .report-container div { direction: rtl !important; text-align: right !important; color: #f8fafc; }
        h1, h2, h3, p, label { color: #f8fafc !important; }
        </style>
        """
    elif theme_name == "חוויתי צבעוני":
        return """
        <style>
        .main, .stApp { background-color: #faf5ff; direction: rtl; text-align: right; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        [data-testid="stSidebar"] { background-color: #f3e8ff; direction: rtl; text-align: right; }
        .report-container { background-color: #ffffff; padding: 40px; border-radius: 15px; border: 1px solid #e9d5ff; box-shadow: 0 10px 25px rgba(192,38,211,0.1); margin-top: 30px; direction: rtl; text-align: right; }
        .report-container p, .report-container h1, .report-container h2, .report-container h3, .report-container div { direction: rtl !important; text-align: right !important; color: #1e293b; }
        </style>
        """
    else:
        return """
        <style>
        .main, .stApp { direction: rtl; text-align: right; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        [data-testid="stSidebar"] { direction: rtl; text-align: right; }
        .report-container { background-color: #ffffff; padding: 40px; border-radius: 15px; border: 1px solid #e2e8f0; box-shadow: 0 10px 25px rgba(0,0,0,0.04); margin-top: 30px; direction: rtl; text-align: right; }
        .report-container p, .report-container h1, .report-container h2, .report-container h3, .report-container div { direction: rtl !important; text-align: right !important; color: #1e293b; }
        </style>
        """

st.markdown(get_theme_css(st.session_state.ui_theme), unsafe_allow_html=True)

st.title("מסוף ניהול השקעות מתקדם (Advanced Trading Terminal)")

with st.sidebar:
    st.header("הגדרות תצוגה אישיות")
    selected_theme = st.selectbox("בחר סגנון עיצוב למערכת", ["מקצועי נקי", "הייטק כהה", "חוויתי צבעוני"], index=["מקצועי נקי", "הייטק כהה", "חוויתי צבעוני"].index(st.session_state.ui_theme))
    if selected_theme != st.session_state.ui_theme:
        st.session_state.ui_theme = selected_theme
        st.rerun()
        
    st.divider()
    st.header("פעולות מסחר")
    mode = st.radio("בחר סוג פעולה", ["עסקת מניות", "מזומן", "מעקב"])
    
    if mode == "עסקת מניות":
        with st.form("t_form", clear_on_submit=True):
            tk = st.text_input("סמל מניה").upper()
            tt = st.selectbox("סוג", ["BUY", "SELL"])
            tq = st.number_input("כמות", min_value=0.0)
            tp = st.number_input("מחיר ביצוע", min_value=0.0)
            if st.form_submit_button("שגר עסקה") and tk and tq > 0:
                db_action("INSERT INTO transactions (user_id, timestamp, transaction_type, ticker_symbol, quantity, price_per_unit, commission, currency, exchange_rate) VALUES (1, ?, ?, ?, ?, ?, 0, 'USD', 1.0)", 
                          (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), tt, tk, tq, tp))
                st.cache_data.clear()
                st.rerun()
    elif mode == "מזומן":
        with st.form("c_form", clear_on_submit=True):
            ct = st.selectbox("תנועה", ["DEPOSIT", "WITHDRAW"])
            ca = st.number_input("סכום הפקדה בדולרים", min_value=0.0)
            if st.form_submit_button("עדכן מאזן") and ca > 0:
                db_action("INSERT INTO transactions (user_id, timestamp, transaction_type, ticker_symbol, quantity, price_per_unit, commission, currency, exchange_rate) VALUES (1, ?, ?, 'CASH', ?, 1.0, 0, 'USD', 1.0)", 
                          (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ct, ca))
                st.cache_data.clear()
                st.rerun()
    else:
        with st.form("w_form", clear_on_submit=True):
            tw = st.text_input("סמל מניה").upper()
            tr = st.number_input("מחיר יעד", min_value=0.0)
            nt = st.text_area("הערות מחקר")
            if st.form_submit_button("הוסף למעקב") and tw:
                db_action("INSERT INTO watchlist (user_id, ticker_symbol, target_price, notes) VALUES (1, ?, ?, ?)", (tw, tr, nt))
                st.rerun()

t1, t2, t3, t4, t5 = st.tabs(["סיכום תיק", "אחזקות והיסטוריה", "רשימת מעקב", "מחשבון הערכת שווי", "מחקר אנליסט"])

df_open, cash_balance, realized_pl, df_history = calculate_portfolio_metrics()

with t1:
    total_stock_value = df_open['שווי שוק'].sum() if not df_open.empty else 0.0
    total_portfolio_value = total_stock_value + cash_balance
    total_open_pl = df_open['רווח פתוח ($)'].sum() if not df_open.empty else 0.0
    
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(render_custom_metric("שווי נקי כולל", f"${total_portfolio_value:,.2f}", st.session_state.ui_theme), unsafe_allow_html=True)
    c2.markdown(render_custom_metric("מאזן מזומנים", f"${cash_balance:,.2f}", st.session_state.ui_theme), unsafe_allow_html=True)
    c3.markdown(render_custom_metric("רווח פתוח", f"${total_open_pl:,.2f}", st.session_state.ui_theme), unsafe_allow_html=True)
    c4.markdown(render_custom_metric("רווח ממומש", f"${realized_pl:,.2f}", st.session_state.ui_theme), unsafe_allow_html=True)
    
    if not df_open.empty:
        fig = px.pie(df_open, values='שווי שוק', names='סמל', hole=0.5, title="פיזור אחזקות נוכחי")
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#f8fafc" if st.session_state.ui_theme == "הייטק כהה" else "#0f172a"))
        st.plotly_chart(fig, use_container_width=True)

with t2:
    st.subheader("אחזקות פתוחות במניות")
    if not df_open.empty: 
        styled_df = df_open.style.format({'מחיר קנייה ממוצע': '${:.2f}', 'עלות כוללת': '${:.2f}', 'מחיר נוכחי': '${:.2f}', 'שווי שוק': '${:.2f}', 'רווח פתוח ($)': '${:.2f}', 'רווח פתוח (%)': '{:.2f}%'})
        st.dataframe(styled_df, use_container_width=True)
    
    st.subheader("יומן פעולות היסטורי")
    if not df_history.empty:
        st.dataframe(df_history.sort_values(by='timestamp', ascending=False), use_container_width=True)

with t3:
    df_w = db_action("SELECT ticker_symbol, target_price, notes FROM watchlist WHERE user_id = 1", fetch=True)
    if not df_w.empty: st.dataframe(df_w, use_container_width=True)

with t4:
    st.subheader("מחשבון היוון תזרימי מזומנים")
    dcf_target = st.text_input("הזן סמל מניה לשאיבת נתונים ראשונית").upper()
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        fcf_input = st.number_input("תזרים מזומנים חופשי בסיסי (במיליונים)", value=1000.0)
        shares_input = st.number_input("מספר מניות מונפקות (במיליונים)", value=100.0)
        growth_rate = st.slider("שיעור צמיחה שנתי צפוי לחמש השנים הקרובות", min_value=0.0, max_value=50.0, value=10.0, step=0.5) / 100
        terminal_growth = st.slider("שיעור צמיחה ארוך טווח לאחר חמש שנים", min_value=0.0, max_value=5.0, value=2.0, step=0.1) / 100
        wacc = st.slider("שיעור היוון או תשואה נדרשת", min_value=1.0, max_value=20.0, value=8.0, step=0.5) / 100
        
        if dcf_target:
            if st.button("שאב נתונים חיים מהשוק"):
                info = get_stock_info(dcf_target)
                st.session_state.dcf_fcf = info.get('freeCashflow', 0) / 1000000
                st.session_state.dcf_shares = info.get('sharesOutstanding', 1) / 1000000
                st.rerun()
                
        if 'dcf_fcf' in st.session_state:
            fcf_input = st.number_input("תזרים חופשי מעודכן", value=float(st.session_state.dcf_fcf))
            shares_input = st.number_input("מניות מעודכנות", value=float(st.session_state.dcf_shares))

    with col2:
        projected_fcf = []
        pv_fcf = []
        current_fcf = fcf_input
        
        for year in range(1, 6):
            current_fcf = current_fcf * (1 + growth_rate)
            projected_fcf.append(current_fcf)
            pv_fcf.append(current_fcf / ((1 + wacc) ** year))
            
        terminal_value = (projected_fcf[-1] * (1 + terminal_growth)) / (wacc - terminal_growth)
        pv_terminal_value = terminal_value / ((1 + wacc) ** 5)
        
        enterprise_value = sum(pv_fcf) + pv_terminal_value
        fair_value_per_share = enterprise_value / shares_input if shares_input > 0 else 0
        
        st.markdown(render_custom_metric("הערכת שווי הוגן למניה", f"${fair_value_per_share:,.2f}", st.session_state.ui_theme), unsafe_allow_html=True)
        
        df_projection = pd.DataFrame({
            "שנה": ["שנה 1", "שנה 2", "שנה 3", "שנה 4", "שנה 5", "ערך טרמינלי"],
            "תזרים חזוי": [f"${x:,.2f}M" for x in projected_fcf] + [f"${terminal_value:,.2f}M"],
            "ערך מהוון נוכחי": [f"${x:,.2f}M" for x in pv_fcf] + [f"${pv_terminal_value:,.2f}M"]
        })
        st.dataframe(df_projection, use_container_width=True)

with t5:
    st.subheader("מסוף מחקר נתונים מבוסס בינה מלאכותית")
    target = st.text_input("הזן סמל מניה לניתוח פונדמנטלי").upper()
    if target:
        with st.spinner("שולף נתונים ומפעיל מנוע אנליזה מורכב..."):
            info = get_stock_info(target)
            
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.markdown(render_custom_metric("שווי שוק", format_large_number(info.get('marketCap')), st.session_state.ui_theme), unsafe_allow_html=True)
            mc2.markdown(render_custom_metric("מכפיל רווח עתידי", info.get('forwardPE', 'N/A'), st.session_state.ui_theme), unsafe_allow_html=True)
            mc3.markdown(render_custom_metric("מכפיל צמיחה", info.get('pegRatio', 'N/A'), st.session_state.ui_theme), unsafe_allow_html=True)
            mc4.markdown(render_custom_metric("תזרים חופשי", format_large_number(info.get('freeCashflow')), st.session_state.ui_theme), unsafe_allow_html=True)
            
            summary = info.get('longBusinessSummary', '')
            metrics_text = f"Market Cap: {info.get('marketCap')}, Forward P/E: {info.get('forwardPE')}, PEG: {info.get('pegRatio')}, FCF: {info.get('freeCashflow')}"
            
            ai_report = get_ai_analysis(target, summary, metrics_text)
            st.markdown(f"<div class='report-container'>{ai_report}</div>", unsafe_allow_html=True)