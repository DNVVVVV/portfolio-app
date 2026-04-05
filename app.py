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
from supabase import create_client, Client

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
db_url = os.getenv("DATABASE_URL")
sb_url = os.getenv("SUPABASE_URL")
sb_key = os.getenv("SUPABASE_KEY")

# אתחול לקוח סופאבייס לניהול משתמשים
if sb_url and sb_key:
    supabase: Client = create_client(sb_url, sb_key)
else:
    st.error("חסרים מפתחות גישה של סופאבייס (SUPABASE_URL / SUPABASE_KEY).")

if not api_key:
    st.error("מפתח הגישה של גוגל (Gemini API Key) חסר.")

if not db_url:
    st.error("כתובת מסד הנתונים (DATABASE_URL) חסרה.")
else:
    engine = create_engine(db_url)

# ניהול מצב המשתמש במערכת
if 'user' not in st.session_state:
    st.session_state.user = None

@st.cache_data(ttl=129600)
def get_ai_analysis(ticker, summary, metrics_text):
    client = genai.Client(api_key=api_key)
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

def calculate_portfolio_metrics(user_uid):
    # שליפת נתונים רק עבור המשתמש המחובר לפי מזהה ייחודי
    df_tx = db_action("SELECT * FROM transactions WHERE user_id_cloud = %s", params=(user_uid,), fetch=True)
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
            pos['מחיר נוכחי'] = lp
            pos['שווי שוק'] = current_val
            pos['רווח פתוח ($)'] = open_pl
            pos['רווח פתוח (%)'] = (open_pl / pos['עלות כוללת']) * 100 if pos['עלות כוללת'] > 0 else 0
            open_positions.append(pos)
            
    return pd.DataFrame(open_positions), cash_balance, realized_total, df_tx

def render_custom_metric(label, value, theme_style):
    bg_color = "#ffffff"
    text_color = "#0f172a"
    label_color = "#64748b"
    border_color = "#2563eb"
    if theme_style == "הייטק כהה":
        bg_color = "#1e293b"; text_color = "#f8fafc"; label_color = "#94a3b8"; border_color = "#38bdf8"
    elif theme_style == "חוויתי צבעוני":
        bg_color = "linear-gradient(135deg, #fdf4ff 0%, #f3e8ff 100%)"; border_color = "#c026d3"
        
    return f"""
    <div style="background: {bg_color}; border-right: 5px solid {border_color}; padding: 18px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05); margin-bottom: 20px; direction: rtl; text-align: right;">
        <div style="color: {label_color}; font-size: 0.95rem; font-weight: 600; margin-bottom: 8px;">{label}</div>
        <div style="color: {text_color}; font-size: 1.7rem; font-weight: 800;">{value}</div>
    </div>
    """

# מסך כניסה והרשמה
def login_screen():
    st.title("ברוכים הבאים למערכת ניהול ההשקעות")
    tab_login, tab_signup = st.tabs(["התחברות", "יצירת חשבון חדש"])
    
    with tab_login:
        with st.form("login_form"):
            email = st.text_input("דואר אלקטרוני (Email)")
            password = st.text_input("סיסמה (Password)", type="password")
            if st.form_submit_button("כניסה למערכת"):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = res.user
                    st.rerun()
                except Exception as e:
                    st.error("שגיאה בפרטי הכניסה. ודא כי האימייל והסיסמה נכונים.")
                    
    with tab_signup:
        with st.form("signup_form"):
            new_email = st.text_input("אימייל להרשמה (Email)")
            new_password = st.text_input("בחר סיסמה (Password)", type="password")
            if st.form_submit_button("צור חשבון"):
                try:
                    supabase.auth.sign_up({"email": new_email, "password": new_password})
                    st.success("החשבון נוצר בהצלחה! כעת ניתן לעבור ללשונית התחברות.")
                except Exception as e:
                    st.error(f"שגיאה ביצירת החשבון: {str(e)}")

# בדיקה האם משתמש מחובר
if st.session_state.user is None:
    login_screen()
    st.stop()

# קבלת מזהה המשתמש המחובר מהענן
current_user_uid = st.session_state.user.id

st.set_page_config(page_title="ניהול השקעות - דוד נפתלי", layout="wide")

if 'ui_theme' not in st.session_state:
    st.session_state.ui_theme = "מקצועי נקי"

st.sidebar.write(f"שלום, {st.session_state.user.email}")
if st.sidebar.button("התנתק (Logout)"):
    st.session_state.user = None
    st.rerun()

st.title("מסוף ניהול השקעות מתקדם (Advanced Trading Terminal)")

# המשך הממשק הראשי עם הפונקציות הקודמות המותאמות ל-current_user_uid
# [כאן מופיעים הטאבים והגרפים כפי שהיו בקוד הקודם]