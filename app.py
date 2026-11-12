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
# 1. PAGE CONFIGURATION & MOBILE-FIRST CSS
# ==========================================
st.set_page_config(
    page_title="Das Family Expense & Loan Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Responsive CSS:
# - Fixes top header clipping on mobile
# - Forces 2-column side-by-side KPI metrics & multi-column button grid on phone
# - Keeps desktop/laptop layout spacious
st.markdown("""
<style>
    .block-container {
        padding-top: 2.8rem !important;
        padding-bottom: 2rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
    }
    .app-top-title {
        font-size: 1.55rem;
        font-weight: 700;
        margin-top: 0.2rem;
        margin-bottom: 0.6rem;
        line-height: 1.25;
    }
    /* Desktop / Laptop Button Styling */
    .stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
        min-height: 44px !important;
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

    /* Mobile Phone Overrides (Samsung S25+ & screens <= 768px) */
    @media (max-width: 768px) {
        .block-container {
            padding-top: 2.6rem !important;
            padding-left: 0.45rem !important;
            padding-right: 0.45rem !important;
        }
        .app-top-title {
            font-size: 1.18rem !important;
            margin-top: 0.1rem !important;
            margin-bottom: 0.45rem !important;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        /* Keep horizontal blocks in a 2-column or 3-column grid instead of 1-column vertical stack */
        div[data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: wrap !important;
            gap: 6px !important;
        }
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
            flex: 1 1 calc(50% - 6px) !important;
            min-width: calc(50% - 6px) !important;
            max-width: calc(50% - 6px) !important;
        }
        /* Compact Buttons on Phone */
        .stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
            min-height: 34px !important;
            height: 34px !important;
            padding: 2px 8px !important;
            font-size: 0.76rem !important;
            border-radius: 8px !important;
            width: 100% !important;
        }
        /* Compact 2-Column KPI Cards on Phone */
        div[data-testid="stMetric"] {
            padding: 8px 10px !important;
            border-radius: 10px !important;
        }
        div[data-testid="stMetricLabel"] p {
            font-size: 0.75rem !important;
        }
        div[data-testid="stMetricValue"] {
            font-size: 1.05rem !important;
        }
        div[data-testid="stMetricDelta"] {
            font-size: 0.72rem !important;
        }
        button[data-baseweb="tab"] {
            font-size: 0.80rem !important;
            padding: 6px 8px !important;
        }
        h3, .stSubheader {
            font-size: 1.0rem !important;
        }
    }
</style>
""", unsafe_allow_html=True)

PLOTLY_MOBILE_CONFIG = {"displayModeBar": False, "responsive": True}
CHART_HEIGHT = 250  # Compact chart height for mobile & desktop
RECYCLE_BIN_RETENTION_DAYS = 3
SALARY_CUTOFF_DAY = 24  # Salaries credited on or after the 24th count toward next month's budget

# ==========================================
# 2. INDIAN CURRENCY, PARSER & SALARY SHIFT
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
    """Cleans Excel/CSV strings like '₹ 3,18,885.00' or '₹79,489' into a float (318885.0)."""
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


def get_effective_accounting_date(row):
    """
    If an Income transaction is a Salary credited on the last working days of the month
    (day >= 24, e.g. 30th Oct Friday), shifts its effective accounting month to the 1st of
    the NEXT month (e.g. Nov) so it funds the upcoming month's expenses!
    """
    dt = row["t_date"]
    t_type = str(row.get("t_type", ""))
    sub_cat = str(row.get("sub_category", "")).lower()
    details = str(row.get("details", "")).lower()

    is_salary = (
        t_type == "Income" and (
            "salary" in sub_cat or
            "salary" in details or
            "tata consultancy" in details
        )
    )

    if is_salary and dt.day >= SALARY_CUTOFF_DAY:
        if dt.month == 12:
            return pd.Timestamp(year=dt.year + 1, month=1, day=1)
        else:
            return pd.Timestamp(year=dt.year, month=dt.month + 1, day=1)

    return pd.Timestamp(year=dt.year, month=dt.month, day=1)


def style_compact_chart(fig, show_legend=False):
    """Applies compact mobile-friendly height and tight margins to any Plotly chart."""
    fig.update_layout(
        height=CHART_HEIGHT,
        margin=dict(t=8, b=8, l=8, r=8),
        showlegend=show_legend,
        font=dict(size=11)
    )
    return fig


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
                        helper.style.cssText = 'color: #2ecc71; font-size: 0.80rem; font-weight: 600; margin-top: 3px; min-height: 1.1rem; transition: all 0.1s ease;';
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

    st.markdown('<div class="app-top-title">🔒 Das Family Tracker</div>', unsafe_allow_html=True)
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
# 4. CACHED DATABASE ENGINE + BANK & RECYCLE BIN
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
                bank TEXT NOT NULL DEFAULT 'SBI',
                t_type TEXT NOT NULL,
                category TEXT NOT NULL,
                sub_category TEXT NOT NULL DEFAULT 'Miscellaneous',
                member TEXT NOT NULL,
                amount NUMERIC(12, 2) NOT NULL,
                pending_loan NUMERIC(12, 2) NOT NULL DEFAULT 0.0,
                details TEXT,
                deleted_at TEXT DEFAULT NULL
            )
        """)
        c.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS bank TEXT NOT NULL DEFAULT 'SBI'")
        c.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS sub_category TEXT NOT NULL DEFAULT 'Miscellaneous'")
        c.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS pending_loan NUMERIC(12, 2) NOT NULL DEFAULT 0.0")
        c.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS deleted_at TEXT DEFAULT NULL")
    else:
        c.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                t_date TEXT NOT NULL,
                bank TEXT NOT NULL DEFAULT 'SBI',
                t_type TEXT NOT NULL,
                category TEXT NOT NULL,
                sub_category TEXT NOT NULL DEFAULT 'Miscellaneous',
                member TEXT NOT NULL,
                amount REAL NOT NULL,
                pending_loan REAL NOT NULL DEFAULT 0.0,
                details TEXT,
                deleted_at TEXT DEFAULT NULL
            )
        """)
        c.execute("PRAGMA table_info(transactions)")
        columns = [col[1] for col in c.fetchall()]
        if "bank" not in columns:
            c.execute("ALTER TABLE transactions ADD COLUMN bank TEXT NOT NULL DEFAULT 'SBI'")
        if "sub_category" not in columns:
            c.execute("ALTER TABLE transactions ADD COLUMN sub_category TEXT NOT NULL DEFAULT 'Miscellaneous'")
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

# ==========================================
# 5. CONSTANTS, LOAN CATEGORIES & AUTO-MAPPERS
# ==========================================
BANK_OPTIONS = ["SBI", "HDFC", "Cash / Other"]
EARNING_MEMBERS = ["Amal Das", "Abhijit Das", "Aditya Das", "Other"]
EXPENSE_MEMBERS = ["Amal Das", "Abhijit Das", "Aditya Das", "Shared / Family"]

# Dedicated Loan Categories & Sub-Categories for the Pending Loan Tracker
LOAN_CATEGORY_MAP = {
    "Gold Loan": ["Gold Loan", "Gold Loan 1", "Gold Loan 2", "Manappuram Gold Loan"],
    "Education Loan": ["EDU loan", "EDU loan 1", "EDU loan 2"],
    "Consumer & Durable Loan": ["Consumer loan", "Consumer loan 1", "Consumer loan 2", "Bajaj Consumer Loan"],
    "Bank & Personal Loan": ["HDFC loan", "Personal Loan", "Bandhan Bank Loan", "Other Loan / EMI"],
    "Credit Card & Other Loan": ["HDFC CC Loan", "AXIS CC Loan", "Vehicle / Bike Loan", "Custom Loan"]
}

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
    "Investment Returns": ["Interest / Dividends", "Mutual Fund / Maturity", "Other Income"],
    "Other Income": ["Personal Loan Disbursed", "Other Income"]
}

SELF_TRANSFER_CATEGORY_MAP = {
    "Self Transfer (Internal)": [
        "Self Transfer (SBI <-> HDFC)",
        "FD Sweep-In (Internal)",
        "Self / Wallet Reversal",
        "Reversal / Mandate Test"
    ]
}

def infer_loan_category(sub_cat_name, existing_cat=""):
    """Maps any loan sub-category (e.g., 'Gold Loan', 'EDU loan') into a specific Loan Category for Loan Charts."""
    if existing_cat in LOAN_CATEGORY_MAP:
        return existing_cat
    s = str(sub_cat_name or "").lower()
    if "gold" in s or "manappur" in s:
        return "Gold Loan"
    if "edu" in s or "student" in s or "college" in s:
        return "Education Loan"
    if "consum" in s or "bajaj" in s or "appliance" in s:
        return "Consumer & Durable Loan"
    if "cc" in s or "card" in s or "bike" in s or "car" in s:
        return "Credit Card & Other Loan"
    return "Bank & Personal Loan"

