import streamlit as st
import pandas as pd
import numpy as np
import io
import matplotlib.pyplot as plt

# ------------------------------
# Currency formatting (US)
# ------------------------------
def fmt(x):
    return f"${x:,.2f}"

# ------------------------------
# Excel Export (Corrected)
# ------------------------------
def to_excel_bytes(df, sheet_name="Sheet1"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()

# ------------------------------
# Amortization Calculator
# ------------------------------
def amortization_table(principal, annual_rate, months, extra_payment=0):
    monthly_rate = annual_rate / 12 / 100
    if monthly_rate == 0:
        emi = principal / months
    else:
        emi = principal * (monthly_rate * (1 + monthly_rate)**months) / ((1 + monthly_rate)**months - 1)

    emi = float(emi)
    data = []
    balance = principal
    month = 1

    while balance > 0:
        interest = balance * monthly_rate
        principal_component = emi - interest + extra_payment

        if principal_component > balance:
            principal_component = balance
            emi_final = interest + principal_component
        else:
            emi_final = emi + extra_payment

        balance -= principal_component

        data.append([
            month,
            emi_final,
            interest,
            principal_component,
            max(balance, 0)
        ])

        month += 1

    df = pd.DataFrame(data, columns=["Month", "EMI", "Interest", "Principal", "Balance"])
    return df, emi

# ------------------------------
# Yearly Summary
# ------------------------------
def yearly_summary(df):
    df["Year"] = ((df["Month"] - 1) // 12) + 1
    return df.groupby("Year")[["EMI", "Interest", "Principal"]].sum().reset_index()

# ------------------------------
# Streamlit Settings
# ------------------------------
st.set_page_config(
    page_title="Mortgage Planner",
    layout="wide",
    page_icon="🏡",
)

# ------------------------------
# Custom Beautiful CSS
# ------------------------------
st.markdown("""
<style>
/* Main page background */
[data-testid="stAppViewContainer"] {
    background: #f4f7fb;
}

/* Header */
h1 {
    color: #2c3e50;
    font-weight: 700;
}

/* Cards */
.metric-card {
    background: white;
    padding: 20px;
    border-radius: 14px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
    text-align: center;
    margin-bottom: 15px;
}
.metric-card h3 {
    margin: 0;
    color: #34495e;
}
.metric-value {
    font-size: 26px;
    font-weight: 700;
    color: #2c7be5;
}
.metric-sub {
    font-size: 14px;
    color: #7f8c8d;
}
</style>
""", unsafe_allow_html=True)

# ------------------------------
# Title
# ------------------------------
st.title("🏡 Mortgage Payment Planner")
st.write("A clean, modern dashboard to calculate mortgage schedules, savings, and more.")

# ------------------------------
# Input Section
# ------------------------------
st.subheader("🔧 Inputs")

col1, col2, col3 = st.columns(3)

with col1:
    principal = st.number_input("Remaining Loan Amount (USD)", value=300000.0, min_value=0.0, step=1000.0)

with col2:
    annual_rate = st.number_input("Annual Interest Rate (%)", value=6.5, min_value=0.0, step=0.1)

with col3:
    tenure_years = st.number_input("Remaining Tenure (Years)", value=30, min_value=1, step=1)

extra_payment = st.number_input("Extra Monthly Payment (optional)", value=0.0, min_value=0.0, step=50.0)
tax_rate = st.number_input("Tax Benefit on Interest (%)", value=30.0)

months = int(tenure_years * 12)

# ------------------------------
# Calculate Tables
# ------------------------------
df_original, emi_original = amortization_table(principal, annual_rate, months, extra_payment=0)
total_interest_original = df_original["Interest"].sum()
tax_saved_original = total_interest_original * (tax_rate / 100)

if extra_payment > 0:
    df_extra, emi_extra = amortization_table(principal, annual_rate, months, extra_payment)
    total_interest_extra = df_extra["Interest"].sum()
    interest_saved = total_interest_original - total_interest_extra
    months_saved = len(df_original) - len(df_extra)

# ------------------------------
# Summary Cards (Beautiful)
# ------------------------------
st.subheader("📊 Summary Overview")

card1, card2, card3, card4 = st.columns(4)

with card1:
    st.markdown(f"""
    <div class="metric-card">
        <h3>Monthly EMI</h3>
        <div class="metric-value">{fmt(emi_original)}</div>
    </div>
    """, unsafe_allow_html=True)

with card2:
    st.markdown(f"""
    <div class="metric-card">
        <h3>Total Interest (Original)</h3>
        <div class="metric-value">{fmt(total_interest_original)}</div>
    </div>
    """, unsafe_allow_html=True)

with card3:
    st.markdown(f"""
    <div class="metric-card">
        <h3>Tax Savings</h3>
        <div class="metric-value">{fmt(tax_saved_original)}</div>
    </div>
    """, unsafe_allow_html=True)

with card4:
    st.markdown(f"""
    <div class="metric-card">
        <h3>Loan Duration</h3>
        <div class="metric-value">{len(df_original)} months</div>
        <div class="metric-sub">({len(df_original)/12:.1f} years)</div>
    </div>
    """, unsafe_allow_html=True)

# ------------------------------
# Extra Payment Comparison
# ------------------------------
if extra_payment > 0:
    st.subheader("⚡ Extra Payment Impact")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <h3>New Duration</h3>
            <div class="metric-value">{len(df_extra)} months</div>
            <div class="metric-sub">({len(df_extra)/12:.1f} years)</div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Months Saved</h3>
            <div class="metric-value">{months_saved}</div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Interest Saved</h3>
            <div class="metric-value">{fmt(interest_saved)}</div>
        </div>
        """, unsafe_allow_html=True)

# ------------------------------
# Chart
# ------------------------------
st.subheader("📉 Balance Reduction Over Time")

fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(df_original["Month"], df_original["Balance"], label="Original", linewidth=2)

if extra_payment > 0:
    ax.plot(df_extra["Month"], df_extra["Balance"], label="With Extra Payment", linewidth=2)

ax.set_xlabel("Month")
ax.set_ylabel("Balance (USD)")
ax.legend()
ax.grid(alpha=0.3)

st.pyplot(fig)

# ------------------------------
# Tables
# ------------------------------
st.subheader("📄 Amortization Table")
df_show = df_extra if extra_payment > 0 else df_original
st.dataframe(df_show, height=380)

st.subheader("📘 Yearly Summary")
st.dataframe(yearly_summary(df_show))

# ------------------------------
# Downloads
# ------------------------------
st.subheader("⬇️ Download Data")

colX, colY = st.columns(2)

with colX:
    csv = df_show.to_csv(index=False).encode()
    st.download_button("Download CSV", csv, "amortization.csv", "text/csv")

with colY:
    excel_bytes = to_excel_bytes(df_show, sheet_name="Amortization")
    st.download_button("Download Excel", excel_bytes, "amortization.xlsx", "application/vnd.ms-excel")
