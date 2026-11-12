import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sqlite3
import re
from datetime import date, datetime, timedelta
import plotly.express as px

# Optional PostgreSQL import (used when DB_URL is configured)
try:
    import psycopg2
except ImportError:
    psycopg2 = None

# ==========================================
# 1. PAGE CONFIGURATION & MOBILE CSS
# ==========================================
st.set_page_config(
    page_title="Das Family Expense & Loan Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 2rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
    }
    .stButton > button, .stFormSubmitButton > button {
        min-height: 48px !important;
        font-weight: 600 !important;
        border-radius: 10px !important;
    }
    div[data-testid="stMetric"] {
        background-color: rgba(128, 128, 128, 0.08);
        border: 1px solid rgba(128, 128, 128, 0.2);
        padding: 10px 14px;
        border-radius: 12px;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.3rem !important;
    }
    button[data-baseweb="tab"] {
        font-size: 0.95rem !important;
        padding: 10px 14px !important;
    }
</style>
""", unsafe_allow_html=True)

PLOTLY_MOBILE_CONFIG = {"displayModeBar": False, "responsive": True}
RECYCLE_BIN_RETENTION_DAYS = 3

# ==========================================
# 2. INDIAN CURRENCY, PARSER & WORDS FORMATTERS
# ==========================================
def format_inr(val, decimals=0):
    """Formats numbers in Indian Standard (e.g., ₹12,26,956 or ₹3,18,885.00)."""
    if val is None or pd.isna(val):
        val = 0.0
    val = float(val)
    is_neg = val < 0
    val = abs(val)

    if decimals > 0:
        s = f"{val:.{decimals}f}"
        int_part, dec_part = s.split(".")
        dec_str = "." + dec_part
    else:
        int_part = str(int(round(val)))
        dec_str = ""

    if len(int_part) > 3:
        last3 = int_part[-3:]
        rest = int_part[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        formatted_int = ",".join(groups) + "," + last3
    else:
        formatted_int = int_part

    sign = "-" if is_neg else ""
    return f"{sign}₹{formatted_int}{dec_str}"


def clean_currency_value(val):
    """Cleans Excel strings like '₹ 3,18,885.00' or '₹79,489' into a float (318885.0)."""
    if val is None or pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "-", "nil", "null"):
        return 0.0
    cleaned = re.sub(r"[^\d.-]", "", s)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def number_to_indian_words(val):
    """Converts a numeric rupee amount into compact Indian words (e.g., '3 Lakh 18 Thousand 8 Hundred 85')."""
    if val is None or pd.isna(val) or float(val) <= 0:
        return ""
    n = int(round(float(val)))
    if n == 0:
        return ""

    parts = []
    crore = n // 10000000
    n %= 10000000
    lakh = n // 100000
    n %= 100000
    thousand = n // 1000
    n %= 1000
    hundred = n // 100
    rem = n % 100

    if crore > 0:
        parts.append(f"{crore} Crore")
    if lakh > 0:
        parts.append(f"{lakh} Lakh")
    if thousand > 0:
        parts.append(f"{thousand} Thousand")
    if hundred > 0:
        parts.append(f"{hundred} Hundred")
    if rem > 0:
        parts.append(f"{rem}")

    return " ".join(parts) + " Rupees"


def inject_live_indian_words_js():
    """Injects a keystroke listener into the popup modal for live Indian words under number inputs."""
    components.html(
        """
        <script>
        (function() {
            const parentDoc = window.parent.document;

            function toIndianWords(num) {
                if (isNaN(num) || num <= 0) return "";
                let n = Math.floor(num);
                if (n === 0) return "";
                let parts = [];
                let crore = Math.floor(n / 10000000);
                n %= 10000000;
                let lakh = Math.floor(n / 100000);
                n %= 100000;
                let thousand = Math.floor(n / 1000);
                n %= 1000;
                let hundred = Math.floor(n / 100);
                let rem = n % 100;

                if (crore > 0) parts.push(crore + " Crore");
                if (lakh > 0) parts.push(lakh + " Lakh");
                if (thousand > 0) parts.push(thousand + " Thousand");
                if (hundred > 0) parts.push(hundred + " Hundred");
                if (rem > 0) parts.push(rem);

                let dec = Math.round((num - Math.floor(num)) * 100);
                let res = parts.join(" ") + " Rupees";
                if (dec > 0) res += " & " + dec + " Paise";
                return res;
            }

            function formatINR(num) {
                if (isNaN(num) || num <= 0) return "";
                return "₹" + num.toLocaleString("en-IN", {maximumFractionDigits: 2});
            }

            function attachListeners() {
                const numInputs = parentDoc.querySelectorAll('div[data-testid="stNumberInput"] input');
                numInputs.forEach((input) => {
                    if (input.dataset.indianWordsAttached === "true") return;
                    input.dataset.indianWordsAttached = "true";

                    const wrapper = input.closest('div[data-testid="stNumberInput"]');
                    if (!wrapper) return;

                    let helper = wrapper.querySelector('.live-inr-words');
                    if (!helper) {
                        helper = parentDoc.createElement('div');
                        helper.className = 'live-inr-words';
                        helper.style.cssText = 'color: #2ecc71; font-size: 0.84rem; font-weight: 600; margin-top: 4px; min-height: 1.2rem; transition: all 0.1s ease;';
                        wrapper.appendChild(helper);
                    }

                    const updateText = () => {
                        const raw = parseFloat(input.value);
                        if (!isNaN(raw) && raw > 0) {
                            helper.textContent = "🇮🇳 " + formatINR(raw) + " — " + toIndianWords(raw);
                        } else {
                            helper.textContent = "";
                        }
                    };

                    input.addEventListener('input', updateText);
                    input.addEventListener('change', updateText);
                    updateText();
                });
            }

            attachListeners();
            const observer = new MutationObserver(attachListeners);
            observer.observe(parentDoc.body, { childList: true, subtree: true });
        })();
        </script>
        """,
        height=0,
        width=0,
    )

# ==========================================
# 3. SIMPLE FAMILY PIN AUTHENTICATION
# ==========================================
def has_secret(key):
    try:
        return key in st.secrets and bool(st.secrets[key])
    except Exception:
        return False

def check_pin():
    if not has_secret("APP_PIN"):
        return True
    if st.session_state.get("authenticated", False):
        return True

    st.markdown("### 🔒 Das Family Tracker")
    pin_input = st.text_input("Enter Family PIN:", type="password", placeholder="Tap to enter PIN")
    if st.button("🔓 Unlock Dashboard", type="primary", use_container_width=True):
        if pin_input == str(st.secrets["APP_PIN"]):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("❌ Incorrect PIN. Please try again.")
    return False

if not check_pin():
    st.stop()

# ==========================================
# 4. CACHED DATABASE ENGINE + 3-DAY RECYCLE BIN
# ==========================================
USE_POSTGRES = has_secret("DB_URL")
LOCAL_DB_NAME = "expenses.db"

@st.cache_resource
def get_pg_connection():
    return psycopg2.connect(st.secrets["DB_URL"])

def get_connection():
    if USE_POSTGRES:
        conn = get_pg_connection()
        try:
            with conn.cursor() as c:
                c.execute("SELECT 1")
        except Exception:
            st.cache_resource.clear()
            conn = get_pg_connection()
        return conn
    return sqlite3.connect(LOCAL_DB_NAME, check_same_thread=False)

def purge_expired_recycle_bin(conn=None):
    """Automatically clears Recycle Bin entries deleted more than 3 days ago."""
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = not USE_POSTGRES

    cutoff_str = (datetime.now() - timedelta(days=RECYCLE_BIN_RETENTION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute(
            "DELETE FROM transactions WHERE deleted_at IS NOT NULL AND deleted_at <> '' AND deleted_at < %s",
            (cutoff_str,)
        )
    else:
        c.execute(
            "DELETE FROM transactions WHERE deleted_at IS NOT NULL AND deleted_at <> '' AND deleted_at < ?",
            (cutoff_str,)
        )
    conn.commit()
    c.close()
    if close_after:
        conn.close()

@st.cache_resource
def init_db_once():
    conn = get_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                t_date DATE NOT NULL,
                t_type TEXT NOT NULL,
                category TEXT NOT NULL,
                sub_category TEXT NOT NULL DEFAULT 'General',
                member TEXT NOT NULL,
                amount NUMERIC(12, 2) NOT NULL,
                pending_loan NUMERIC(12, 2) NOT NULL DEFAULT 0.0,
                details TEXT,
                deleted_at TEXT DEFAULT NULL
            )
        """)
        c.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS sub_category TEXT NOT NULL DEFAULT 'General'")
        c.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS pending_loan NUMERIC(12, 2) NOT NULL DEFAULT 0.0")
        c.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS deleted_at TEXT DEFAULT NULL")
    else:
        c.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                t_date TEXT NOT NULL,
                t_type TEXT NOT NULL,
                category TEXT NOT NULL,
                sub_category TEXT NOT NULL DEFAULT 'General',
                member TEXT NOT NULL,
                amount REAL NOT NULL,
                pending_loan REAL NOT NULL DEFAULT 0.0,
                details TEXT,
                deleted_at TEXT DEFAULT NULL
            )
        """)
        c.execute("PRAGMA table_info(transactions)")
        columns = [col[1] for col in c.fetchall()]
        if "sub_category" not in columns:
            c.execute("ALTER TABLE transactions ADD COLUMN sub_category TEXT NOT NULL DEFAULT 'General'")
        if "pending_loan" not in columns:
            c.execute("ALTER TABLE transactions ADD COLUMN pending_loan REAL NOT NULL DEFAULT 0.0")
        if "deleted_at" not in columns:
            c.execute("ALTER TABLE transactions ADD COLUMN deleted_at TEXT DEFAULT NULL")
    conn.commit()
    c.close()
    purge_expired_recycle_bin(conn)
    if not USE_POSTGRES:
        conn.close()
    return True

init_db_once()

@st.cache_data(ttl=300, show_spinner=False)
def load_data():
    """Loads active (non-deleted) transactions."""
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM transactions WHERE deleted_at IS NULL OR deleted_at = '' ORDER BY t_date DESC, id DESC",
        conn
    )
    if not USE_POSTGRES:
        conn.close()

    if not df.empty:
        df["t_date"] = pd.to_datetime(df["t_date"])
        df["amount"] = df["amount"].astype(float)
        df["pending_loan"] = df["pending_loan"].fillna(0.0).astype(float)
        df["sub_category"] = df["sub_category"].fillna("General")
        df["Month_Key"] = df["t_date"].dt.strftime("%Y-%m")
        df["Month_Label"] = df["t_date"].dt.strftime("%B %Y (%Y-%m)")
        df["Record_Label"] = df.apply(
            lambda r: (
                f"#{int(r['id'])} | {r['t_date'].strftime('%Y-%m-%d')} | "
                f"{r['sub_category']} | {format_inr(r['amount'], 0)}"
                + (f" (Loan: {format_inr(r['pending_loan'], 0)})" if r["pending_loan"] > 0 else "")
                + f" • {r['member']}"
            ),
            axis=1
        )
    return df

@st.cache_data(ttl=300, show_spinner=False)
def load_recycle_bin():
    """Purges items > 3 days old and loads remaining Recycle Bin items."""
    conn = get_connection()
    purge_expired_recycle_bin(conn)
    bin_df = pd.read_sql_query(
        "SELECT * FROM transactions WHERE deleted_at IS NOT NULL AND deleted_at <> '' ORDER BY deleted_at DESC, id DESC",
        conn
    )
    if not USE_POSTGRES:
        conn.close()

    if not bin_df.empty:
        bin_df["t_date"] = pd.to_datetime(bin_df["t_date"])
        bin_df["amount"] = bin_df["amount"].astype(float)
        bin_df["pending_loan"] = bin_df["pending_loan"].fillna(0.0).astype(float)
        bin_df["deleted_dt"] = pd.to_datetime(bin_df["deleted_at"])
        now_dt = datetime.now()

        def calc_expiry_label(del_dt):
            expire_at = del_dt + timedelta(days=RECYCLE_BIN_RETENTION_DAYS)
            rem = expire_at - now_dt
            total_hours = int(max(rem.total_seconds(), 0) // 3600)
            days_left = total_hours // 24
            hrs_left = total_hours % 24
            if days_left > 0:
                return f"{days_left}d {hrs_left}h left"
            return f"{hrs_left}h left"

        bin_df["Auto_Clears_In"] = bin_df["deleted_dt"].apply(calc_expiry_label)
        bin_df["Bin_Label"] = bin_df.apply(
            lambda r: (
                f"#{int(r['id'])} | {r['t_date'].strftime('%Y-%m-%d')} | "
                f"{r['sub_category']} | {format_inr(r['amount'], 0)}"
                + (f" (Loan: {format_inr(r['pending_loan'], 0)})" if r["pending_loan"] > 0 else "")
                + f" • {r['member']} ⏳ [{r['Auto_Clears_In']}]"
            ),
            axis=1
        )
    return bin_df

def clear_all_caches():
    load_data.clear()
    load_recycle_bin.clear()

def add_transaction(t_date, t_type, category, sub_category, member, amount, pending_loan, details):
    conn = get_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("""
            INSERT INTO transactions (t_date, t_type, category, sub_category, member, amount, pending_loan, details, deleted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)
        """, (t_date, t_type, category, sub_category, member, amount, pending_loan, details))
    else:
        c.execute("""
            INSERT INTO transactions (t_date, t_type, category, sub_category, member, amount, pending_loan, details, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """, (str(t_date), t_type, category, sub_category, member, amount, pending_loan, details))
    conn.commit()
    c.close()
    if not USE_POSTGRES:
        conn.close()
    clear_all_caches()

def bulk_add_transactions(records_list):
    if not records_list:
        return
    conn = get_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.executemany("""
            INSERT INTO transactions (t_date, t_type, category, sub_category, member, amount, pending_loan, details, deleted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)
        """, records_list)
    else:
        c.executemany("""
            INSERT INTO transactions (t_date, t_type, category, sub_category, member, amount, pending_loan, details, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """, [(str(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in records_list])
    conn.commit()
    c.close()
    if not USE_POSTGRES:
        conn.close()
    clear_all_caches()

def update_transaction(t_id, t_date, t_type, category, sub_category, member, amount, pending_loan, details):
    conn = get_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("""
            UPDATE transactions
            SET t_date = %s, t_type = %s, category = %s, sub_category = %s,
                member = %s, amount = %s, pending_loan = %s, details = %s
            WHERE id = %s
        """, (t_date, t_type, category, sub_category, member, float(amount), float(pending_loan), details, int(t_id)))
    else:
        c.execute("""
            UPDATE transactions
            SET t_date = ?, t_type = ?, category = ?, sub_category = ?,
                member = ?, amount = ?, pending_loan = ?, details = ?
            WHERE id = ?
        """, (str(t_date), t_type, category, sub_category, member, float(amount), float(pending_loan), details, int(t_id)))
    conn.commit()
    c.close()
    if not USE_POSTGRES:
        conn.close()
    clear_all_caches()

def soft_delete_transactions(t_ids):
    if not t_ids:
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    c = conn.cursor()
    for t_id in t_ids:
        if USE_POSTGRES:
            c.execute("UPDATE transactions SET deleted_at = %s WHERE id = %s", (now_str, int(t_id)))
        else:
            c.execute("UPDATE transactions SET deleted_at = ? WHERE id = ?", (now_str, int(t_id)))
    conn.commit()
    c.close()
    if not USE_POSTGRES:
        conn.close()
    clear_all_caches()

def restore_transactions(t_ids):
    if not t_ids:
        return
    conn = get_connection()
    c = conn.cursor()
    for t_id in t_ids:
        if USE_POSTGRES:
            c.execute("UPDATE transactions SET deleted_at = NULL WHERE id = %s", (int(t_id),))
        else:
            c.execute("UPDATE transactions SET deleted_at = NULL WHERE id = ?", (int(t_id),))
    conn.commit()
    c.close()
    if not USE_POSTGRES:
        conn.close()
    clear_all_caches()

def permanent_delete_transactions(t_ids):
    if not t_ids:
        return
    conn = get_connection()
    c = conn.cursor()
    for t_id in t_ids:
        if USE_POSTGRES:
            c.execute("DELETE FROM transactions WHERE id = %s", (int(t_id),))
        else:
            c.execute("DELETE FROM transactions WHERE id = ?", (int(t_id),))
    conn.commit()
    c.close()
    if not USE_POSTGRES:
        conn.close()
    clear_all_caches()

# ==========================================
# 5. CONSTANTS, CATEGORIES & AUTO-MAPPER
# ==========================================
EARNING_MEMBERS = ["Amal Das", "Abhijit Das", "Aditya Das", "Other"]
EXPENSE_MEMBERS = ["Amal Das", "Abhijit Das", "Aditya Das", "Shared / Family"]

EXPENSE_CATEGORY_MAP = {
    "Loans & EMIs": ["Gold Loan", "Consumer loan", "EDU loan", "HDFC loan", "Other Loan / EMI"],
    "Credit Card Bills": ["HDFC CC bill", "AXIS CC bill", "Other CC bill"],
    "Utilities & Bills": ["Light Bill", "Gas Bill", "Mobile / Internet Bill", "Water / Other Bill"],
    "Insurance & Investments": ["LIC", "Mutual Fund", "Fixed Deposit / PPF", "Health / Vehicle Insurance"],
    "Groceries & Food": ["Grocery", "Vegetables / Fish / Meat", "Dining / HungerBox", "Tea / Snacks"],
    "Housing & Rent": ["Home rent", "House Maintenance", "Appliances & Repairs"],
    "Medical & Healthcare": ["Medicine Bill", "Doctor / Consultation", "Diagnostic / Lab Test"],
    "Transport & Fuel": ["Fuel / IndianOil", "Public Transport / Cab", "Car / Bike Maintenance"],
    "Shopping & Miscellaneous": ["Shopping & Personal", "Family Event / Gift", "Miscellaneous"]
}

INCOME_CATEGORY_MAP = {
    "Salary & Regular Income": ["Monthly Salary", "Bonus / Incentives", "Pension / Family Contribution"],
    "Business & Freelance": ["Business / Freelance", "Rental / Side Income"],
    "Investment Returns": ["Interest / Dividends", "Mutual Fund / Maturity", "Other Income"]
}

def infer_parent_category(sub_cat_name, t_type="Expense"):
    """Automatically maps a Sub-category from Excel (like 'HDFC CC bill' or 'Gold Loan') to its Parent Category."""
    s_clean = str(sub_cat_name or "").strip().lower()
    target_map = EXPENSE_CATEGORY_MAP if t_type == "Expense" else INCOME_CATEGORY_MAP

    for parent_cat, subs in target_map.items():
        for sub in subs:
            if sub.lower() == s_clean:
                return parent_cat

    if "loan" in s_clean or "emi" in s_clean:
        return "Loans & EMIs"
    if "cc" in s_clean or "card" in s_clean:
        return "Credit Card Bills"
    if "bill" in s_clean or "light" in s_clean or "gas" in s_clean or "recharge" in s_clean:
        return "Utilities & Bills"
    if "lic" in s_clean or "mutual" in s_clean or "sip" in s_clean or "insurance" in s_clean:
        return "Insurance & Investments"
    if "grocer" in s_clean or "food" in s_clean or "veg" in s_clean:
        return "Groceries & Food"
    if "rent" in s_clean or "home" in s_clean or "house" in s_clean:
        return "Housing & Rent"
    if "med" in s_clean or "doctor" in s_clean:
        return "Medical & Healthcare"
    if "fuel" in s_clean or "petrol" in s_clean or "oil" in s_clean:
        return "Transport & Fuel"

    return "Shopping & Miscellaneous" if t_type == "Expense" else "Salary & Regular Income"

df = load_data()
bin_df = load_recycle_bin()

# ==========================================
# 6. POPUP MODAL DIALOGS (@st.dialog)
# ==========================================
@st.dialog("➕ Add New Expense / Income / Loan", width="large")
def open_add_modal():
    top_col1, top_col2 = st.columns(2)
    with top_col1:
        t_type = st.radio("Transaction Type", ["Expense", "Income"], horizontal=True)
    with top_col2:
        if t_type == "Expense":
            category = st.selectbox("Category", list(EXPENSE_CATEGORY_MAP.keys()))
        else:
            category = st.selectbox("Income Category", list(INCOME_CATEGORY_MAP.keys()))

    if t_type == "Expense":
        sub_options = EXPENSE_CATEGORY_MAP[category] + ["➕ Custom Sub-category..."]
        selected_sub = st.selectbox("Sub-category", sub_options)
    else:
        sub_options = INCOME_CATEGORY_MAP[category] + ["➕ Custom Sub-category..."]
        selected_sub = st.selectbox("Income Sub-category", sub_options)

    custom_sub = ""
    if selected_sub == "➕ Custom Sub-category...":
        custom_sub = st.text_input("Enter Custom Sub-category", placeholder="e.g., Car Loan")

    f_col1, f_col2 = st.columns(2)
    with f_col1:
        t_date = st.date_input("Date", date.today())
    with f_col2:
        if t_type == "Expense":
            member = st.selectbox("Paid By / Loan Holder", EXPENSE_MEMBERS)
        else:
            member = st.selectbox("Earning Family Member", EARNING_MEMBERS)

    a_col1, a_col2 = st.columns(2)
    with a_col1:
        amount = st.number_input(
            "Monthly Paid / EMI / Income Amount (₹)",
            min_value=0.0, value=None,
            placeholder="Tap to type amount (e.g., 1500)", step=100.0,
            key="add_amount_input"
        )
        if amount and amount > 0:
            st.caption(f"🇮🇳 **{format_inr(amount)}** — *{number_to_indian_words(amount)}*")

    with a_col2:
        if t_type == "Expense":
            pending_loan = st.number_input(
                "Pending Loan Till Date (₹) [Optional]",
                min_value=0.0, value=None,
                placeholder="Tap if Loan (e.g., 318885)", step=500.0,
                key="add_loan_input"
            )
            if pending_loan and pending_loan > 0:
                st.caption(f"🇮🇳 **{format_inr(pending_loan)}** — *{number_to_indian_words(pending_loan)}*")
        else:
            pending_loan = None
            st.caption("ℹ️ Pending Loan is only used for Expense / Loan entries.")

    details = st.text_input("Details / Notes (Optional)", placeholder="e.g., Monthly bill or EMI")

    inject_live_indian_words_js()

    if st.button("💾 Save Entry", type="primary", use_container_width=True):
        clean_amount = float(amount) if amount is not None else 0.0
        clean_loan = float(pending_loan) if pending_loan is not None else 0.0
        final_sub = custom_sub.strip() if selected_sub == "➕ Custom Sub-category..." else selected_sub

        if not final_sub:
            st.error("⚠️ Please enter a valid sub-category name.")
        elif clean_amount <= 0 and clean_loan <= 0:
            st.error("⚠️ Please enter an Amount or Pending Loan greater than ₹0.")
        else:
            add_transaction(
                t_date, t_type, category, final_sub, member,
                clean_amount, clean_loan, details.strip()
            )
            st.toast(f"✅ Saved {final_sub}: {format_inr(clean_amount, 2)}", icon="💰")
            st.rerun()


@st.dialog("📥 Import Previous Data from Excel / CSV", width="large")
def open_excel_import_modal():
    st.caption(
        "Upload your `.xlsx`, `.xls`, or `.csv` file. The app automatically cleans `'₹ 3,18,885.00'` formatting, "
        "skips Total summary rows, and lets you preview/edit everything before saving!"
    )
    uploaded_file = st.file_uploader("Select your Excel or CSV file", type=["xlsx", "xls", "csv"])

    if uploaded_file is not None:
        try:
            if uploaded_file.name.lower().endswith(".csv"):
                raw_excel_df = pd.read_csv(uploaded_file)
            else:
                xl = pd.ExcelFile(uploaded_file)
                if len(xl.sheet_names) > 1:
                    selected_sheet = st.selectbox("📑 Select Excel Sheet Tab", xl.sheet_names)
                else:
                    selected_sheet = xl.sheet_names[0]
                raw_excel_df = pd.read_excel(uploaded_file, sheet_name=selected_sheet)
        except Exception as e:
            st.error(f"❌ Could not read file: {e}")
            return

        if raw_excel_df.empty:
            st.warning("The selected sheet is empty.")
            return

        cols = list(raw_excel_df.columns)
        none_opt = ["(None / Use Default)"]

        def guess_col(keywords, include_none=False):
            options = (none_opt + cols) if include_none else cols
            for c in cols:
                c_low = str(c).lower()
                if any(k in c_low for k in keywords):
                    return options.index(c)
            return 0

        st.markdown("##### 1️⃣ Map Your Excel Columns")
        m_c1, m_c2, m_c3 = st.columns(3)
        with m_c1:
            sub_col = st.selectbox(
                "Sub-category Column *",
                cols,
                index=guess_col(["sub-catego", "sub_catego", "sub", "item", "particular", "expense", "category"])
            )
        with m_c2:
            amt_col = st.selectbox(
                "Amount / Paid Column",
                none_opt + cols,
                index=guess_col(["amount", "paid", "emi", "cost", "value", "expense"], include_none=True)
            )
        with m_c3:
            loan_col = st.selectbox(
                "Pending Loan Column",
                none_opt + cols,
                index=guess_col(["pending", "loan", "balance"], include_none=True)
            )

        m_c4, m_c5, m_c6 = st.columns(3)
        with m_c4:
            date_col = st.selectbox(
                "Date Column (if in Excel)",
                none_opt + cols,
                index=guess_col(["date", "month", "day"], include_none=True)
            )
        with m_c5:
            member_col = st.selectbox(
                "Member Column (if in Excel)",
                none_opt + cols,
                index=guess_col(["member", "name", "paid by", "person"], include_none=True)
            )
        with m_c6:
            details_col = st.selectbox(
                "Details / Notes Column",
                none_opt + cols,
                index=guess_col(["detail", "note", "remark", "desc"], include_none=True)
            )

        st.markdown("##### 2️⃣ Default Values (Used if Date or Member isn't in your Excel)")
        d_c1, d_c2, d_c3 = st.columns(3)
        with d_c1:
            fallback_date = st.date_input("Default Month / Date for Imported Rows", date.today())
        with d_c2:
            fallback_member = st.selectbox("Default Family Member", EXPENSE_MEMBERS, index=2)  # Defaults to Aditya Das
        with d_c3:
            fallback_type = st.radio("Default Type", ["Expense", "Income"], horizontal=True)

        # Parse and clean rows from Excel
        parsed_rows = []
        for _, r in raw_excel_df.iterrows():
            raw_sub = r[sub_col] if sub_col in r else ""
            if pd.isna(raw_sub):
                continue
            sub_str = str(raw_sub).strip()
            # Skip empty rows or Excel 'Total' summary rows
            if not sub_str or sub_str.lower() in ("nan", "none", "total", "grand total", "sub-category", "sub category"):
                continue

            amt_val = clean_currency_value(r[amt_col]) if amt_col != "(None / Use Default)" else 0.0
            loan_val = clean_currency_value(r[loan_col]) if loan_col != "(None / Use Default)" else 0.0

            # Skip rows where both Amount and Pending Loan are 0
            if amt_val <= 0 and loan_val <= 0:
                continue

            # Parse date if available
            row_date = fallback_date
            if date_col != "(None / Use Default)" and pd.notna(r[date_col]):
                try:
                    row_date = pd.to_datetime(r[date_col]).date()
                except Exception:
                    row_date = fallback_date

            # Parse member if available
            row_member = fallback_member
            if member_col != "(None / Use Default)" and pd.notna(r[member_col]):
                m_str = str(r[member_col]).strip()
                if m_str and m_str.lower() not in ("nan", "none"):
                    row_member = m_str

            # Parse details if available
            row_details = "Imported from Excel"
            if details_col != "(None / Use Default)" and pd.notna(r[details_col]):
                d_str = str(r[details_col]).strip()
                if d_str and d_str.lower() not in ("nan", "none"):
                    row_details = d_str

            parent_cat = infer_parent_category(sub_str, fallback_type)

            parsed_rows.append({
                "Import": True,
                "Date": row_date,
                "Type": fallback_type,
                "Category": parent_cat,
                "Sub-category": sub_str,
                "Member": row_member,
                "Amount (₹)": amt_val,
                "Pending Loan (₹)": loan_val,
                "Details": row_details
            })

        if not parsed_rows:
            st.warning("⚠️ No valid rows with Amount > 0 or Pending Loan > 0 were found. Check your column mapping above.")
            return

        st.markdown("##### 3️⃣ Review & Edit Before Importing")
        preview_import_df = pd.DataFrame(parsed_rows)
        edited_import_df = st.data_editor(
            preview_import_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Import": st.column_config.CheckboxColumn("Import?", default=True),
                "Date": st.column_config.DateColumn("Date"),
                "Type": st.column_config.SelectboxColumn("Type", options=["Expense", "Income"]),
                "Category": st.column_config.SelectboxColumn(
                    "Category",
                    options=list(EXPENSE_CATEGORY_MAP.keys()) + list(INCOME_CATEGORY_MAP.keys())
                ),
                "Sub-category": st.column_config.TextColumn("Sub-category"),
                "Member": st.column_config.SelectboxColumn("Member", options=EXPENSE_MEMBERS + ["Other"]),
                "Amount (₹)": st.column_config.NumberColumn("Amount (₹)", min_value=0.0, format="%.2f"),
                "Pending Loan (₹)": st.column_config.NumberColumn("Pending Loan (₹)", min_value=0.0, format="%.2f"),
                "Details": st.column_config.TextColumn("Details")
            }
        )

        to_import = edited_import_df[edited_import_df["Import"] == True]
        imp_amt_total = to_import["Amount (₹)"].sum()
        imp_loan_total = to_import["Pending Loan (₹)"].sum()

        st.caption(
            f"✅ **{len(to_import)} rows ready** | "
            f"Total Amount: **{format_inr(imp_amt_total, 2)}** | "
            f"Total Pending Loan: **{format_inr(imp_loan_total, 2)}**"
        )

        if st.button(f"🚀 Import {len(to_import)} Rows into Database", type="primary", use_container_width=True):
            if to_import.empty:
                st.warning("Please keep at least one row checked.")
            else:
                records_to_save = [
                    (
                        row["Date"],
                        str(row["Type"]),
                        str(row["Category"]),
                        str(row["Sub-category"]).strip(),
                        str(row["Member"]),
                        float(row["Amount (₹)"] or 0.0),
                        float(row["Pending Loan (₹)"] or 0.0),
                        str(row["Details"] or "").strip()
                    )
                    for _, row in to_import.iterrows()
                ]
                bulk_add_transactions(records_to_save)
                st.toast(f"🎉 Successfully imported {len(records_to_save)} rows from Excel!", icon="📥")
                st.rerun()


@st.dialog("⚠️ Confirm Undo Last Entry", width="small")
def open_undo_confirm_modal(latest_row):
    st.warning("Are you sure you want to undo and move this latest entry to the Recycle Bin?")
    amt_val = float(latest_row["amount"])
    loan_val = float(latest_row.get("pending_loan", 0.0) or 0.0)

    st.markdown(f"""
    * **Entry ID:** `#{int(latest_row['id'])}`
    * **Date:** `{latest_row['t_date'].strftime('%Y-%m-%d')}`
    * **Type & Sub-category:** `{latest_row['t_type']}` → **{latest_row['sub_category']}**
    * **Member:** `{latest_row['member']}`
    * **Amount:** **{format_inr(amt_val, 2)}** *({number_to_indian_words(amt_val) or '₹0'})*
    """ + (f"* **Pending Loan:** **{format_inr(loan_val, 2)}** *({number_to_indian_words(loan_val)})*" if loan_val > 0 else ""))

    st.caption(f"ℹ️ You can restore this item from the 🗑️ Recycle Bin within {RECYCLE_BIN_RETENTION_DAYS} days.")

    c_yes, c_no = st.columns(2)
    with c_yes:
        if st.button("🗑️ Yes, Move to Bin", type="primary", use_container_width=True):
            soft_delete_transactions([int(latest_row["id"])])
            st.toast(f"Moved entry #{int(latest_row['id'])} to Recycle Bin!", icon="🗑️")
            st.rerun()
    with c_no:
        if st.button("❌ Cancel", use_container_width=True):
            st.rerun()


@st.dialog("🗑️ Recycle Bin (Auto-Clears Every 3 Days)", width="large")
def open_recycle_bin_modal():
    st.caption(
        f"Deleted entries are safely kept here for **{RECYCLE_BIN_RETENTION_DAYS} days** before being permanently erased."
    )
    current_bin = load_recycle_bin()

    if current_bin.empty:
        st.info("✨ Your Recycle Bin is completely empty.")
        return

    bin_map = dict(zip(current_bin["Bin_Label"], current_bin["id"]))
    selected_bin_labels = st.multiselect(
        "Select entries to Restore or Permanently Delete:",
        options=list(bin_map.keys()),
        default=list(bin_map.keys())
    )

    b_col1, b_col2 = st.columns(2)
    with b_col1:
        if st.button("♻️ Restore Selected", type="primary", use_container_width=True):
            if selected_bin_labels:
                ids_to_restore = [bin_map[lbl] for lbl in selected_bin_labels]
                restore_transactions(ids_to_restore)
                st.toast(f"♻️ Restored {len(ids_to_restore)} entry(s) to dashboard!", icon="✅")
                st.rerun()
            else:
                st.warning("Select at least one entry above.")
    with b_col2:
        if st.button("🔥 Delete Forever", use_container_width=True):
            if selected_bin_labels:
                ids_to_purge = [bin_map[lbl] for lbl in selected_bin_labels]
                permanent_delete_transactions(ids_to_purge)
                st.toast(f"🔥 Permanently deleted {len(ids_to_purge)} entry(s)!", icon="🗑️")
                st.rerun()
            else:
                st.warning("Select at least one entry above.")

    st.divider()
    disp_bin = current_bin[["id", "t_date", "sub_category", "member", "amount", "pending_loan", "Auto_Clears_In"]].copy()
    disp_bin["t_date"] = disp_bin["t_date"].dt.strftime("%Y-%m-%d")
    disp_bin["amount"] = disp_bin["amount"].apply(format_inr)
    disp_bin["pending_loan"] = disp_bin["pending_loan"].apply(format_inr)
    disp_bin.columns = ["ID", "Date", "Sub-category", "Member", "Amount", "Pending Loan", "Expires In"]
    st.dataframe(disp_bin, use_container_width=True, hide_index=True)


@st.dialog("🔄 Copy / Auto-Fetch Last Month's Data", width="large")
def open_copy_modal():
    if df.empty:
        st.info("No previous month data available to copy yet.")
        return

    st.caption(
        "Uncheck any one-time items or tap any number in the table to adjust the amount before importing."
    )
    avail_months = df.sort_values("Month_Key", ascending=False)["Month_Label"].unique()

    cl_col1, cl_col2 = st.columns(2)
    with cl_col1:
        source_month = st.selectbox("1️⃣ Copy From Month", avail_months)
    with cl_col2:
        target_date = st.date_input("2️⃣ New Month Date", date.today())

    clone_filter = st.radio(
        "3️⃣ What to Fetch?",
        ["Only Expenses & Loans", "Both Expenses & Income"],
        horizontal=True
    )

    src_df = df[df["Month_Label"] == source_month].copy()
    if clone_filter == "Only Expenses & Loans":
        src_df = src_df[src_df["t_type"] == "Expense"]

    if src_df.empty:
        st.warning("No matching entries found in the selected source month.")
        return

    src_df = src_df.sort_values("id", ascending=True)
    preview_df = pd.DataFrame({
        "Copy": True,
        "Type": src_df["t_type"],
        "Category": src_df["category"],
        "Sub-category": src_df["sub_category"],
        "Member": src_df["member"],
        "Amount (₹)": src_df["amount"],
        "Pending Loan (₹)": src_df["pending_loan"],
        "Details": src_df["details"].fillna("")
    })

    edited_clone_df = st.data_editor(
        preview_df, hide_index=True, use_container_width=True,
        column_config={
            "Copy": st.column_config.CheckboxColumn("Copy?", default=True),
            "Type": st.column_config.TextColumn("Type", disabled=True),
            "Category": st.column_config.TextColumn("Category", disabled=True),
            "Sub-category": st.column_config.TextColumn("Sub-category"),
            "Member": st.column_config.SelectboxColumn("Member", options=EXPENSE_MEMBERS + ["Other"]),
            "Amount (₹)": st.column_config.NumberColumn("Amount (₹)", min_value=0.0, format="%.2f"),
            "Pending Loan (₹)": st.column_config.NumberColumn("Pending Loan (₹)", min_value=0.0, format="%.2f"),
            "Details": st.column_config.TextColumn("Details")
        }
    )

    selected_rows = edited_clone_df[edited_clone_df["Copy"] == True]
    exp_sum = selected_rows[selected_rows["Type"] == "Expense"]["Amount (₹)"].sum()
    loan_sum = selected_rows["Pending Loan (₹)"].sum()

    st.caption(
        f"✅ **{len(selected_rows)} entries selected** | "
        f"Total Expense: **{format_inr(exp_sum, 2)}** | "
        f"Total Pending Loan: **{format_inr(loan_sum, 2)}**"
    )

    if st.button(
        f"🚀 Import {len(selected_rows)} Entries to {target_date.strftime('%B %Y')}",
        type="primary", use_container_width=True
    ):
        if selected_rows.empty:
            st.warning("⚠️ Please keep at least one row checked to import.")
        else:
            records_to_insert = [
                (
                    target_date, str(row["Type"]), str(row["Category"]),
                    str(row["Sub-category"]).strip(), str(row["Member"]),
                    float(row["Amount (₹)"] or 0.0), float(row["Pending Loan (₹)"] or 0.0),
                    str(row["Details"] or "").strip()
                )
                for _, row in selected_rows.iterrows()
            ]
            bulk_add_transactions(records_to_insert)
            st.toast(f"🎉 Imported {len(records_to_insert)} entries!", icon="✅")
            st.rerun()


@st.dialog("✏️ Modify / Edit Entry", width="large")
def open_modify_modal(target_df):
    if target_df.empty:
        st.info("No records available to modify.")
        return

    records_map = dict(zip(target_df["Record_Label"], target_df["id"]))
    selected_label = st.selectbox(
        "Select the entry you want to modify:",
        options=list(records_map.keys())
    )

    rec_id = records_map[selected_label]
    rec_row = target_df[target_df["id"] == rec_id].iloc[0]

    mc1, mc2 = st.columns(2)
    with mc1:
        type_opts = ["Expense", "Income"]
        default_type_idx = type_opts.index(rec_row["t_type"]) if rec_row["t_type"] in type_opts else 0
        edit_type = st.radio(
            "Transaction Type", type_opts, index=default_type_idx,
            horizontal=True, key=f"mod_type_{rec_id}"
        )

    cat_map = EXPENSE_CATEGORY_MAP if edit_type == "Expense" else INCOME_CATEGORY_MAP
    cat_list = list(cat_map.keys())
    default_cat_idx = cat_list.index(rec_row["category"]) if rec_row["category"] in cat_list else 0

    with mc2:
        edit_category = st.selectbox(
            "Category", cat_list, index=default_cat_idx, key=f"mod_cat_{rec_id}"
        )

    sub_list = list(cat_map[edit_category])
    current_sub = str(rec_row["sub_category"])
    if current_sub not in sub_list:
        sub_list.insert(0, current_sub)
    sub_list.append("➕ Custom Sub-category...")
    default_sub_idx = sub_list.index(current_sub)

    edit_sub_choice = st.selectbox(
        "Sub-category", sub_list, index=default_sub_idx, key=f"mod_sub_{rec_id}"
    )

    custom_edit_sub = ""
    if edit_sub_choice == "➕ Custom Sub-category...":
        custom_edit_sub = st.text_input(
            "Enter Custom Sub-category", value=current_sub, key=f"mod_cust_sub_{rec_id}"
        )

    fc1, fc2 = st.columns(2)
    with fc1:
        edit_date = st.date_input("Date", value=rec_row["t_date"].date(), key=f"mod_date_{rec_id}")
    with fc2:
        mem_list = list(EXPENSE_MEMBERS if edit_type == "Expense" else EARNING_MEMBERS)
        if rec_row["member"] not in mem_list:
            mem_list.insert(0, rec_row["member"])
        edit_member = st.selectbox(
            "Member", mem_list, index=mem_list.index(rec_row["member"]), key=f"mod_mem_{rec_id}"
        )

    fc3, fc4 = st.columns(2)
    with fc3:
        edit_amount = st.number_input(
            "Amount Paid / Income (₹)", min_value=0.0,
            value=float(rec_row["amount"]), format="%.2f", step=100.0,
            key=f"mod_amt_{rec_id}"
        )
        if edit_amount and edit_amount > 0:
            st.caption(f"🇮🇳 **{format_inr(edit_amount)}** — *{number_to_indian_words(edit_amount)}*")
    with fc4:
        if edit_type == "Expense":
            edit_pending_loan = st.number_input(
                "Pending Loan Balance (₹)", min_value=0.0,
                value=float(rec_row["pending_loan"]), format="%.2f", step=500.0,
                key=f"mod_loan_{rec_id}"
            )
            if edit_pending_loan and edit_pending_loan > 0:
                st.caption(f"🇮🇳 **{format_inr(edit_pending_loan)}** — *{number_to_indian_words(edit_pending_loan)}*")
        else:
            edit_pending_loan = 0.0
            st.caption("Pending Loan is ₹0 for Income entries.")

    edit_details = st.text_input("Details / Notes", value=str(rec_row["details"] or ""), key=f"mod_det_{rec_id}")

    inject_live_indian_words_js()

    if st.button("💾 Save Changes", type="primary", use_container_width=True):
        final_sub_val = custom_edit_sub.strip() if edit_sub_choice == "➕ Custom Sub-category..." else edit_sub_choice
        if not final_sub_val:
            st.error("⚠️ Please provide a valid sub-category name.")
        elif (edit_amount or 0.0) <= 0 and (edit_pending_loan or 0.0) <= 0:
            st.error("⚠️ Please enter an Amount or Pending Loan greater than ₹0.")
        else:
            update_transaction(
                rec_id, edit_date, edit_type, edit_category,
                final_sub_val, edit_member, float(edit_amount or 0.0),
                float(edit_pending_loan or 0.0), edit_details.strip()
            )
            st.toast(f"✅ Entry #{rec_id} ({final_sub_val}) updated!", icon="✏️")
            st.rerun()


@st.dialog("🗑️ Move Wrong Entries to Recycle Bin", width="large")
def open_delete_modal(target_df, scope_label="Selected Month"):
    if target_df.empty:
        st.info("No records available to delete.")
        return

    st.caption(
        f"Showing records from: **{scope_label}** • Deleted items stay in the Recycle Bin for {RECYCLE_BIN_RETENTION_DAYS} days."
    )
    records_map = dict(zip(target_df["Record_Label"], target_df["id"]))
    to_delete = st.multiselect(
        "Select one or more entries to move to the Recycle Bin:",
        options=list(records_map.keys()),
        placeholder="Tap to pick or search entries..."
    )

    if st.button("🗑️ Move Selected to Recycle Bin", type="primary", use_container_width=True):
        if to_delete:
            ids_to_remove = [records_map[label] for label in to_delete]
            soft_delete_transactions(ids_to_remove)
            st.toast(f"🗑️ Moved {len(ids_to_remove)} entry(s) to Recycle Bin!", icon="✅")
            st.rerun()
        else:
            st.warning("⚠️ Please select at least one entry above.")

# ==========================================
# 7. TOP ACTION BUTTON BAR (POPUP TRIGGERS)
# ==========================================
st.markdown("### 💰 Das Family Expense & Loan Tracker")

bin_count = len(bin_df)
bin_btn_label = f"🗑️ Bin ({bin_count})" if bin_count > 0 else "🗑️ Bin"

if not df.empty:
    btn_c1, btn_c2, btn_c3, btn_c4, btn_c5, btn_c6 = st.columns(6)
    with btn_c1:
        if st.button("➕ Add Entry", type="primary", use_container_width=True):
            open_add_modal()
    with btn_c2:
        if st.button("📥 Import Excel", use_container_width=True):
            open_excel_import_modal()
    with btn_c3:
        if st.button("🔄 Copy Month", use_container_width=True):
            open_copy_modal()
    with btn_c4:
        if st.button("✏️ Modify", use_container_width=True):
            open_modify_modal(df)
    with btn_c5:
        latest_row = df.iloc[0]
        if st.button(f"↩️ Undo (#{int(latest_row['id'])})", use_container_width=True):
            open_undo_confirm_modal(latest_row)
    with btn_c6:
        if st.button(bin_btn_label, use_container_width=True):
            open_recycle_bin_modal()
else:
    empty_c1, empty_c2, empty_c3 = st.columns([2, 2, 1])
    with empty_c1:
        if st.button("➕ Add First Entry", type="primary", use_container_width=True):
            open_add_modal()
    with empty_c2:
        if st.button("📥 Import Previous Data from Excel", use_container_width=True):
            open_excel_import_modal()
    with empty_c3:
        if st.button(bin_btn_label, use_container_width=True):
            open_recycle_bin_modal()

# ==========================================
# 8. MAIN DASHBOARD (INDIAN NUMBER FORMAT)
# ==========================================
if df.empty:
    st.info("👋 Tap **➕ Add First Entry** or **📥 Import Previous Data from Excel** above to get started!")
else:
    tab_monthly, tab_loans, tab_trends, tab_records = st.tabs([
        "📅 Monthly", "🏦 Loans", "📈 Trends", "📋 History"
    ])

    # ------------------------------------------
    # TAB 1: MONTH-WISE DASHBOARD
    # ------------------------------------------
    with tab_monthly:
        month_options = df.sort_values("Month_Key", ascending=False)["Month_Label"].unique()

        col_select, col_chart_style = st.columns([1.2, 1.8])
        with col_select:
            selected_month = st.selectbox("🗓️ Select Month", month_options)
        with col_chart_style:
            chart_style = st.radio(
                "📊 Chart Style",
                ["PieChart (Donut)", "PieChart (Solid)", "Bar Chart"],
                horizontal=True
            )

        with st.expander("👨‍👩‍👦 Filter by Family Member (All Selected)", expanded=False):
            selected_members = st.multiselect(
                "Select Family Members",
                options=df["member"].unique(),
                default=list(df["member"].unique())
            )

        m_df = df[(df["Month_Label"] == selected_month) & (df["member"].isin(selected_members))]

        m_income = m_df[m_df["t_type"] == "Income"]["amount"].sum()
        m_expense = m_df[m_df["t_type"] == "Expense"]["amount"].sum()
        m_balance = m_income - m_expense
        m_pending_loan = m_df["pending_loan"].sum()

        r1_c1, r1_c2 = st.columns(2)
        r1_c1.metric("Monthly Income", format_inr(m_income))
        r1_c2.metric("Monthly Expense", format_inr(m_expense))

        r2_c1, r2_c2 = st.columns(2)
        r2_c1.metric("Net Savings", format_inr(m_balance), delta=format_inr(m_balance))
        r2_c2.metric("Pending Loan", format_inr(m_pending_loan))

        m_act1, m_act2 = st.columns(2)
        with m_act1:
            if st.button(f"✏️ Modify Entry in {selected_month.split(' ')[0]}", use_container_width=True, key="btn_mod_m"):
                open_modify_modal(m_df)
        with m_act2:
            if st.button(f"🗑️ Delete Entry in {selected_month.split(' ')[0]}", use_container_width=True, key="btn_del_m"):
                open_delete_modal(m_df, scope_label=selected_month)

        st.divider()

        exp_m_df = m_df[m_df["t_type"] == "Expense"]
        inc_m_df = m_df[m_df["t_type"] == "Income"]
        loan_m_df = m_df[m_df["pending_loan"] > 0]

        hole_size = 0.42 if chart_style == "PieChart (Donut)" else 0.0

        ch1, ch2 = st.columns(2)
        with ch1:
            st.subheader("🥧 Category-Wise Expense")
            if not exp_m_df.empty and exp_m_df["amount"].sum() > 0:
                cat_grp = exp_m_df.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=True)
                cat_grp["INR_Label"] = cat_grp["amount"].apply(format_inr)
                if "PieChart" in chart_style:
                    fig_cat = px.pie(
                        cat_grp, values="amount", names="category", hole=hole_size,
                        custom_data=["INR_Label"],
                        color_discrete_sequence=px.colors.qualitative.Pastel
                    )
                    fig_cat.update_traces(
                        textposition="inside", textinfo="percent+label",
                        hovertemplate="<b>%{label}</b><br>Amount: %{customdata[0]}<br>Share: %{percent}<extra></extra>"
                    )
                    fig_cat.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                    st.plotly_chart(fig_cat, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    fig_cat_bar = px.bar(
                        cat_grp, x="amount", y="category", color="category", orientation="h",
                        text="INR_Label",
                        labels={"category": "Category", "amount": "Expense (₹)"}
                    )
                    fig_cat_bar.update_traces(hovertemplate="<b>%{y}</b><br>Expense: %{text}<extra></extra>")
                    fig_cat_bar.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                    st.plotly_chart(fig_cat_bar, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
            else:
                st.info("No expenses recorded for this month.")

        with ch2:
            st.subheader("🎯 Sub-Category Expense")
            if not exp_m_df.empty and exp_m_df["amount"].sum() > 0:
                sub_grp = exp_m_df.groupby(["sub_category", "category"], as_index=False)["amount"].sum().sort_values("amount", ascending=True)
                sub_grp["INR_Label"] = sub_grp["amount"].apply(format_inr)
                if "PieChart" in chart_style:
                    fig_sub_pie = px.pie(
                        sub_grp, values="amount", names="sub_category", hole=hole_size,
                        custom_data=["INR_Label"],
                        color_discrete_sequence=px.colors.qualitative.Safe
                    )
                    fig_sub_pie.update_traces(
                        textposition="inside", textinfo="percent+label",
                        hovertemplate="<b>%{label}</b><br>Amount: %{customdata[0]}<br>Share: %{percent}<extra></extra>"
                    )
                    fig_sub_pie.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                    st.plotly_chart(fig_sub_pie, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    fig_sub_bar = px.bar(
                        sub_grp, x="amount", y="sub_category", color="category", orientation="h",
                        text="INR_Label",
                        labels={"sub_category": "Sub-category", "amount": "Expense (₹)", "category": "Category"}
                    )
                    fig_sub_bar.update_traces(hovertemplate="<b>%{y}</b><br>Expense: %{text}<extra></extra>")
                    fig_sub_bar.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                    st.plotly_chart(fig_sub_bar, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
            else:
                st.info("No expenses recorded for this month.")

        ch3, ch4 = st.columns(2)
        with ch3:
            st.subheader("👨‍👩‍👦 Family Member Income")
            if not inc_m_df.empty and inc_m_df["amount"].sum() > 0:
                mem_inc_summary = inc_m_df.groupby("member", as_index=False)["amount"].sum()
                mem_inc_summary["INR_Label"] = mem_inc_summary["amount"].apply(format_inr)
                if "PieChart" in chart_style:
                    fig_inc_pie = px.pie(
                        mem_inc_summary, values="amount", names="member", hole=hole_size,
                        custom_data=["INR_Label"],
                        color_discrete_sequence=px.colors.qualitative.Set2
                    )
                    fig_inc_pie.update_traces(
                        textposition="inside", textinfo="percent+label",
                        hovertemplate="<b>%{label}</b><br>Income: %{customdata[0]}<extra></extra>"
                    )
                    fig_inc_pie.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                    st.plotly_chart(fig_inc_pie, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    fig_inc_bar = px.bar(
                        mem_inc_summary, x="member", y="amount", color="member",
                        text="INR_Label",
                        labels={"member": "Family Member", "amount": "Income (₹)"}
                    )
                    fig_inc_bar.update_traces(hovertemplate="<b>%{x}</b><br>Income: %{text}<extra></extra>")
                    fig_inc_bar.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                    st.plotly_chart(fig_inc_bar, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
            else:
                st.info("No income recorded for this month.")

        with ch4:
            st.subheader("🏦 Pending Loan Breakdown")
            if not loan_m_df.empty:
                loan_grp = loan_m_df.groupby(["sub_category", "member"], as_index=False)["pending_loan"].sum().sort_values("pending_loan", ascending=True)
                loan_grp["INR_Label"] = loan_grp["pending_loan"].apply(format_inr)
                if "PieChart" in chart_style:
                    fig_loan_pie = px.pie(
                        loan_grp, values="pending_loan", names="sub_category", hole=hole_size,
                        custom_data=["INR_Label"],
                        color_discrete_sequence=px.colors.qualitative.Bold
                    )
                    fig_loan_pie.update_traces(
                        textposition="inside", textinfo="percent+label",
                        hovertemplate="<b>%{label}</b><br>Pending Loan: %{customdata[0]}<extra></extra>"
                    )
                    fig_loan_pie.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                    st.plotly_chart(fig_loan_pie, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    fig_loan_bar = px.bar(
                        loan_grp, x="pending_loan", y="sub_category", color="member", orientation="h",
                        text="INR_Label",
                        labels={"sub_category": "Loan Type", "pending_loan": "Pending Balance (₹)", "member": "Member"}
                    )
                    fig_loan_bar.update_traces(hovertemplate="<b>%{y}</b><br>Pending Loan: %{text}<extra></extra>")
                    fig_loan_bar.update_layout(margin=dict(t=10, b=10, l=10, r=10))
                    st.plotly_chart(fig_loan_bar, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
            else:
                st.info("No pending loans recorded for this month.")

        t_col1, t_col2 = st.columns(2)
        with t_col1:
            st.subheader("📂 Sub-Category Summary")
            if not exp_m_df.empty:
                sub_table = exp_m_df.groupby(["sub_category", "category"], as_index=False).agg(
                    Paid=("amount", "sum"), Loan=("pending_loan", "sum")
                ).sort_values("Paid", ascending=False)
                sub_table["Paid"] = sub_table["Paid"].apply(format_inr)
                sub_table["Loan"] = sub_table["Loan"].apply(format_inr)
                sub_table.columns = ["Sub-category", "Category", "Paid", "Pending Loan"]
                st.dataframe(sub_table, use_container_width=True, hide_index=True)

        with t_col2:
            st.subheader("💳 Member Summary")
            if not exp_m_df.empty:
                mem_exp_table = exp_m_df.groupby("member", as_index=False).agg(
                    Entries=("id", "count"), Total_Paid=("amount", "sum"), Total_Pending_Loan=("pending_loan", "sum")
                ).sort_values("Total_Paid", ascending=False)
                mem_exp_table["Total_Paid"] = mem_exp_table["Total_Paid"].apply(format_inr)
                mem_exp_table["Total_Pending_Loan"] = mem_exp_table["Total_Pending_Loan"].apply(format_inr)
                mem_exp_table.columns = ["Member", "Items", "Paid", "Pending Loan"]
                st.dataframe(mem_exp_table, use_container_width=True, hide_index=True)

    # ------------------------------------------
    # TAB 2: DEDICATED PENDING LOAN TRACKER
    # ------------------------------------------
    with tab_loans:
        st.subheader("🏦 Pending Loan Status Till Date")
        loan_all_df = df[df["pending_loan"] > 0]

        if loan_all_df.empty:
            st.info("No Pending Loan balances entered yet. Tap '➕ Add Entry' or '📥 Import Excel' above.")
        else:
            loan_months = loan_all_df.sort_values("Month_Key", ascending=False)["Month_Label"].unique()
            sel_loan_month = st.selectbox("🗓️ Select Month", loan_months, key="loan_month_sel")

            cur_loan_df = loan_all_df[loan_all_df["Month_Label"] == sel_loan_month]
            total_pending_till_date = cur_loan_df["pending_loan"].sum()
            total_emi_paid_month = cur_loan_df["amount"].sum()

            lk1, lk2 = st.columns(2)
            lk1.metric("Total Pending Loan", format_inr(total_pending_till_date))
            lk2.metric("EMIs Paid This Month", format_inr(total_emi_paid_month))

            if st.button(f"✏️ Modify a Loan Entry in {sel_loan_month.split(' ')[0]}", use_container_width=True, key="btn_mod_loan"):
                open_modify_modal(cur_loan_df)

            st.divider()

            lc1, lc2 = st.columns(2)
            with lc1:
                st.subheader("📋 Itemized Pending Loans")
                loan_list_disp = cur_loan_df[["sub_category", "member", "amount", "pending_loan", "details"]].copy()
                loan_list_disp["amount"] = loan_list_disp["amount"].apply(lambda x: format_inr(x, 2))
                loan_list_disp["pending_loan"] = loan_list_disp["pending_loan"].apply(lambda x: format_inr(x, 2))
                loan_list_disp.columns = ["Loan Type", "Member", "EMI Paid", "Pending Loan", "Details"]
                st.dataframe(loan_list_disp, use_container_width=True, hide_index=True)
                st.success(f"**Total Loan Pending ({sel_loan_month}): {format_inr(total_pending_till_date, 2)}**")

            with lc2:
                st.subheader("📉 Month-over-Month Pending Loan")
                mom_loan = loan_all_df.groupby("Month_Key", as_index=False)["pending_loan"].sum().sort_values("Month_Key")
                mom_loan["INR_Label"] = mom_loan["pending_loan"].apply(format_inr)
                fig_loan_trend = px.bar(
                    mom_loan, x="Month_Key", y="pending_loan", text="INR_Label",
                    color_discrete_sequence=["#e67e22"],
                    labels={"Month_Key": "Month", "pending_loan": "Pending Loan (₹)"}
                )
                fig_loan_trend.update_traces(hovertemplate="<b>%{x}</b><br>Total Pending: %{text}<extra></extra>")
                fig_loan_trend.update_layout(margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig_loan_trend, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

    # ------------------------------------------
    # TAB 3: ALL-TIME & MULTI-MONTH TRENDS
    # ------------------------------------------
    with tab_trends:
        all_inc = df[df["t_type"] == "Income"]["amount"].sum()
        all_exp = df[df["t_type"] == "Expense"]["amount"].sum()
        all_bal = all_inc - all_exp

        latest_month_key = df["Month_Key"].max()
        latest_pending_loan = df[df["Month_Key"] == latest_month_key]["pending_loan"].sum()

        a1, a2 = st.columns(2)
        a1.metric("All-Time Income", format_inr(all_inc))
        a2.metric("All-Time Expense", format_inr(all_exp))

        a3, a4 = st.columns(2)
        a3.metric("All-Time Net Savings", format_inr(all_bal))
        a4.metric(f"Latest Pending Loan ({latest_month_key})", format_inr(latest_pending_loan))

        st.divider()

        st.subheader("📊 Monthly Income vs. Expense")
        mom_df = df.groupby(["Month_Key", "t_type"], as_index=False)["amount"].sum().sort_values("Month_Key")
        mom_df["INR_Label"] = mom_df["amount"].apply(format_inr)
        fig_mom = px.bar(
            mom_df, x="Month_Key", y="amount", color="t_type", barmode="group", text="INR_Label",
            color_discrete_map={"Income": "#2ecc71", "Expense": "#e74c3c"},
            labels={"Month_Key": "Month", "amount": "Amount (₹)", "t_type": "Type"}
        )
        fig_mom.update_traces(hovertemplate="<b>%{x}</b><br>%{fullData.name}: %{text}<extra></extra>")
        fig_mom.update_layout(margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_mom, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

        st.subheader("📈 Sub-Category Spending Trend")
        all_exp_df = df[df["t_type"] == "Expense"]
        if not all_exp_df.empty:
            mom_sub = all_exp_df.groupby(["Month_Key", "sub_category"], as_index=False)["amount"].sum().sort_values("Month_Key")
            mom_sub["INR_Label"] = mom_sub["amount"].apply(format_inr)
            fig_mom_sub = px.bar(
                mom_sub, x="Month_Key", y="amount", color="sub_category",
                custom_data=["INR_Label"],
                labels={"Month_Key": "Month", "amount": "Expense (₹)", "sub_category": "Sub-category"}
            )
            fig_mom_sub.update_traces(hovertemplate="<b>%{x}</b><br>Amount: %{customdata[0]}<extra></extra>")
            fig_mom_sub.update_layout(margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig_mom_sub, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

    # ------------------------------------------
    # TAB 4: ALL RECORDS, POPUP EDIT/DELETE & CSV EXPORT
    # ------------------------------------------
    with tab_records:
        h_btn1, h_btn2, h_btn3, h_btn4 = st.columns(4)
        with h_btn1:
            if st.button("📥 Import Excel", use_container_width=True, key="btn_imp_all"):
                open_excel_import_modal()
        with h_btn2:
            if st.button("✏️ Modify Entry", use_container_width=True, key="btn_mod_all"):
                open_modify_modal(df)
        with h_btn3:
            if st.button("🗑️ Move to Bin", use_container_width=True, key="btn_del_all"):
                open_delete_modal(df, scope_label="All Months")
        with h_btn4:
            if st.button(bin_btn_label, use_container_width=True, key="btn_bin_all"):
                open_recycle_bin_modal()

        st.divider()
        st.subheader("📋 Complete History (Indian Format)")

        disp_df = df[["id", "t_date", "t_type", "sub_category", "member", "amount", "pending_loan", "category", "details"]].copy()
        disp_df["t_date"] = disp_df["t_date"].dt.strftime("%Y-%m-%d")
        disp_df["amount"] = disp_df["amount"].apply(lambda x: format_inr(x, 2))
        disp_df["pending_loan"] = disp_df["pending_loan"].apply(lambda x: format_inr(x, 2))
        disp_df.columns = [
            "ID", "Date", "Type", "Sub-category", "Member",
            "Amount (₹)", "Pending Loan (₹)", "Category", "Details"
        ]

        raw_csv_df = df[["id", "t_date", "t_type", "sub_category", "member", "amount", "pending_loan", "category", "details"]].copy()
        raw_csv_df["t_date"] = raw_csv_df["t_date"].dt.strftime("%Y-%m-%d")
        raw_csv_df.columns = disp_df.columns
        csv_bytes = raw_csv_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="📥 Download Full History as CSV",
            data=csv_bytes,
            file_name=f"das_family_finances_{date.today()}.csv",
            mime="text/csv",
            use_container_width=True
        )

        st.dataframe(disp_df, use_container_width=True, hide_index=True)

# Footer status badge
st.caption(
    f"⚡ Fast Cached Mode | 🇮🇳 Indian Format | 🗑️ {RECYCLE_BIN_RETENTION_DAYS}-Day Recycle Bin | "
    + ("🟢 Cloud PostgreSQL" if USE_POSTGRES else "🟡 Local SQLite (`expenses.db`)")
)