def get_category_map_for_type(t_type):
    if t_type == "Income":
        return INCOME_CATEGORY_MAP
    if t_type == "Self Transfer":
        return SELF_TRANSFER_CATEGORY_MAP
    return EXPENSE_CATEGORY_MAP

def infer_parent_category(sub_cat_name, t_type="Expense"):
    if t_type == "Self Transfer":
        return "Self Transfer (Internal)"

    s_clean = str(sub_cat_name or "").strip().lower()
    target_map = get_category_map_for_type(t_type)

    for parent_cat, subs in target_map.items():
        for sub in subs:
            if sub.lower() == s_clean:
                return parent_cat

    if t_type == "Income":
        if "sal" in s_clean or "bonus" in s_clean or "pension" in s_clean or "contribution" in s_clean:
            return "Salary & Regular Income"
        if "bus" in s_clean or "free" in s_clean or "rent" in s_clean:
            return "Business & Freelance"
        if "disburs" in s_clean:
            return "Other Income"
        return "Investment Returns"

    if "loan" in s_clean or "emi" in s_clean:
        return "Loans & EMIs"
    if "cc" in s_clean or "card" in s_clean:
        return "Credit Card Bills"
    if "bill" in s_clean or "light" in s_clean or "gas" in s_clean or "recharge" in s_clean:
        return "Utilities & Bills"
    if "lic" in s_clean or "mutual" in s_clean or "sip" in s_clean or "insurance" in s_clean or "fixed deposit" in s_clean:
        return "Insurance & Investments"
    if "grocer" in s_clean or "food" in s_clean or "veg" in s_clean or "dining" in s_clean or "hungerbox" in s_clean:
        return "Groceries & Food"
    if "rent" in s_clean or "home" in s_clean or "house" in s_clean:
        return "Housing & Rent"
    if "med" in s_clean or "doctor" in s_clean:
        return "Medical & Healthcare"
    if "fuel" in s_clean or "petrol" in s_clean or "oil" in s_clean or "transport" in s_clean or "maintenance" in s_clean:
        return "Transport & Fuel"

    return "Shopping & Miscellaneous"

@st.cache_data(ttl=300, show_spinner=False)
def load_data():
    """Loads active transactions and shifts end-of-month salaries (day >= 24) into next month's budget."""
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT * FROM transactions WHERE deleted_at IS NULL OR deleted_at = '' ORDER BY t_date DESC, id DESC",
        conn
    )
    if not USE_POSTGRES:
        conn.close()

    if not df.empty:
        df["t_date"] = pd.to_datetime(df["t_date"])
        df["bank"] = df["bank"].fillna("SBI")
        df["amount"] = df["amount"].astype(float)
        df["pending_loan"] = df["pending_loan"].fillna(0.0).astype(float)
        df["sub_category"] = df["sub_category"].fillna("Miscellaneous")
        df["Loan_Category"] = df.apply(lambda r: infer_loan_category(r["sub_category"], r["category"]), axis=1)

        df["Effective_Date"] = df.apply(get_effective_accounting_date, axis=1)
        df["Month_Key"] = df["Effective_Date"].dt.strftime("%Y-%m")
        df["Month_Label"] = df["Effective_Date"].dt.strftime("%B %Y (%Y-%m)")
        df["Is_Shifted_Salary"] = df["Effective_Date"].dt.month != df["t_date"].dt.month

        df["Record_Label"] = df.apply(
            lambda r: (
                f"#{int(r['id'])} | {r['t_date'].strftime('%Y-%m-%d')}"
                + (f" ➡️ [{r['Effective_Date'].strftime('%b %Y')} Salary]" if r["Is_Shifted_Salary"] else "")
                + f" | [{r['bank']}] {r['sub_category']} | {format_inr(r['amount'], 0)}"
                + (f" (Loan: {format_inr(r['pending_loan'], 0)})" if r["pending_loan"] > 0 else "")
                + f" • {r['member']}"
            ),
            axis=1
        )
    return df

@st.cache_data(ttl=300, show_spinner=False)
def load_recycle_bin():
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
        bin_df["bank"] = bin_df["bank"].fillna("SBI")
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
                f"#{int(r['id'])} | {r['t_date'].strftime('%Y-%m-%d')} | [{r['bank']}] "
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

