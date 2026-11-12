import streamlit as st
import pandas as pd
import sqlite3
from datetime import date
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
        font-size: 1.35rem !important;
    }
    button[data-baseweb="tab"] {
        font-size: 0.95rem !important;
        padding: 10px 14px !important;
    }
</style>
""", unsafe_allow_html=True)

PLOTLY_MOBILE_CONFIG = {"displayModeBar": False, "responsive": True}

# ==========================================
# 2. SIMPLE FAMILY PIN AUTHENTICATION
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
# 3. CACHED & POOLED DATABASE ENGINE (FAST!)
# ==========================================
USE_POSTGRES = has_secret("DB_URL")
LOCAL_DB_NAME = "expenses.db"

@st.cache_resource
def get_pg_connection():
    """Keeps a single persistent PostgreSQL connection alive across reruns."""
    return psycopg2.connect(st.secrets["DB_URL"])

def get_connection():
    if USE_POSTGRES:
        conn = get_pg_connection()
        try:
            # Quick ping to check if cloud connection is still alive
            with conn.cursor() as c:
                c.execute("SELECT 1")
        except Exception:
            st.cache_resource.clear()
            conn = get_pg_connection()
        return conn
    return sqlite3.connect(LOCAL_DB_NAME, check_same_thread=False)

@st.cache_resource
def init_db_once():
    """Runs ONLY ONCE when the server starts instead of every button click."""
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
                details TEXT
            )
        """)
        c.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS sub_category TEXT NOT NULL DEFAULT 'General'")
        c.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS pending_loan NUMERIC(12, 2) NOT NULL DEFAULT 0.0")
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
                details TEXT
            )
        """)
        c.execute("PRAGMA table_info(transactions)")
        columns = [col[1] for col in c.fetchall()]
        if "sub_category" not in columns:
            c.execute("ALTER TABLE transactions ADD COLUMN sub_category TEXT NOT NULL DEFAULT 'General'")
        if "pending_loan" not in columns:
            c.execute("ALTER TABLE transactions ADD COLUMN pending_loan REAL NOT NULL DEFAULT 0.0")
    conn.commit()
    c.close()
    if not USE_POSTGRES:
        conn.close()
    return True

# Run DB initialization once per server boot
init_db_once()

@st.cache_data(ttl=600, show_spinner=False)
def load_data():
    """Caches database rows and pre-computes columns in RAM for instant 0ms filtering."""
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM transactions ORDER BY t_date DESC, id DESC", conn)
    if not USE_POSTGRES:
        conn.close()

    if not df.empty:
        df["t_date"] = pd.to_datetime(df["t_date"])
        df["amount"] = df["amount"].astype(float)
        df["pending_loan"] = df["pending_loan"].fillna(0.0).astype(float)
        df["sub_category"] = df["sub_category"].fillna("General")
        df["Month_Key"] = df["t_date"].dt.strftime("%Y-%m")
        df["Month_Label"] = df["t_date"].dt.strftime("%B %Y (%Y-%m)")
        df["Record_Label"] = (
            "#" + df["id"].astype(str) + " | " +
            df["t_date"].dt.strftime("%Y-%m-%d") + " | " +
            df["sub_category"] + " | ₹" +
            df["amount"].map("{:,.0f}".format) +
            df["pending_loan"].apply(lambda x: f" (Loan: ₹{x:,.0f})" if x > 0 else "") +
            " • " + df["member"]
        )
    return df

def add_transaction(t_date, t_type, category, sub_category, member, amount, pending_loan, details):
    conn = get_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("""
            INSERT INTO transactions (t_date, t_type, category, sub_category, member, amount, pending_loan, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (t_date, t_type, category, sub_category, member, amount, pending_loan, details))
    else:
        c.execute("""
            INSERT INTO transactions (t_date, t_type, category, sub_category, member, amount, pending_loan, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(t_date), t_type, category, sub_category, member, amount, pending_loan, details))
    conn.commit()
    c.close()
    if not USE_POSTGRES:
        conn.close()
    load_data.clear()  # Clear RAM cache so new data shows immediately

def bulk_add_transactions(records_list):
    if not records_list:
        return
    conn = get_connection()
    c = conn.cursor()
    if USE_POSTGRES:
        c.executemany("""
            INSERT INTO transactions (t_date, t_type, category, sub_category, member, amount, pending_loan, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, records_list)
    else:
        c.executemany("""
            INSERT INTO transactions (t_date, t_type, category, sub_category, member, amount, pending_loan, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [(str(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in records_list])
    conn.commit()
    c.close()
    if not USE_POSTGRES:
        conn.close()
    load_data.clear()

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
    load_data.clear()

def delete_transactions(t_ids):
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
    load_data.clear()

# ==========================================
# 4. CONSTANTS & CATEGORIES
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

@st.fragment
def render_modify_ui(target_df, key_prefix):
    """Isolated fragment: changing dropdowns here won't reload the whole page!"""
    if target_df.empty:
        st.info("No records available to modify.")
        return

    records_map = dict(zip(target_df["Record_Label"], target_df["id"]))
    selected_label = st.selectbox(
        "Select the entry you want to modify:",
        options=list(records_map.keys()),
        key=f"{key_prefix}_select_record"
    )

    rec_id = records_map[selected_label]
    rec_row = target_df[target_df["id"] == rec_id].iloc[0]

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        type_opts = ["Expense", "Income"]
        default_type_idx = type_opts.index(rec_row["t_type"]) if rec_row["t_type"] in type_opts else 0
        edit_type = st.radio(
            "Transaction Type", type_opts, index=default_type_idx,
            horizontal=True, key=f"{key_prefix}_type_{rec_id}"
        )

    cat_map = EXPENSE_CATEGORY_MAP if edit_type == "Expense" else INCOME_CATEGORY_MAP
    cat_list = list(cat_map.keys())
    default_cat_idx = cat_list.index(rec_row["category"]) if rec_row["category"] in cat_list else 0

    with mc2:
        edit_category = st.selectbox(
            "Category", cat_list, index=default_cat_idx, key=f"{key_prefix}_cat_{rec_id}"
        )

    sub_list = list(cat_map[edit_category])
    current_sub = str(rec_row["sub_category"])
    if current_sub not in sub_list:
        sub_list.insert(0, current_sub)
    sub_list.append("➕ Custom Sub-category...")
    default_sub_idx = sub_list.index(current_sub)

    with mc3:
        edit_sub_choice = st.selectbox(
            "Sub-category", sub_list, index=default_sub_idx, key=f"{key_prefix}_sub_{rec_id}"
        )

    custom_edit_sub = ""
    if edit_sub_choice == "➕ Custom Sub-category...":
        custom_edit_sub = st.text_input(
            "Enter Custom Sub-category", value=current_sub, key=f"{key_prefix}_cust_sub_{rec_id}"
        )

    with st.form(f"{key_prefix}_edit_form_{rec_id}"):
        fc1, fc2 = st.columns(2)
        with fc1:
            edit_date = st.date_input("Date", value=rec_row["t_date"].date())
        with fc2:
            mem_list = list(EXPENSE_MEMBERS if edit_type == "Expense" else EARNING_MEMBERS)
            if rec_row["member"] not in mem_list:
                mem_list.insert(0, rec_row["member"])
            edit_member = st.selectbox("Member", mem_list, index=mem_list.index(rec_row["member"]))

        fc3, fc4 = st.columns(2)
        with fc3:
            edit_amount = st.number_input(
                "Amount Paid / Income (₹)", min_value=0.0,
                value=float(rec_row["amount"]), format="%.2f", step=100.0
            )
        with fc4:
            if edit_type == "Expense":
                edit_pending_loan = st.number_input(
                    "Pending Loan Balance (₹)", min_value=0.0,
                    value=float(rec_row["pending_loan"]), format="%.2f", step=500.0
                )
            else:
                edit_pending_loan = 0.0
                st.caption("Pending Loan is ₹0.00 for Income entries.")

        edit_details = st.text_input("Details / Notes", value=str(rec_row["details"] or ""))

        if st.form_submit_button("💾 Update Entry", type="primary", use_container_width=True):
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

# Load cached dataframe (0ms if already loaded!)
df = load_data()

# ==========================================
# 5. FAST FRAGMENT: ADD ENTRY & CLONE MONTH
# ==========================================
st.markdown("### 💰 Das Family Expense & Loan Tracker")

@st.fragment
def render_add_entry_box():
    """Fragment ensures switching Category/Type dropdowns is instant without redrawing charts."""
    with st.expander("➕ Add New Expense / Income / Loan (Tap Here)", expanded=df.empty):
        top_col1, top_col2, top_col3 = st.columns(3)
        with top_col1:
            t_type = st.radio("Transaction Type", ["Expense", "Income"], horizontal=True)
        with top_col2:
            if t_type == "Expense":
                category = st.selectbox("Category", list(EXPENSE_CATEGORY_MAP.keys()))
            else:
                category = st.selectbox("Income Category", list(INCOME_CATEGORY_MAP.keys()))
        with top_col3:
            if t_type == "Expense":
                sub_options = EXPENSE_CATEGORY_MAP[category] + ["➕ Custom Sub-category..."]
                selected_sub = st.selectbox("Sub-category", sub_options)
            else:
                sub_options = INCOME_CATEGORY_MAP[category] + ["➕ Custom Sub-category..."]
                selected_sub = st.selectbox("Income Sub-category", sub_options)

        custom_sub = ""
        if selected_sub == "➕ Custom Sub-category...":
            custom_sub = st.text_input("Enter Custom Sub-category", placeholder="e.g., Car Loan")

        with st.form("mobile_transaction_form", clear_on_submit=True):
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
                    placeholder="Tap to type amount (e.g., 1500)", step=100.0
                )
            with a_col2:
                if t_type == "Expense":
                    pending_loan = st.number_input(
                        "Pending Loan Till Date (₹) [Optional]",
                        min_value=0.0, value=None,
                        placeholder="Tap if Loan (e.g., 79489)", step=500.0
                    )
                else:
                    pending_loan = None
                    st.caption("ℹ️ Pending Loan is only used for Expense / Loan entries.")

            details = st.text_input("Details / Notes (Optional)", placeholder="e.g., Monthly bill or EMI")

            if st.form_submit_button("💾 Save Entry", type="primary", use_container_width=True):
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
                    st.toast(f"✅ Saved {final_sub}: ₹{clean_amount:,.2f}", icon="💰")
                    st.rerun()

        if not df.empty:
            latest_row = df.iloc[0]
            latest_loan_val = float(latest_row.get("pending_loan", 0.0) or 0.0)
            loan_txt = f" | Loan: ₹{latest_loan_val:,.0f}" if latest_loan_val > 0 else ""
            u_col1, u_col2 = st.columns([3, 1])
            with u_col1:
                st.caption(
                    f"🕒 **Last Added (#{int(latest_row['id'])}):** {latest_row['sub_category']} — "
                    f"₹{float(latest_row['amount']):,.2f}{loan_txt} ({latest_row['member']})"
                )
            with u_col2:
                if st.button("↩️ Undo Last", use_container_width=True):
                    delete_transactions([int(latest_row["id"])])
                    st.toast(f"Deleted entry #{int(latest_row['id'])}!", icon="🗑️")
                    st.rerun()

render_add_entry_box()

# Auto-Fetch / Copy Previous Month's Expenses to Current Month
if not df.empty:
    with st.expander("🔄 Copy / Auto-Fetch Last Month's Expenses to New Month", expanded=False):
        st.caption(
            "Automatically fetch your fixed monthly expenses, loans, and salaries from a previous month. "
            "Uncheck items or edit any amount right in the table before importing!"
        )
        avail_months = df.sort_values("Month_Key", ascending=False)["Month_Label"].unique()

        cl_col1, cl_col2, cl_col3 = st.columns(3)
        with cl_col1:
            source_month = st.selectbox("1️⃣ Copy From Month", avail_months, key="clone_src_month")
        with cl_col2:
            target_date = st.date_input("2️⃣ New Month Date", date.today(), key="clone_target_date")
        with cl_col3:
            clone_filter = st.radio(
                "3️⃣ What to Fetch?",
                ["Only Expenses & Loans", "Both Expenses & Income"],
                horizontal=True, key="clone_type_filter"
            )

        src_df = df[df["Month_Label"] == source_month].copy()
        if clone_filter == "Only Expenses & Loans":
            src_df = src_df[src_df["t_type"] == "Expense"]

        if src_df.empty:
            st.warning("No matching entries found in the selected source month.")
        else:
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
                },
                key="clone_editor_table"
            )

            selected_rows = edited_clone_df[edited_clone_df["Copy"] == True]
            st.caption(
                f"✅ **{len(selected_rows)} entries selected** | "
                f"Total Expense: **₹{selected_rows[selected_rows['Type'] == 'Expense']['Amount (₹)'].sum():,.2f}** | "
                f"Total Pending Loan: **₹{selected_rows['Pending Loan (₹)'].sum():,.2f}**"
            )

            if st.button(
                f"🚀 Import {len(selected_rows)} Checked Entries to {target_date.strftime('%B %Y')}",
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

# ==========================================
# 6. MAIN DASHBOARD
# ==========================================
if df.empty:
    st.info("👋 Tap **➕ Add New Expense / Income / Loan** above to save your first entry!")
else:
    tab_monthly, tab_loans, tab_trends, tab_records = st.tabs([
        "📅 Monthly", "🏦 Loans", "📈 Trends", "📋 History & Edit"
    ])

    # ------------------------------------------
    # TAB 1: MONTH-WISE DASHBOARD (FRAGMENTED FOR INSTANT SWITCHING)
    # ------------------------------------------
    with tab_monthly:
        @st.fragment
        def render_monthly_tab():
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
            r1_c1.metric("Monthly Income", f"₹{m_income:,.0f}")
            r1_c2.metric("Monthly Expense", f"₹{m_expense:,.0f}")

            r2_c1, r2_c2 = st.columns(2)
            r2_c1.metric("Net Savings", f"₹{m_balance:,.0f}", delta=f"₹{m_balance:,.0f}")
            r2_c2.metric("Pending Loan", f"₹{m_pending_loan:,.0f}")

            st.divider()

            exp_m_df = m_df[m_df["t_type"] == "Expense"]
            inc_m_df = m_df[m_df["t_type"] == "Income"]
            loan_m_df = m_df[m_df["pending_loan"] > 0]

            hole_size = 0.42 if chart_style == "PieChart (Donut)" else 0.0

            ch1, ch2 = st.columns(2)
            with ch1:
                st.subheader("🥧 Category-Wise Expense")
                if not exp_m_df.empty and exp_m_df["amount"].sum() > 0:
                    if "PieChart" in chart_style:
                        fig_cat = px.pie(
                            exp_m_df, values="amount", names="category", hole=hole_size,
                            color_discrete_sequence=px.colors.qualitative.Pastel
                        )
                        fig_cat.update_traces(textposition="inside", textinfo="percent+label")
                        fig_cat.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                        st.plotly_chart(fig_cat, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                    else:
                        cat_grp = exp_m_df.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=True)
                        fig_cat_bar = px.bar(
                            cat_grp, x="amount", y="category", color="category", orientation="h",
                            text_auto=".2s", labels={"category": "Category", "amount": "Expense (₹)"}
                        )
                        fig_cat_bar.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                        st.plotly_chart(fig_cat_bar, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    st.info("No expenses recorded for this month.")

            with ch2:
                st.subheader("🎯 Sub-Category Expense")
                if not exp_m_df.empty and exp_m_df["amount"].sum() > 0:
                    if "PieChart" in chart_style:
                        fig_sub_pie = px.pie(
                            exp_m_df, values="amount", names="sub_category", hole=hole_size,
                            color_discrete_sequence=px.colors.qualitative.Safe
                        )
                        fig_sub_pie.update_traces(textposition="inside", textinfo="percent+label")
                        fig_sub_pie.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                        st.plotly_chart(fig_sub_pie, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                    else:
                        sub_grp = exp_m_df.groupby(["sub_category", "category"], as_index=False)["amount"].sum().sort_values("amount", ascending=True)
                        fig_sub_bar = px.bar(
                            sub_grp, x="amount", y="sub_category", color="category", orientation="h",
                            text_auto=".2s", labels={"sub_category": "Sub-category", "amount": "Expense (₹)", "category": "Category"}
                        )
                        fig_sub_bar.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                        st.plotly_chart(fig_sub_bar, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    st.info("No expenses recorded for this month.")

            ch3, ch4 = st.columns(2)
            with ch3:
                st.subheader("👨‍👩‍👦 Family Member Income")
                if not inc_m_df.empty and inc_m_df["amount"].sum() > 0:
                    mem_inc_summary = inc_m_df.groupby("member", as_index=False)["amount"].sum()
                    if "PieChart" in chart_style:
                        fig_inc_pie = px.pie(
                            mem_inc_summary, values="amount", names="member", hole=hole_size,
                            color_discrete_sequence=px.colors.qualitative.Set2
                        )
                        fig_inc_pie.update_traces(textposition="inside", textinfo="percent+label")
                        fig_inc_pie.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                        st.plotly_chart(fig_inc_pie, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                    else:
                        fig_inc_bar = px.bar(
                            mem_inc_summary, x="member", y="amount", color="member",
                            text_auto=".2s", labels={"member": "Family Member", "amount": "Income (₹)"}
                        )
                        fig_inc_bar.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                        st.plotly_chart(fig_inc_bar, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                else:
                    st.info("No income recorded for this month.")

            with ch4:
                st.subheader("🏦 Pending Loan Breakdown")
                if not loan_m_df.empty:
                    if "PieChart" in chart_style:
                        fig_loan_pie = px.pie(
                            loan_m_df, values="pending_loan", names="sub_category", hole=hole_size,
                            color_discrete_sequence=px.colors.qualitative.Bold
                        )
                        fig_loan_pie.update_traces(textposition="inside", textinfo="percent+label")
                        fig_loan_pie.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False)
                        st.plotly_chart(fig_loan_pie, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)
                    else:
                        loan_grp = loan_m_df.groupby(["sub_category", "member"], as_index=False)["pending_loan"].sum().sort_values("pending_loan", ascending=True)
                        fig_loan_bar = px.bar(
                            loan_grp, x="pending_loan", y="sub_category", color="member", orientation="h",
                            text_auto=".2s", labels={"sub_category": "Loan Type", "pending_loan": "Pending Balance (₹)", "member": "Member"}
                        )
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
                    sub_table["Paid"] = sub_table["Paid"].map("₹{:,.0f}".format)
                    sub_table["Loan"] = sub_table["Loan"].map("₹{:,.0f}".format)
                    sub_table.columns = ["Sub-category", "Category", "Paid", "Pending Loan"]
                    st.dataframe(sub_table, use_container_width=True, hide_index=True)

            with t_col2:
                st.subheader("💳 Member Summary")
                if not exp_m_df.empty:
                    mem_exp_table = exp_m_df.groupby("member", as_index=False).agg(
                        Entries=("id", "count"), Total_Paid=("amount", "sum"), Total_Pending_Loan=("pending_loan", "sum")
                    ).sort_values("Total_Paid", ascending=False)
                    mem_exp_table["Total_Paid"] = mem_exp_table["Total_Paid"].map("₹{:,.0f}".format)
                    mem_exp_table["Total_Pending_Loan"] = mem_exp_table["Total_Pending_Loan"].map("₹{:,.0f}".format)
                    mem_exp_table.columns = ["Member", "Items", "Paid", "Pending Loan"]
                    st.dataframe(mem_exp_table, use_container_width=True, hide_index=True)

            st.divider()
            st.subheader(f"🛠️ Edit or Delete in {selected_month}")

            with st.expander(f"✏️ Modify an Entry in {selected_month}", expanded=False):
                render_modify_ui(m_df, key_prefix="month_mod")

            with st.expander(f"🗑️ Delete Wrong Entry in {selected_month}", expanded=False):
                month_records_map = dict(zip(m_df["Record_Label"], m_df["id"]))
                to_delete_month = st.multiselect(
                    "Select wrong entries to delete:",
                    options=list(month_records_map.keys()), key="del_month_select"
                )
                if st.button("🗑️ Delete Selected Entries", type="primary", key="btn_del_month", use_container_width=True):
                    if to_delete_month:
                        ids_to_remove = [month_records_map[label] for label in to_delete_month]
                        delete_transactions(ids_to_remove)
                        st.success(f"✅ Deleted {len(ids_to_remove)} entry(s)!")
                        st.rerun()
                    else:
                        st.warning("Select at least one entry above.")

        render_monthly_tab()

    # ------------------------------------------
    # TAB 2: DEDICATED PENDING LOAN TRACKER
    # ------------------------------------------
    with tab_loans:
        st.subheader("🏦 Pending Loan Status Till Date")
        loan_all_df = df[df["pending_loan"] > 0]

        if loan_all_df.empty:
            st.info("No Pending Loan balances entered yet. Fill in the 'Pending Loan Till Date (₹)' box when adding a loan.")
        else:
            loan_months = loan_all_df.sort_values("Month_Key", ascending=False)["Month_Label"].unique()
            sel_loan_month = st.selectbox("🗓️ Select Month", loan_months, key="loan_month_sel")

            cur_loan_df = loan_all_df[loan_all_df["Month_Label"] == sel_loan_month]
            total_pending_till_date = cur_loan_df["pending_loan"].sum()
            total_emi_paid_month = cur_loan_df["amount"].sum()

            lk1, lk2 = st.columns(2)
            lk1.metric("Total Pending Loan", f"₹{total_pending_till_date:,.0f}")
            lk2.metric("EMIs Paid This Month", f"₹{total_emi_paid_month:,.0f}")

            st.divider()

            lc1, lc2 = st.columns(2)
            with lc1:
                st.subheader("📋 Itemized Pending Loans")
                loan_list_disp = cur_loan_df[["sub_category", "member", "amount", "pending_loan", "details"]].copy()
                loan_list_disp["amount"] = loan_list_disp["amount"].map("₹{:,.0f}".format)
                loan_list_disp["pending_loan"] = loan_list_disp["pending_loan"].map("₹{:,.0f}".format)
                loan_list_disp.columns = ["Loan Type", "Member", "EMI Paid", "Pending Loan", "Details"]
                st.dataframe(loan_list_disp, use_container_width=True, hide_index=True)
                st.success(f"**Total Loan Pending ({sel_loan_month}): ₹{total_pending_till_date:,.2f}**")

            with lc2:
                st.subheader("📉 Month-over-Month Pending Loan")
                mom_loan = loan_all_df.groupby("Month_Key", as_index=False)["pending_loan"].sum().sort_values("Month_Key")
                fig_loan_trend = px.bar(
                    mom_loan, x="Month_Key", y="pending_loan", text_auto=".4s",
                    color_discrete_sequence=["#e67e22"],
                    labels={"Month_Key": "Month", "pending_loan": "Pending Loan (₹)"}
                )
                fig_loan_trend.update_layout(margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig_loan_trend, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

            st.divider()
            with st.expander(f"✏️ Modify a Loan Entry in {sel_loan_month}", expanded=False):
                render_modify_ui(cur_loan_df, key_prefix="loan_mod")

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
        a1.metric("All-Time Income", f"₹{all_inc:,.0f}")
        a2.metric("All-Time Expense", f"₹{all_exp:,.0f}")

        a3, a4 = st.columns(2)
        a3.metric("All-Time Net Savings", f"₹{all_bal:,.0f}")
        a4.metric(f"Latest Pending Loan ({latest_month_key})", f"₹{latest_pending_loan:,.0f}")

        st.divider()

        st.subheader("📊 Monthly Income vs. Expense")
        mom_df = df.groupby(["Month_Key", "t_type"], as_index=False)["amount"].sum().sort_values("Month_Key")
        fig_mom = px.bar(
            mom_df, x="Month_Key", y="amount", color="t_type", barmode="group", text_auto=".2s",
            color_discrete_map={"Income": "#2ecc71", "Expense": "#e74c3c"},
            labels={"Month_Key": "Month", "amount": "Amount (₹)", "t_type": "Type"}
        )
        fig_mom.update_layout(margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_mom, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

        st.subheader("📈 Sub-Category Spending Trend")
        all_exp_df = df[df["t_type"] == "Expense"]
        if not all_exp_df.empty:
            mom_sub = all_exp_df.groupby(["Month_Key", "sub_category"], as_index=False)["amount"].sum().sort_values("Month_Key")
            fig_mom_sub = px.bar(
                mom_sub, x="Month_Key", y="amount", color="sub_category",
                labels={"Month_Key": "Month", "amount": "Expense (₹)", "sub_category": "Sub-category"}
            )
            fig_mom_sub.update_layout(margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig_mom_sub, use_container_width=True, config=PLOTLY_MOBILE_CONFIG)

    # ------------------------------------------
    # TAB 4: ALL RECORDS, EDIT, DELETE & CSV EXPORT
    # ------------------------------------------
    with tab_records:
        with st.expander("✏️ Modify Any Entry (All Months)", expanded=False):
            render_modify_ui(df, key_prefix="all_mod")

        with st.expander("🗑️ Delete Wrong Entries (All Months)", expanded=False):
            all_records_map = dict(zip(df["Record_Label"], df["id"]))
            selected_for_deletion = st.multiselect(
                "Select wrong transaction(s) to remove:",
                options=list(all_records_map.keys()),
                placeholder="Tap to search by date, sub-category, or amount..."
            )
            if st.button("🗑️ Delete Selected", type="primary", use_container_width=True):
                if selected_for_deletion:
                    ids_to_del = [all_records_map[label] for label in selected_for_deletion]
                    delete_transactions(ids_to_del)
                    st.success(f"✅ Deleted {len(ids_to_del)} record(s)!")
                    st.rerun()
                else:
                    st.warning("Select at least one record first.")

        st.divider()
        st.subheader("📋 Complete History")

        clean_df = df[["id", "t_date", "t_type", "sub_category", "member", "amount", "pending_loan", "category", "details"]].copy()
        clean_df["t_date"] = clean_df["t_date"].dt.strftime("%Y-%m-%d")
        clean_df.columns = [
            "ID", "Date", "Type", "Sub-category", "Member",
            "Amount (₹)", "Pending Loan (₹)", "Category", "Details"
        ]

        csv_bytes = clean_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Full History as CSV",
            data=csv_bytes,
            file_name=f"das_family_finances_{date.today()}.csv",
            mime="text/csv",
            use_container_width=True
        )

        st.dataframe(clean_df, use_container_width=True, hide_index=True)

# Footer status badge
st.caption("⚡ Fast Cached Mode | " + ("🟢 Cloud PostgreSQL" if USE_POSTGRES else "🟡 Local SQLite (`expenses.db`)"))