def add_transaction(t_date, bank, t_type, category, sub_category, member, amount, pending_loan, details):
    conn = get_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("""
            INSERT INTO transactions (t_date, bank, t_type, category, sub_category, member, amount, pending_loan, details, deleted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
        """, (t_date, bank, t_type, category, sub_category, member, amount, pending_loan, details))
    else:
        c.execute("""
            INSERT INTO transactions (t_date, bank, t_type, category, sub_category, member, amount, pending_loan, details, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """, (str(t_date), bank, t_type, category, sub_category, member, amount, pending_loan, details))
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
            INSERT INTO transactions (t_date, bank, t_type, category, sub_category, member, amount, pending_loan, details, deleted_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
        """, records_list)
    else:
        c.executemany("""
            INSERT INTO transactions (t_date, bank, t_type, category, sub_category, member, amount, pending_loan, details, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """, [(str(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]) for r in records_list])
    conn.commit()
    c.close()
    if not USE_POSTGRES:
        conn.close()
    clear_all_caches()

def update_transaction(t_id, t_date, bank, t_type, category, sub_category, member, amount, pending_loan, details):
    conn = get_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("""
            UPDATE transactions
            SET t_date = %s, bank = %s, t_type = %s, category = %s, sub_category = %s,
                member = %s, amount = %s, pending_loan = %s, details = %s
            WHERE id = %s
        """, (t_date, bank, t_type, category, sub_category, member, float(amount), float(pending_loan), details, int(t_id)))
    else:
        c.execute("""
            UPDATE transactions
            SET t_date = ?, bank = ?, t_type = ?, category = ?, sub_category = ?,
                member = ?, amount = ?, pending_loan = ?, details = ?
            WHERE id = ?
        """, (str(t_date), bank, t_type, category, sub_category, member, float(amount), float(pending_loan), details, int(t_id)))
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

df = load_data()
bin_df = load_recycle_bin()

# ==========================================
# 6. POPUP MODAL DIALOGS (@st.dialog)
# ==========================================
@st.dialog("➕ Add New Expense / Income / Transfer", width="large")
def open_add_modal():
    top_col1, top_col2 = st.columns(2)
    with top_col1:
        t_type = st.radio("Transaction Type", ["Expense", "Income", "Self Transfer"], horizontal=True)
    with top_col2:
        bank = st.selectbox("Bank Account", BANK_OPTIONS)

    cat_col1, cat_col2 = st.columns(2)
    with cat_col1:
        cat_map = get_category_map_for_type(t_type)
        category = st.selectbox("Category", list(cat_map.keys()))
    with cat_col2:
        sub_options = cat_map[category] + ["➕ Custom Sub-category..."]
        selected_sub = st.selectbox("Sub-category", sub_options)

    custom_sub = ""
    if selected_sub == "➕ Custom Sub-category...":
        custom_sub = st.text_input("Enter Custom Sub-category", placeholder="e.g., Car Loan")

    f_col1, f_col2 = st.columns(2)
    with f_col1:
        t_date = st.date_input("Date", date.today())
        if t_type == "Income" and selected_sub == "Monthly Salary" and t_date.day >= SALARY_CUTOFF_DAY:
            next_m = (t_date.replace(day=28) + timedelta(days=10)).strftime("%B %Y")
            st.caption(f"📅 **End-of-Month Salary:** Counts toward **{next_m}**!")
    with f_col2:
        if t_type == "Income":
            member = st.selectbox("Earning Member", EARNING_MEMBERS, index=2)
        else:
            member = st.selectbox("Paid By / Member", EXPENSE_MEMBERS, index=2)

    a_col1, a_col2 = st.columns(2)
    with a_col1:
        amount = st.number_input(
            "Amount (₹)",
            min_value=0.0, value=None,
            placeholder="Tap to type (e.g., 1500)", step=100.0,
            key="add_amount_input"
        )
        if amount and amount > 0:
            st.caption(f"🇮🇳 **{format_inr(amount)}** — *{number_to_indian_words(amount)}*")

    with a_col2:
        if t_type == "Expense":
            pending_loan = st.number_input(
                "Pending Loan Balance (₹) [Optional]",
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
            final_sub = "Miscellaneous"

        if clean_amount <= 0 and clean_loan <= 0:
            st.error("⚠️ Please enter an Amount or Pending Loan greater than ₹0.")
        else:
            add_transaction(
                t_date, bank, t_type, category, final_sub, member,
                clean_amount, clean_loan, details.strip()
            )
            st.toast(f"✅ Saved [{bank}] {final_sub}: {format_inr(clean_amount, 2)}", icon="💰")
            st.rerun()


@st.dialog("🏦 Add / Update Month-Wise Pending Loans", width="large")
def open_pending_loan_modal():
    st.caption(
        "Log a single Pending Loan with its Loan Category, or bulk-update all your active loans for the month at once!"
    )
    mode_tab1, mode_tab2 = st.tabs(["➕ Add Single Pending Loan", "📋 Bulk Month-Wise Loan Sheet"])

    # Mode 1: Add a Single Pending Loan with Loan Category
    with mode_tab1:
        l_c1, l_c2 = st.columns(2)
        with l_c1:
            loan_date = st.date_input("Loan Month / Date", date.today(), key="single_loan_dt")
            loan_cat = st.selectbox("Loan Category", list(LOAN_CATEGORY_MAP.keys()), key="single_loan_cat")
        with l_c2:
            loan_bank = st.selectbox("Bank / Lender", BANK_OPTIONS, key="single_loan_bank")
            sub_opts = LOAN_CATEGORY_MAP[loan_cat] + ["➕ Custom Loan Name..."]
            loan_sub_sel = st.selectbox("Loan Sub-Category / Name", sub_opts, key="single_loan_sub")

        cust_loan_name = ""
        if loan_sub_sel == "➕ Custom Loan Name...":
            cust_loan_name = st.text_input("Enter Custom Loan Name", placeholder="e.g., Car Loan SBI")

        l_c3, l_c4 = st.columns(2)
        with l_c3:
            loan_holder = st.selectbox("Loan Holder (Member)", EXPENSE_MEMBERS, index=2, key="single_loan_mem")
            emi_paid_val = st.number_input(
                "Monthly EMI Paid (₹) [Optional, can be 0]",
                min_value=0.0, value=None,
                placeholder="e.g., 7800 (or leave blank)", step=500.0,
                key="single_loan_emi"
            )
        with l_c4:
            pending_bal_val = st.number_input(
                "Pending Loan Balance Till Date (₹) *",
                min_value=0.0, value=None,
                placeholder="e.g., 318885", step=1000.0,
                key="single_loan_bal"
            )
            loan_notes = st.text_input("Loan Details / Account Note", placeholder="e.g., Education Loan 1")

        inject_live_indian_words_js()

        if st.button("💾 Save Pending Loan Entry", type="primary", use_container_width=True):
            final_loan_sub = cust_loan_name.strip() if loan_sub_sel == "➕ Custom Loan Name..." else loan_sub_sel
            clean_emi = float(emi_paid_val) if emi_paid_val is not None else 0.0
            clean_bal = float(pending_bal_val) if pending_bal_val is not None else 0.0

            if not final_loan_sub:
                st.error("⚠️ Please provide a loan name.")
            elif clean_bal <= 0 and clean_emi <= 0:
                st.error("⚠️ Please enter a Pending Loan Balance greater than ₹0.")
            else:
                add_transaction(
                    loan_date, loan_bank, "Expense", loan_cat,
                    final_loan_sub, loan_holder, clean_emi, clean_bal,
                    loan_notes.strip() or f"{loan_cat} Balance"
                )
                st.toast(f"✅ Saved {final_loan_sub} Pending Loan: {format_inr(clean_bal)}", icon="🏦")
                st.rerun()

    # Mode 2: Bulk Month-Wise Loan Sheet (Pre-populated with your standard loans or previous month's loans!)
    with mode_tab2:
        b_c1, b_c2 = st.columns(2)
        with b_c1:
            bulk_loan_date = st.date_input("Target Month Date", date.today().replace(day=1), key="bulk_loan_dt")
        with b_c2:
            loan_hist_df = df[df["pending_loan"] > 0] if not df.empty else pd.DataFrame()
            if not loan_hist_df.empty:
                prev_loan_months = ["📋 Standard Das Family Loan Template"] + list(
                    loan_hist_df.sort_values("Month_Key", ascending=False)["Month_Label"].unique()
                )
            else:
                prev_loan_months = ["📋 Standard Das Family Loan Template"]
            template_source = st.selectbox("Load Loan List From:", prev_loan_months, key="bulk_loan_src")

        if template_source == "📋 Standard Das Family Loan Template":
            seed_loans = pd.DataFrame([
                {"Save": True, "Bank": "SBI", "Loan Category": "Gold Loan", "Loan Sub-category": "Gold Loan 1", "Member": "Amal Das", "EMI Paid (₹)": 0.0, "Pending Loan (₹)": 79489.0, "Details": "Gold Loan 1"},
                {"Save": True, "Bank": "SBI", "Loan Category": "Gold Loan", "Loan Sub-category": "Gold Loan 2", "Member": "Amal Das", "EMI Paid (₹)": 0.0, "Pending Loan (₹)": 23519.0, "Details": "Gold Loan 2"},
                {"Save": True, "Bank": "SBI", "Loan Category": "Consumer & Durable Loan", "Loan Sub-category": "Consumer loan 1", "Member": "Aditya Das", "EMI Paid (₹)": 1736.0, "Pending Loan (₹)": 75694.0, "Details": "Consumer Loan 1"},
                {"Save": True, "Bank": "SBI", "Loan Category": "Consumer & Durable Loan", "Loan Sub-category": "Consumer loan 2", "Member": "Amal Das", "EMI Paid (₹)": 0.0, "Pending Loan (₹)": 13888.0, "Details": "Consumer Loan 2"},
                {"Save": True, "Bank": "SBI", "Loan Category": "Education Loan", "Loan Sub-category": "EDU loan 1", "Member": "Aditya Das", "EMI Paid (₹)": 0.0, "Pending Loan (₹)": 318885.0, "Details": "Education Loan 1"},
                {"Save": True, "Bank": "SBI", "Loan Category": "Education Loan", "Loan Sub-category": "EDU loan 2", "Member": "Aditya Das", "EMI Paid (₹)": 0.0, "Pending Loan (₹)": 401647.0, "Details": "Education Loan 2"},
                {"Save": True, "Bank": "HDFC", "Loan Category": "Bank & Personal Loan", "Loan Sub-category": "HDFC loan", "Member": "Aditya Das", "EMI Paid (₹)": 9406.0, "Pending Loan (₹)": 313834.0, "Details": "HDFC Personal Loan"},
            ])
        else:
            prev_df = loan_hist_df[loan_hist_df["Month_Label"] == template_source].sort_values("id")
            seed_loans = pd.DataFrame({
                "Save": True,
                "Bank": prev_df["bank"],
                "Loan Category": prev_df["Loan_Category"],
                "Loan Sub-category": prev_df["sub_category"],
                "Member": prev_df["member"],
                "EMI Paid (₹)": prev_df["amount"],
                "Pending Loan (₹)": prev_df["pending_loan"],
                "Details": prev_df["details"].fillna("")
            })

        edited_loans = st.data_editor(
            seed_loans,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "Save": st.column_config.CheckboxColumn("Save?", default=True),
                "Bank": st.column_config.SelectboxColumn("Bank", options=BANK_OPTIONS, default="SBI"),
                "Loan Category": st.column_config.SelectboxColumn(
                    "Loan Category", options=list(LOAN_CATEGORY_MAP.keys()), default="Bank & Personal Loan"
                ),
                "Loan Sub-category": st.column_config.TextColumn("Loan Sub-category"),
                "Member": st.column_config.SelectboxColumn("Member", options=EXPENSE_MEMBERS, default="Aditya Das"),
                "EMI Paid (₹)": st.column_config.NumberColumn("EMI Paid (₹)", min_value=0.0, format="%.2f", default=0.0),
                "Pending Loan (₹)": st.column_config.NumberColumn("Pending Loan (₹)", min_value=0.0, format="%.2f", default=0.0),
                "Details": st.column_config.TextColumn("Details")
            },
            key="bulk_loan_editor"
        )

        checked_loans = edited_loans[edited_loans["Save"] == True]
        tot_pending_preview = checked_loans["Pending Loan (₹)"].sum()
        tot_emi_preview = checked_loans["EMI Paid (₹)"].sum()

        st.caption(
            f"✅ **{len(checked_loans)} Loans Selected** | "
            f"Total Pending Balance: **{format_inr(tot_pending_preview, 2)}** "
            f"*({number_to_indian_words(tot_pending_preview)})* | "
            f"Total EMI Paid: **{format_inr(tot_emi_preview, 2)}**"
        )

        if st.button(
            f"🚀 Save {len(checked_loans)} Pending Loans for {bulk_loan_date.strftime('%B %Y')}",
            type="primary", use_container_width=True
        ):
            if checked_loans.empty:
                st.warning("Please keep at least one loan row checked.")
            else:
                loan_records = [
                    (
                        bulk_loan_date,
                        str(r.get("Bank") or "SBI"),
                        "Expense",
                        str(r.get("Loan Category") or "Loans & EMIs"),
                        str(r.get("Loan Sub-category") or "Other Loan / EMI").strip(),
                        str(r.get("Member") or "Aditya Das"),
                        float(r.get("EMI Paid (₹)") or 0.0),
                        float(r.get("Pending Loan (₹)") or 0.0),
                        str(r.get("Details") or "").strip()
                    )
                    for _, r in checked_loans.iterrows()
                    if float(r.get("Pending Loan (₹)") or 0.0) > 0 or float(r.get("EMI Paid (₹)") or 0.0) > 0
                ]
                bulk_add_transactions(loan_records)
                st.toast(f"🏦 Saved {len(loan_records)} Pending Loans for {bulk_loan_date.strftime('%B %Y')}!", icon="✅")
                st.rerun()


@st.dialog("📥 Import Merged CSV or Multi-Sheet Excel", width="large")
def open_excel_import_modal():
    st.caption(
        "Directly supports **`Merged_SBI_HDFC_Expenses_2026.csv`** and **`.xlsx`**! "
        "Any salary credited on or after the 24th (e.g., 30th Oct Friday) is automatically counted as **Next Month's Salary**."
    )
    uploaded_file = st.file_uploader("Select your CSV or Excel (.xlsx / .xls) file", type=["csv", "xlsx", "xls"])

    if uploaded_file is not None:
        sheets_dict = {}
        try:
            if uploaded_file.name.lower().endswith(".csv"):
                sheets_dict["CSV_Data"] = pd.read_csv(uploaded_file)
                selected_sheets = ["CSV_Data"]
            else:
                xl = pd.ExcelFile(uploaded_file)
                selected_sheets = st.multiselect(
                    "📑 Select Monthly Sheet Tabs to Import",
                    options=xl.sheet_names,
                    default=xl.sheet_names
                )
                for sh in selected_sheets:
                    sheets_dict[sh] = pd.read_excel(uploaded_file, sheet_name=sh)
        except Exception as e:
            st.error(f"❌ Could not read file: {e}")
            return

        if not selected_sheets:
            st.warning("Please select at least one sheet tab above.")
            return

        first_df = sheets_dict[selected_sheets[0]]
        if first_df.empty:
            st.warning("The selected file/sheet is empty.")
            return

        cols = list(first_df.columns)
        none_opt = ["(None / Auto-Detect)"]

        def guess_col(keywords, include_none=False):
            options = (none_opt + cols) if include_none else cols
            for c in cols:
                c_low = str(c).lower()
                if any(k == c_low or k in c_low for k in keywords):
                    return options.index(c)
            return 0

        with st.expander("⚙️ Verify Column Mapping (Auto-Detected)", expanded=False):
            m_c1, m_c2, m_c3, m_c4 = st.columns(4)
            with m_c1:
                sub_col = st.selectbox(
                    "Sub-category Column",
                    none_opt + cols,
                    index=guess_col(["sub-catego", "sub_catego", "sub", "item"], include_none=True)
                )
            with m_c2:
                type_col = st.selectbox(
                    "Type Column",
                    none_opt + cols,
                    index=guess_col(["type", "income/expense", "nature"], include_none=True)
                )
            with m_c3:
                bank_col = st.selectbox(
                    "Bank Column",
                    none_opt + cols,
                    index=guess_col(["bank", "account"], include_none=True)
                )
            with m_c4:
                cat_col = st.selectbox(
                    "Category Column",
                    none_opt + cols,
                    index=guess_col(["category"], include_none=True)
                )

            m_c5, m_c6, m_c7, m_c8 = st.columns(4)
            with m_c5:
                amt_col = st.selectbox(
                    "Amount Column",
                    none_opt + cols,
                    index=guess_col(["amount", "paid", "emi", "value"], include_none=True)
                )
            with m_c6:
                loan_col = st.selectbox(
                    "Pending Loan Column",
                    none_opt + cols,
                    index=guess_col(["pending", "loan", "balance"], include_none=True)
                )
            with m_c7:
                member_col = st.selectbox(
                    "Member Column",
                    none_opt + cols,
                    index=guess_col(["member", "name", "paid by"], include_none=True)
                )
            with m_c8:
                date_col = st.selectbox(
                    "Date Column",
                    none_opt + cols,
                    index=guess_col(["date", "day"], include_none=True)
                )

            details_col = st.selectbox(
                "Details / Narration Column",
                none_opt + cols,
                index=guess_col(["detail", "narration", "note", "remark"], include_none=True)
            )

        parsed_rows = []
        income_keywords = ("salary", "income", "bonus", "freelance", "dividend", "interest", "pension")

        for sh_name in selected_sheets:
            sh_df = sheets_dict[sh_name]
            guessed_sh_date = date.today().replace(day=1)
            try:
                guessed_sh_date = pd.to_datetime(sh_name, errors="raise").date().replace(day=1)
            except Exception:
                pass

            for _, r in sh_df.iterrows():
                raw_bank_val = str(r[bank_col]).strip().lower() if bank_col in r and pd.notna(r[bank_col]) else ""
                raw_type_val = str(r[type_col]).strip().lower() if type_col in r and pd.notna(r[type_col]) else ""
                if raw_bank_val == "total" or raw_type_val.startswith("inc:") or raw_type_val == "total":
                    continue

                amt_val = clean_currency_value(r[amt_col]) if amt_col in r and amt_col != "(None / Auto-Detect)" else 0.0
                loan_val = clean_currency_value(r[loan_col]) if loan_col in r and loan_col != "(None / Auto-Detect)" else 0.0
                if amt_val <= 0 and loan_val <= 0:
                    continue

                row_type = "Expense"
                if type_col != "(None / Auto-Detect)" and type_col in r and pd.notna(r[type_col]):
                    t_raw = str(r[type_col]).strip().lower()
                    if "self" in t_raw or "internal" in t_raw or "transfer" in t_raw:
                        row_type = "Self Transfer"
                    elif "inc" in t_raw or "sal" in t_raw or "earn" in t_raw:
                        row_type = "Income"

                raw_sub = r[sub_col] if sub_col != "(None / Auto-Detect)" and sub_col in r else ""
                sub_str = "" if pd.isna(raw_sub) else str(raw_sub).strip()
                if sub_str.lower() in ("total", "grand total", "sub-category", "sub category"):
                    continue

                if not sub_str or sub_str.lower() in ("nan", "none", ""):
                    sub_str = "Miscellaneous" if row_type == "Expense" else ("Other Income" if row_type == "Income" else "Self Transfer (SBI <-> HDFC)")

                if type_col == "(None / Auto-Detect)":
                    if any(k in sub_str.lower() for k in income_keywords) and loan_val <= 0:
                        row_type = "Income"

                if row_type in ("Income", "Self Transfer"):
                    loan_val = 0.0

                row_bank = "SBI"
                if bank_col != "(None / Auto-Detect)" and bank_col in r and pd.notna(r[bank_col]):
                    b_str = str(r[bank_col]).strip().upper()
                    if "HDFC" in b_str:
                        row_bank = "HDFC"
                    elif "SBI" in b_str:
                        row_bank = "SBI"
                    elif b_str and b_str not in ("NAN", "NONE"):
                        row_bank = b_str

                row_date = guessed_sh_date
                if date_col != "(None / Auto-Detect)" and date_col in r and pd.notna(r[date_col]):
                    try:
                        row_date = pd.to_datetime(r[date_col]).date()
                    except Exception:
                        row_date = guessed_sh_date

                row_member = "Aditya Das"
                if member_col != "(None / Auto-Detect)" and member_col in r and pd.notna(r[member_col]):
                    m_str = str(r[member_col]).strip()
                    if m_str and m_str.lower() not in ("nan", "none"):
                        row_member = m_str

                row_details = f"Imported ({sh_name})"
                if details_col != "(None / Auto-Detect)" and details_col in r and pd.notna(r[details_col]):
                    d_str = str(r[details_col]).strip()
                    if d_str and d_str.lower() not in ("nan", "none"):
                        row_details = d_str

                parent_cat = ""
                if cat_col != "(None / Auto-Detect)" and cat_col in r and pd.notna(r[cat_col]):
                    c_str = str(r[cat_col]).strip()
                    if c_str and c_str.lower() not in ("nan", "none"):
                        parent_cat = c_str
                if not parent_cat:
                    parent_cat = infer_parent_category(sub_str, row_type)

                parsed_rows.append({
                    "Import": True,
                    "Date": row_date,
                    "Bank": row_bank,
                    "Type": row_type,
                    "Category": parent_cat,
                    "Sub-category": sub_str,
                    "Member": row_member,
                    "Amount (₹)": amt_val,
                    "Pending Loan (₹)": loan_val,
                    "Details": row_details
                })

        if not parsed_rows:
            st.warning("⚠️ No valid transaction rows were found.")
            return

        st.markdown("##### 📋 Review & Edit Before Saving")
        preview_import_df = pd.DataFrame(parsed_rows)
        edited_import_df = st.data_editor(
            preview_import_df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Import": st.column_config.CheckboxColumn("Import?", default=True),
                "Date": st.column_config.DateColumn("Date"),
                "Bank": st.column_config.SelectboxColumn("Bank", options=BANK_OPTIONS),
                "Type": st.column_config.SelectboxColumn("Type", options=["Expense", "Income", "Self Transfer"]),
                "Category": st.column_config.TextColumn("Category"),
                "Sub-category": st.column_config.TextColumn("Sub-category"),
                "Member": st.column_config.SelectboxColumn("Member", options=EXPENSE_MEMBERS + ["Other"]),
                "Amount (₹)": st.column_config.NumberColumn("Amount (₹)", min_value=0.0, format="%.2f"),
                "Pending Loan (₹)": st.column_config.NumberColumn("Pending Loan (₹)", min_value=0.0, format="%.2f"),
                "Details": st.column_config.TextColumn("Details")
            }
        )

        to_import = edited_import_df[edited_import_df["Import"] == True]
        imp_inc_total = to_import[to_import["Type"] == "Income"]["Amount (₹)"].sum()
        imp_exp_total = to_import[to_import["Type"] == "Expense"]["Amount (₹)"].sum()
        imp_self_total = to_import[to_import["Type"] == "Self Transfer"]["Amount (₹)"].sum()

        st.caption(
            f"✅ **{len(to_import)} rows ready** | "
            f"Income: **{format_inr(imp_inc_total, 0)}** | "
            f"Expense: **{format_inr(imp_exp_total, 0)}** | "
            f"Self Transfer (Excluded): **{format_inr(imp_self_total, 0)}**"
        )

        if st.button(f"🚀 Import All {len(to_import)} Rows into Database", type="primary", use_container_width=True):
            if to_import.empty:
                st.warning("Please keep at least one row checked.")
            else:
                records_to_save = [
                    (
                        row["Date"],
                        str(row["Bank"]).strip(),
                        str(row["Type"]).strip(),
                        str(row["Category"]).strip(),
                        str(row["Sub-category"]).strip() or "Miscellaneous",
                        str(row["Member"]).strip(),
                        float(row["Amount (₹)"] or 0.0),
                        float(row["Pending Loan (₹)"] or 0.0),
                        str(row["Details"] or "").strip()
                    )
                    for _, row in to_import.iterrows()
                ]
                bulk_add_transactions(records_to_save)
                st.toast(f"🎉 Imported {len(records_to_save)} rows into database!", icon="📥")
                st.rerun()


@st.dialog("⚠️ Confirm Undo Last Entry", width="small")
def open_undo_confirm_modal(latest_row):
    st.warning("Are you sure you want to undo and move this latest entry to the Recycle Bin?")
    amt_val = float(latest_row["amount"])
    loan_val = float(latest_row.get("pending_loan", 0.0) or 0.0)

    st.markdown(f"""
    * **Entry ID:** `#{int(latest_row['id'])}` (`{latest_row['bank']}`)
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
    disp_bin = current_bin[["id", "t_date", "bank", "sub_category", "member", "amount", "pending_loan", "Auto_Clears_In"]].copy()
    disp_bin["t_date"] = disp_bin["t_date"].dt.strftime("%Y-%m-%d")
    disp_bin["amount"] = disp_bin["amount"].apply(format_inr)
    disp_bin["pending_loan"] = disp_bin["pending_loan"].apply(format_inr)
    disp_bin.columns = ["ID", "Date", "Bank", "Sub-category", "Member", "Amount", "Pending Loan", "Expires In"]
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
        ["Only Expenses & Loans", "Only Pending Loans", "Both Expenses & Income"],
        horizontal=True
    )

    src_df = df[df["Month_Label"] == source_month].copy()
    if clone_filter == "Only Expenses & Loans":
        src_df = src_df[src_df["t_type"] == "Expense"]
    elif clone_filter == "Only Pending Loans":
        src_df = src_df[src_df["pending_loan"] > 0]
    else:
        src_df = src_df[src_df["t_type"].isin(["Expense", "Income"])]

    if src_df.empty:
        st.warning("No matching entries found in the selected source month.")
        return

    src_df = src_df.sort_values("id", ascending=True)
    preview_df = pd.DataFrame({
        "Copy": True,
        "Bank": src_df["bank"],
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
            "Bank": st.column_config.SelectboxColumn("Bank", options=BANK_OPTIONS),
            "Type": st.column_config.TextColumn("Type", disabled=True),
            "Category": st.column_config.TextColumn("Category"),
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
                    target_date, str(row["Bank"]), str(row["Type"]), str(row["Category"]),
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
        type_opts = ["Expense", "Income", "Self Transfer"]
        default_type_idx = type_opts.index(rec_row["t_type"]) if rec_row["t_type"] in type_opts else 0
        edit_type = st.radio(
            "Transaction Type", type_opts, index=default_type_idx,
            horizontal=True, key=f"mod_type_{rec_id}"
        )
    with mc2:
        bank_list = list(BANK_OPTIONS)
        if rec_row["bank"] not in bank_list:
            bank_list.insert(0, rec_row["bank"])
        edit_bank = st.selectbox("Bank", bank_list, index=bank_list.index(rec_row["bank"]), key=f"mod_bank_{rec_id}")

    cat_map = get_category_map_for_type(edit_type)
    cat_list = list(cat_map.keys()) + [c for c in LOAN_CATEGORY_MAP.keys() if c not in cat_map]
    if rec_row["category"] not in cat_list:
        cat_list.insert(0, rec_row["category"])
    default_cat_idx = cat_list.index(rec_row["category"])

    mc3, mc4 = st.columns(2)
    with mc3:
        edit_category = st.selectbox(
            "Category", cat_list, index=default_cat_idx, key=f"mod_cat_{rec_id}"
        )

    base_subs = cat_map.get(edit_category, LOAN_CATEGORY_MAP.get(edit_category, ["Miscellaneous"]))
    sub_list = list(base_subs)
    current_sub = str(rec_row["sub_category"])
    if current_sub not in sub_list:
        sub_list.insert(0, current_sub)
    sub_list.append("➕ Custom Sub-category...")
    default_sub_idx = sub_list.index(current_sub)

    with mc4:
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
        mem_list = list(EXPENSE_MEMBERS if edit_type != "Income" else EARNING_MEMBERS)
        if rec_row["member"] not in mem_list:
            mem_list.insert(0, rec_row["member"])
        edit_member = st.selectbox(
            "Member", mem_list, index=mem_list.index(rec_row["member"]), key=f"mod_mem_{rec_id}"
        )

    fc3, fc4 = st.columns(2)
    with fc3:
        edit_amount = st.number_input(
            "Amount (₹)", min_value=0.0,
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
            st.caption("Pending Loan is ₹0 for Income / Self Transfer entries.")

    edit_details = st.text_input("Details / Notes", value=str(rec_row["details"] or ""), key=f"mod_det_{rec_id}")

    inject_live_indian_words_js()

    if st.button("💾 Save Changes", type="primary", use_container_width=True):
        final_sub_val = custom_edit_sub.strip() if edit_sub_choice == "➕ Custom Sub-category..." else edit_sub_choice
        if not final_sub_val:
            final_sub_val = "Miscellaneous"
        if (edit_amount or 0.0) <= 0 and (edit_pending_loan or 0.0) <= 0:
            st.error("⚠️ Please enter an Amount or Pending Loan greater than ₹0.")
        else:
            update_transaction(
                rec_id, edit_date, edit_bank, edit_type, edit_category,
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
# 7. MOBILE-OPTIMIZED TOP HEADER & ACTION BAR
# ==========================================
st.markdown('<div class="app-top-title">💰 Das Family Expense & Loan Tracker</div>', unsafe_allow_html=True)

bin_count = len(bin_df)
bin_btn_label = f"🗑️ Bin ({bin_count})" if bin_count > 0 else "🗑️ Bin"

if not df.empty:
    # 2x3 / 2-column responsive button grid on mobile, single row on desktop
    btn_c1, btn_c2, btn_c3, btn_c4, btn_c5, btn_c6 = st.columns(6)
    with btn_c1:
        if st.button("➕ Add Entry", type="primary", use_container_width=True):
            open_add_modal()
    with btn_c2:
        if st.button("🏦 Pending Loan", use_container_width=True):
            open_pending_loan_modal()
    with btn_c3:
        if st.button("📥 Import Excel", use_container_width=True):
            open_excel_import_modal()
    with btn_c4:
        if st.button("🔄 Copy Month", use_container_width=True):
            open_copy_modal()
    with btn_c5:
        if st.button("✏️ Modify", use_container_width=True):
            open_modify_modal(df)
    with btn_c6:
        latest_row = df.iloc[0]
        if st.button(f"↩️ Undo (#{int(latest_row['id'])})", use_container_width=True):
            open_undo_confirm_modal(latest_row)
else:
    empty_c1, empty_c2, empty_c3, empty_c4 = st.columns(4)
    with empty_c1:
        if st.button("➕ Add Entry", type="primary", use_container_width=True):
            open_add_modal()
    with empty_c2:
        if st.button("🏦 Pending Loan", use_container_width=True):
            open_pending_loan_modal()
    with empty_c3:
        if st.button("📥 Import CSV/Excel", use_container_width=True):
            open_excel_import_modal()
    with empty_c4:
        if st.button(bin_btn_label, use_container_width=True):
            open_recycle_bin_modal()

# ==========================================
# 8. MAIN DASHBOARD (INDIAN NUMBER FORMAT)
# ==========================================
if df.empty:
    st.info("👋 Tap **➕ Add Entry**, **🏦 Pending Loan**, or **📥 Import CSV/Excel** above to get started!")
else:
    tab_monthly, tab_loans, tab_trends, tab_records = st.tabs([
        "📅 Monthly", "🏦 Loans", "📈 Trends", "📋 History"
    ])

    # ------------------------------------------
    # TAB 1: MONTH-WISE DASHBOARD
    # ------------------------------------------
    with tab_monthly:
        month_options = df.sort_values("Month_Key", ascending=False)["Month_Label"].unique()

        col_select, col_chart_style = st.columns(2)
        with col_select:
            selected_month = st.selectbox("🗓️ Select Budget Month", month_options)
        with col_chart_style:
            chart_style = st.radio(
                "📊 Chart Style",
                ["Donut", "Solid Pie", "Bar"],
                horizontal=True
            )

        with st.expander("🏦 Filter by Bank & Family Member", expanded=False):
            f_b_col, f_m_col = st.columns(2)
            with f_b_col:
                selected_banks = st.multiselect(
                    "Select Bank(s)",
                    options=df["bank"].unique(),
                    default=list(df["bank"].unique())
                )
            with f_m_col:
                selected_members = st.multiselect(
                    "Select Family Members",
                    options=df["member"].unique(),
                    default=list(df["member"].unique())
                )

        m_df = df[
            (df["Month_Label"] == selected_month) &
            (df["bank"].isin(selected_banks)) &
            (df["member"].isin(selected_members))
        ]

        m_income = m_df[m_df["t_type"] == "Income"]["amount"].sum()
        m_expense = m_df[m_df["t_type"] == "Expense"]["amount"].sum()
        m_balance = m_income - m_expense
        m_pending_loan = m_df["pending_loan"].sum()
        m_self_transfer = m_df[m_df["t_type"] == "Self Transfer"]["amount"].sum()
        shifted_sal_df = m_df[m_df["Is_Shifted_Salary"] == True]

        # 2x2 Side-by-Side KPI Grid on Mobile & Desktop
        r1_c1, r1_c2 = st.columns(2)
        r1_c1.metric("Monthly Income", format_inr(m_income))
        r1_c2.metric("Monthly Expense", format_inr(m_expense))

        r2_c1, r2_c2 = st.columns(2)
        r2_c1.metric("Net Savings", format_inr(m_balance), delta=format_inr(m_balance))
        r2_c2.metric("Pending Loan", format_inr(m_pending_loan))

        if not shifted_sal_df.empty:
            sal_dates = ", ".join(shifted_sal_df["t_date"].dt.strftime("%d %b").unique())
            sal_sum = shifted_sal_df["amount"].sum()
            st.caption(
                f"📅 **Salary Auto-Shift:** Includes **{format_inr(sal_sum)}** credited on **{sal_dates}**."
            )

        if m_self_transfer > 0:
            st.caption(f"🔄 **Self-Transfers Excluded from Totals:** {format_inr(m_self_transfer)}")

        m_act1, m_act2, m_act3 = st.columns(3)
        with m_act1:
            if st.button("🏦 Add Pending Loan", use_container_width=True, key="btn_loan_m"):
                open_pending_loan_modal()
        with m_act2:
            if st.button("✏️ Modify Entry", use_container_width=True, key="btn_mod_m"):
                open_modify_modal(m_df)
        with m_act3:
            if st.button("🗑️ Delete Entry", use_container_width=True, key="btn_del_m"):
                open_delete_modal(m_df, scope_label=selected_month)

        st.divider()

        exp_m_df = m_df[m_df["t_type"] == "Expense"]
        inc_m_df = m_df[m_df["t_type"] == "Income"]

        hole_size = 0.45 if chart_style == "Donut" else 0.0

        ch1, ch2 = st.columns(2)
        with ch1:
            st.markdown("**🥧 Category Expense**")
            if not exp_m_df.empty and exp_m_df["amount"].sum() > 0:
                cat_grp = exp_m_df.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=True)
                cat_grp["INR_Label"] = cat_grp["amount"].apply(format_inr)
                if chart_style in ("Donut", "Solid Pie"):
                    fig_cat = px.pie(
                        cat_grp, values="amount", names="category", hole=hole_size,
                        custom_data=["INR_Label"],
                        color_discrete_sequence=px.colors.qualitative.Pastel
                    )
                    fig_cat.update_traces(
                        textposition="inside", textinfo="percent+label",
                        hovertemplate="<b>%{label}</b><br>%{customdata[0]} (%{percent})<extra></extra>"
                    )
                    st.plotly_chart(style_compact_chart(fig_cat), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    fig_cat_bar = px.bar(
                        cat_grp, x="amount", y="category", color="category", orientation="h",
                        text="INR_Label", labels={"category": "", "amount": "₹"}
                    )
                    fig_cat_bar.update_traces(hovertemplate="<b>%{y}</b>: %{text}<extra></extra>")
                    st.plotly_chart(style_compact_chart(fig_cat_bar), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
            else:
                st.info("No expenses for this month.")

        with ch2:
            st.markdown("**🎯 Sub-Category Expense**")
            if not exp_m_df.empty and exp_m_df["amount"].sum() > 0:
                sub_grp = exp_m_df.groupby(["sub_category", "category"], as_index=False)["amount"].sum().sort_values("amount", ascending=True)
                sub_grp["INR_Label"] = sub_grp["amount"].apply(format_inr)
                if chart_style in ("Donut", "Solid Pie"):
                    fig_sub_pie = px.pie(
                        sub_grp, values="amount", names="sub_category", hole=hole_size,
                        custom_data=["INR_Label"],
                        color_discrete_sequence=px.colors.qualitative.Safe
                    )
                    fig_sub_pie.update_traces(
                        textposition="inside", textinfo="percent+label",
                        hovertemplate="<b>%{label}</b><br>%{customdata[0]} (%{percent})<extra></extra>"
                    )
                    st.plotly_chart(style_compact_chart(fig_sub_pie), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    fig_sub_bar = px.bar(
                        sub_grp.tail(10), x="amount", y="sub_category", color="category", orientation="h",
                        text="INR_Label", labels={"sub_category": "", "amount": "₹"}
                    )
                    fig_sub_bar.update_traces(hovertemplate="<b>%{y}</b>: %{text}<extra></extra>")
                    st.plotly_chart(style_compact_chart(fig_sub_bar), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
            else:
                st.info("No expenses for this month.")

        ch3, ch4 = st.columns(2)
        with ch3:
            st.markdown("**👨‍👩‍👦 Member Income**")
            if not inc_m_df.empty and inc_m_df["amount"].sum() > 0:
                mem_inc_summary = inc_m_df.groupby("member", as_index=False)["amount"].sum()
                mem_inc_summary["INR_Label"] = mem_inc_summary["amount"].apply(format_inr)
                if chart_style in ("Donut", "Solid Pie"):
                    fig_inc_pie = px.pie(
                        mem_inc_summary, values="amount", names="member", hole=hole_size,
                        custom_data=["INR_Label"],
                        color_discrete_sequence=px.colors.qualitative.Set2
                    )
                    fig_inc_pie.update_traces(
                        textposition="inside", textinfo="percent+label",
                        hovertemplate="<b>%{label}</b>: %{customdata[0]}<extra></extra>"
                    )
                    st.plotly_chart(style_compact_chart(fig_inc_pie), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    fig_inc_bar = px.bar(
                        mem_inc_summary, x="member", y="amount", color="member",
                        text="INR_Label", labels={"member": "", "amount": "₹"}
                    )
                    fig_inc_bar.update_traces(hovertemplate="<b>%{x}</b>: %{text}<extra></extra>")
                    st.plotly_chart(style_compact_chart(fig_inc_bar), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
            else:
                st.info("No income for this month.")

        with ch4:
            st.markdown("**🏦 Expense by Bank**")
            if not exp_m_df.empty and exp_m_df["amount"].sum() > 0:
                bank_grp = exp_m_df.groupby("bank", as_index=False)["amount"].sum()
                bank_grp["INR_Label"] = bank_grp["amount"].apply(format_inr)
                if chart_style in ("Donut", "Solid Pie"):
                    fig_bank_pie = px.pie(
                        bank_grp, values="amount", names="bank", hole=hole_size,
                        custom_data=["INR_Label"],
                        color_discrete_sequence=px.colors.qualitative.Bold
                    )
                    fig_bank_pie.update_traces(
                        textposition="inside", textinfo="percent+label",
                        hovertemplate="<b>%{label}</b>: %{customdata[0]}<extra></extra>"
                    )
                    st.plotly_chart(style_compact_chart(fig_bank_pie), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    fig_bank_bar = px.bar(
                        bank_grp, x="bank", y="amount", color="bank",
                        text="INR_Label", labels={"bank": "", "amount": "₹"}
                    )
                    fig_bank_bar.update_traces(hovertemplate="<b>%{x}</b>: %{text}<extra></extra>")
                    st.plotly_chart(style_compact_chart(fig_bank_bar), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
            else:
                st.info("No bank expenses.")

        t_col1, t_col2 = st.columns(2)
        with t_col1:
            st.markdown("**📂 Sub-Category Summary**")
            if not exp_m_df.empty:
                sub_table = exp_m_df.groupby(["sub_category", "category"], as_index=False).agg(
                    Paid=("amount", "sum"), Loan=("pending_loan", "sum")
                ).sort_values("Paid", ascending=False)
                sub_table["Paid"] = sub_table["Paid"].apply(format_inr)
                sub_table["Loan"] = sub_table["Loan"].apply(format_inr)
                sub_table.columns = ["Sub-category", "Category", "Paid", "Pending Loan"]
                st.dataframe(sub_table, use_container_width=True, hide_index=True)

        with t_col2:
            st.markdown("**💳 Bank & Member Summary**")
            if not exp_m_df.empty:
                mem_exp_table = exp_m_df.groupby(["bank", "member"], as_index=False).agg(
                    Entries=("id", "count"), Total_Paid=("amount", "sum"), Total_Pending_Loan=("pending_loan", "sum")
                ).sort_values("Total_Paid", ascending=False)
                mem_exp_table["Total_Paid"] = mem_exp_table["Total_Paid"].apply(format_inr)
                mem_exp_table["Total_Pending_Loan"] = mem_exp_table["Total_Pending_Loan"].apply(format_inr)
                mem_exp_table.columns = ["Bank", "Member", "Items", "Paid", "Pending Loan"]
                st.dataframe(mem_exp_table, use_container_width=True, hide_index=True)

    # ------------------------------------------
    # TAB 2: DEDICATED PENDING LOAN TRACKER & CHARTS
    # ------------------------------------------
    with tab_loans:
        l_top1, l_top2 = st.columns(2)
        with l_top1:
            if st.button("🏦 Add / Update Month-Wise Loans", type="primary", use_container_width=True, key="btn_open_loan_tab"):
                open_pending_loan_modal()
        with l_top2:
            loan_chart_style = st.radio(
                "📊 Loan Chart Style",
                ["Donut", "Solid Pie", "Bar"],
                horizontal=True,
                key="loan_chart_style_radio"
            )

        # Include both explicit Pending Loan entries (>0) AND Loan EMI payments
        loan_all_df = df[(df["pending_loan"] > 0) | (df["category"] == "Loans & EMIs") | (df["category"].isin(LOAN_CATEGORY_MAP.keys()))].copy()

        if loan_all_df.empty:
            st.info("👋 Tap **🏦 Add / Update Month-Wise Loans** above to load your Gold Loan, EDU Loan, Consumer Loan, and HDFC Loan balances!")
        else:
            loan_months = loan_all_df.sort_values("Month_Key", ascending=False)["Month_Label"].unique()
            sel_loan_month = st.selectbox("🗓️ Select Loan Month", loan_months, key="loan_month_sel")

            cur_loan_df = loan_all_df[loan_all_df["Month_Label"] == sel_loan_month]
            total_pending_till_date = cur_loan_df["pending_loan"].sum()
            total_emi_paid_month = cur_loan_df["amount"].sum()
            active_loan_count = (cur_loan_df["pending_loan"] > 0).sum()

            lk1, lk2 = st.columns(2)
            lk1.metric("Total Pending Loan", format_inr(total_pending_till_date))
            lk2.metric("EMIs Paid This Month", format_inr(total_emi_paid_month))

            lk3, lk4 = st.columns(2)
            lk3.metric("Active Loan Accounts", f"{active_loan_count} Loans")
            lk4.metric("In Words", number_to_indian_words(total_pending_till_date) or "₹0")

            l_act1, l_act2 = st.columns(2)
            with l_act1:
                if st.button("✏️ Modify Loan Entry", use_container_width=True, key="btn_mod_loan"):
                    open_modify_modal(cur_loan_df)
            with l_act2:
                if st.button("🗑️ Delete Loan Entry", use_container_width=True, key="btn_del_loan"):
                    open_delete_modal(cur_loan_df, scope_label=f"Loans in {sel_loan_month}")

            st.divider()

            loan_hole = 0.45 if loan_chart_style == "Donut" else 0.0
            pending_only_df = cur_loan_df[cur_loan_df["pending_loan"] > 0]
            chart_source_df = pending_only_df if not pending_only_df.empty else cur_loan_df
            val_col = "pending_loan" if not pending_only_df.empty else "amount"
            val_title = "Pending Loan" if val_col == "pending_loan" else "EMI Paid"

            # 4 Compact Charts for Loans (Category-wise, Sub-category-wise, Member-wise, Month-over-Month)
            l_ch1, l_ch2 = st.columns(2)
            with l_ch1:
                st.markdown(f"**📂 Category-Wise {val_title}**")
                l_cat_grp = chart_source_df.groupby("Loan_Category", as_index=False)[val_col].sum().sort_values(val_col, ascending=True)
                l_cat_grp["INR_Label"] = l_cat_grp[val_col].apply(format_inr)
                if loan_chart_style in ("Donut", "Solid Pie"):
                    fig_lcat = px.pie(
                        l_cat_grp, values=val_col, names="Loan_Category", hole=loan_hole,
                        custom_data=["INR_Label"],
                        color_discrete_sequence=px.colors.qualitative.Bold
                    )
                    fig_lcat.update_traces(
                        textposition="inside", textinfo="percent+label",
                        hovertemplate="<b>%{label}</b><br>%{customdata[0]} (%{percent})<extra></extra>"
                    )
                    st.plotly_chart(style_compact_chart(fig_lcat), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    fig_lcat_bar = px.bar(
                        l_cat_grp, x=val_col, y="Loan_Category", color="Loan_Category", orientation="h",
                        text="INR_Label", labels={"Loan_Category": "", val_col: "₹"}
                    )
                    fig_lcat_bar.update_traces(hovertemplate="<b>%{y}</b>: %{text}<extra></extra>")
                    st.plotly_chart(style_compact_chart(fig_lcat_bar), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

            with l_ch2:
                st.markdown(f"**🎯 Sub-Category {val_title}**")
                l_sub_grp = chart_source_df.groupby(["sub_category", "Loan_Category"], as_index=False)[val_col].sum().sort_values(val_col, ascending=True)
                l_sub_grp["INR_Label"] = l_sub_grp[val_col].apply(format_inr)
                if loan_chart_style in ("Donut", "Solid Pie"):
                    fig_lsub = px.pie(
                        l_sub_grp, values=val_col, names="sub_category", hole=loan_hole,
                        custom_data=["INR_Label"],
                        color_discrete_sequence=px.colors.qualitative.Vivid
                    )
                    fig_lsub.update_traces(
                        textposition="inside", textinfo="percent+label",
                        hovertemplate="<b>%{label}</b><br>%{customdata[0]} (%{percent})<extra></extra>"
                    )
                    st.plotly_chart(style_compact_chart(fig_lsub), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    fig_lsub_bar = px.bar(
                        l_sub_grp, x=val_col, y="sub_category", color="Loan_Category", orientation="h",
                        text="INR_Label", labels={"sub_category": "", val_col: "₹"}
                    )
                    fig_lsub_bar.update_traces(hovertemplate="<b>%{y}</b>: %{text}<extra></extra>")
                    st.plotly_chart(style_compact_chart(fig_lsub_bar), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

            l_ch3, l_ch4 = st.columns(2)
            with l_ch3:
                st.markdown(f"**👨‍👩‍👦 Member-Wise {val_title}**")
                l_mem_grp = chart_source_df.groupby("member", as_index=False)[val_col].sum()
                l_mem_grp["INR_Label"] = l_mem_grp[val_col].apply(format_inr)
                if loan_chart_style in ("Donut", "Solid Pie"):
                    fig_lmem = px.pie(
                        l_mem_grp, values=val_col, names="member", hole=loan_hole,
                        custom_data=["INR_Label"],
                        color_discrete_sequence=px.colors.qualitative.Set2
                    )
                    fig_lmem.update_traces(
                        textposition="inside", textinfo="percent+label",
                        hovertemplate="<b>%{label}</b>: %{customdata[0]}<extra></extra>"
                    )
                    st.plotly_chart(style_compact_chart(fig_lmem), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    fig_lmem_bar = px.bar(
                        l_mem_grp, x="member", y=val_col, color="member",
                        text="INR_Label", labels={"member": "", val_col: "₹"}
                    )
                    fig_lmem_bar.update_traces(hovertemplate="<b>%{x}</b>: %{text}<extra></extra>")
                    st.plotly_chart(style_compact_chart(fig_lmem_bar), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

            with l_ch4:
                st.markdown("**📉 Month-Wise Loan Trend**")
                mom_loan = loan_all_df.groupby("Month_Key", as_index=False).agg(
                    Pending=("pending_loan", "sum"),
                    EMI=("amount", "sum")
                ).sort_values("Month_Key")
                trend_col = "Pending" if mom_loan["Pending"].sum() > 0 else "EMI"
                mom_loan["INR_Label"] = mom_loan[trend_col].apply(format_inr)
                fig_loan_trend = px.bar(
                    mom_loan, x="Month_Key", y=trend_col, text="INR_Label",
                    color_discrete_sequence=["#e67e22"],
                    labels={"Month_Key": "", trend_col: "₹"}
                )
                fig_loan_trend.update_traces(hovertemplate="<b>%{x}</b>: %{text}<extra></extra>")
                st.plotly_chart(style_compact_chart(fig_loan_trend), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

            st.markdown("**📋 Itemized Loans & EMIs Table**")
            loan_list_disp = cur_loan_df[["Loan_Category", "sub_category", "bank", "member", "amount", "pending_loan", "details"]].copy()
            loan_list_disp["amount"] = loan_list_disp["amount"].apply(lambda x: format_inr(x, 2))
            loan_list_disp["pending_loan"] = loan_list_disp["pending_loan"].apply(lambda x: format_inr(x, 2))
            loan_list_disp.columns = ["Loan Category", "Loan Sub-category", "Bank", "Member", "EMI Paid", "Pending Balance", "Details"]
            st.dataframe(loan_list_disp, use_container_width=True, hide_index=True)

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
        a4.metric(f"Pending Loan ({latest_month_key})", format_inr(latest_pending_loan))

        st.divider()

        st.markdown("**📊 Monthly Income vs. Expense**")
        active_df = df[df["t_type"].isin(["Income", "Expense"])]
        mom_df = active_df.groupby(["Month_Key", "t_type"], as_index=False)["amount"].sum().sort_values("Month_Key")
        mom_df["INR_Label"] = mom_df["amount"].apply(format_inr)
        fig_mom = px.bar(
            mom_df, x="Month_Key", y="amount", color="t_type", barmode="group", text="INR_Label",
            color_discrete_map={"Income": "#2ecc71", "Expense": "#e74c3c"},
            labels={"Month_Key": "", "amount": "₹", "t_type": ""}
        )
        fig_mom.update_traces(hovertemplate="<b>%{x}</b><br>%{fullData.name}: %{text}<extra></extra>")
        st.plotly_chart(style_compact_chart(fig_mom, show_legend=True), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

        st.markdown("**📈 Sub-Category Spending Trend**")
        all_exp_df = df[df["t_type"] == "Expense"]
        if not all_exp_df.empty:
            mom_sub = all_exp_df.groupby(["Month_Key", "sub_category"], as_index=False)["amount"].sum().sort_values("Month_Key")
            mom_sub["INR_Label"] = mom_sub["amount"].apply(format_inr)
            fig_mom_sub = px.bar(
                mom_sub, x="Month_Key", y="amount", color="sub_category",
                custom_data=["INR_Label"],
                labels={"Month_Key": "", "amount": "₹", "sub_category": ""}
            )
            fig_mom_sub.update_traces(hovertemplate="<b>%{x}</b>: %{customdata[0]}<extra></extra>")
            st.plotly_chart(style_compact_chart(fig_mom_sub), use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

    # ------------------------------------------
    # TAB 4: COMPLETE HISTORY WITH RICH MULTI-FILTERS
    # ------------------------------------------
    with tab_records:
        h_btn1, h_btn2, h_btn3, h_btn4 = st.columns(4)
        with h_btn1:
            if st.button("📥 Import CSV", use_container_width=True, key="btn_imp_all"):
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

        st.markdown("##### 🔍 Filter Complete History")
        # Row 1 Filters: Budget Month & Bank
        hf_r1_c1, hf_r1_c2 = st.columns(2)
        with hf_r1_c1:
            all_budget_months = list(df.sort_values("Month_Key", ascending=False)["Month_Key"].unique())
            hist_months = st.multiselect(
                "🗓️ Budget Month",
                options=all_budget_months,
                default=all_budget_months,
                key="hist_f_month"
            )
        with hf_r1_c2:
            all_banks = list(df["bank"].unique())
            hist_banks = st.multiselect(
                "🏦 Bank Account",
                options=all_banks,
                default=all_banks,
                key="hist_f_bank"
            )

        # Row 2 Filters: Transaction Type & Category
        hf_r2_c1, hf_r2_c2 = st.columns(2)
        with hf_r2_c1:
            all_types = list(df["t_type"].unique())
            hist_types = st.multiselect(
                "🔄 Transaction Type",
                options=all_types,
                default=all_types,
                key="hist_f_type"
            )
        with hf_r2_c2:
            avail_cats = sorted(list(df[df["t_type"].isin(hist_types)]["category"].unique()))
            hist_cats = st.multiselect(
                "📂 Category",
                options=avail_cats,
                default=avail_cats,
                key="hist_f_cat"
            )

        # Row 3 Filters: Sub-category & Member + Search
        hf_r3_c1, hf_r3_c2 = st.columns(2)
        with hf_r3_c1:
            avail_subs = sorted(list(df[df["category"].isin(hist_cats)]["sub_category"].unique()))
            hist_subs = st.multiselect(
                "🎯 Sub-category",
                options=avail_subs,
                default=avail_subs,
                key="hist_f_sub"
            )
        with hf_r3_c2:
            all_mems = list(df["member"].unique())
            hist_mems = st.multiselect(
                "👨‍👩‍👦 Family Member",
                options=all_mems,
                default=all_mems,
                key="hist_f_mem"
            )

        search_query = st.text_input(
            "🔎 Search in Details / Narration (Optional)",
            placeholder="Type any keyword (e.g., Manappuram, TCS, Zomato, Cred)..."
        )

        hist_df = df[
            (df["Month_Key"].isin(hist_months)) &
            (df["bank"].isin(hist_banks)) &
            (df["t_type"].isin(hist_types)) &
            (df["category"].isin(hist_cats)) &
            (df["sub_category"].isin(hist_subs)) &
            (df["member"].isin(hist_mems))
        ].copy()

        if search_query.strip():
            q = search_query.strip().lower()
            hist_df = hist_df[
                hist_df["details"].fillna("").str.lower().str.contains(q) |
                hist_df["sub_category"].fillna("").str.lower().str.contains(q)
            ]

        # Live Filtered Summary Metrics
        f_inc = hist_df[hist_df["t_type"] == "Income"]["amount"].sum()
        f_exp = hist_df[hist_df["t_type"] == "Expense"]["amount"].sum()
        f_loan = hist_df["pending_loan"].sum()

        st.caption(
            f"📊 **Showing {len(hist_df)} matching records** | "
            f"Filtered Income: **{format_inr(f_inc)}** | "
            f"Filtered Expense: **{format_inr(f_exp)}** | "
            f"Filtered Pending Loan: **{format_inr(f_loan)}**"
        )

        disp_df = hist_df[["id", "t_date", "Month_Key", "bank", "t_type", "sub_category", "member", "amount", "pending_loan", "category", "details"]].copy()
        disp_df["t_date"] = disp_df["t_date"].dt.strftime("%Y-%m-%d")
        disp_df["amount"] = disp_df["amount"].apply(lambda x: format_inr(x, 2))
        disp_df["pending_loan"] = disp_df["pending_loan"].apply(lambda x: format_inr(x, 2))
        disp_df.columns = [
            "ID", "Actual Date", "Budget Month", "Bank", "Type", "Sub-category", "Member",
            "Amount (₹)", "Pending Loan (₹)", "Category", "Details"
        ]

        raw_csv_df = hist_df[["id", "t_date", "Month_Key", "bank", "t_type", "sub_category", "member", "amount", "pending_loan", "category", "details"]].copy()
        raw_csv_df["t_date"] = raw_csv_df["t_date"].dt.strftime("%Y-%m-%d")
        raw_csv_df.columns = disp_df.columns
        csv_bytes = raw_csv_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            label=f"📥 Download Filtered History ({len(hist_df)} rows) as CSV",
            data=csv_bytes,
            file_name=f"das_family_finances_{date.today()}.csv",
            mime="text/csv",
            use_container_width=True
        )

        st.dataframe(disp_df, use_container_width=True, hide_index=True)

# Footer status badge
st.caption(
    f"⚡ Fast Cached Mode | 📅 Salary Auto-Shift (Day ≥ {SALARY_CUTOFF_DAY} ➡️ Next Month) | 🏦 SBI + HDFC | "
    + ("🟢 Cloud PostgreSQL" if USE_POSTGRES else "🟡 Local SQLite (`expenses.db`)")
)