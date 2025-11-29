import streamlit as st
import numpy as np
import pandas as pd
import altair as alt
from io import BytesIO

# -----------------------------
# USD formatting
# -----------------------------
def fmt(x):
    return f"${x:,.2f}"


# -----------------------------
# EMI calculation
# -----------------------------
def calculate_emi(principal, annual_rate, months):
    monthly_rate = annual_rate / 12 / 100
    if monthly_rate == 0:
        return principal / months
    emi = principal * monthly_rate * (1 + monthly_rate) ** months / ((1 + monthly_rate) ** months - 1)
    return emi


# -----------------------------
# Amortization table
# -----------------------------
def amortization_table(principal, annual_rate, months, extra_payment=0):
    monthly_rate = annual_rate / 12 / 100
    emi = calculate_emi(principal, annual_rate, months)
    balance = principal

    data = []
    month = 1

    while balance > 0 and month <= 2000:
        interest = balance * monthly_rate
        principal_component = emi - interest + extra_payment

        if principal_component > balance:
            principal_component = balance
            payment = interest + balance
        else:
            payment = emi + extra_payment

        balance -= principal_component

        data.append([
            month,
            payment,
            interest,
            principal_component,
            max(balance, 0)
        ])
        month += 1

    df = pd.DataFrame(data, columns=["Month", "Payment", "Interest", "Principal", "Balance"])
    return df


# -----------------------------
# Excel Export
# -----------------------------
def to_excel(df, sheet="Sheet1"):
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine="openpyxl")
    df.to_excel(writer, index=False, sheet_name=sheet)
    writer.close()
    output.seek(0)
    return output.read()


# -----------------------------
# Yearly summary
# -----------------------------
def yearly_summary(df):
    df["Year"] = (df["Month"] - 1) // 12 + 1
    return df.groupby("Year").agg({
        "Payment": "sum",
        "Interest": "sum",
        "Principal": "sum",
        "Balance": "last"
    }).reset_index()


# -----------------------------
# STREAMLIT PREMIUM FINTECH UI
# -----------------------------
st.set_page_config(page_title="Mortgage Planner (USD)", layout="wide")

# Custom fintech CSS
st.markdown("""
<style>
body {
    font-family: 'Inter', sans-serif;
}
.main-title {
    font-size: 42px;
    font-weight: 800;
    background: linear-gradient(90deg, #005bea 0%, #00c6fb 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.sub-text {
    font-size: 18px;
    color: #6b7280;
}
.fin-card {
    padding: 25px;
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.65);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(200, 200, 200, 0.35);
    box-shadow: 0px 4px 10px rgba(0,0,0,0.08);
    transition: transform .15s ease;
}
.fin-card:hover {
    transform: translateY(-4px);
}
.metric-label {
    font-size: 15px;
    color: #6b7280;
}
.metric-value {
    font-size: 30px;
    font-weight: 700;
    margin-top: 4px;
}
.section-title {
    font-size: 28px;
    font-weight: 700;
    margin-top: 20px;
    margin-bottom: 10px;
}
</style>
""", unsafe_allow_html=True)

# -----------------------------
# HEADER
# -----------------------------
st.markdown("<div class='main-title'>🏦 Mortgage Planner (USD)</div>", unsafe_allow_html=True)
st.markdown("<div class='sub-text'>A premium, interactive mortgage payoff simulator with extra payments, charts, and tax benefits.</div>", unsafe_allow_html=True)
st.markdown("---")

# -----------------------------
# INPUT AREA
# -----------------------------
left, right = st.columns(2)

with left:
    principal = st.number_input("🏠 Remaining Loan Amount ($)", value=350000.0, step=1000.0)
    rate = st.number_input("📈 Annual Interest Rate (%)", value=6.5, step=0.1)

with right:
    years = st.number_input("⏳ Remaining Tenure (Years)", value=25, step=1)
    extra = st.number_input("💡 Extra Monthly Payment (Optional)", value=0.0, step=50.0)

tax_rate = st.number_input("💸 Tax Savings Rate (%)", value=30.0, step=1.0)

months = int(years * 12)

# -----------------------------
# COMPUTATION
# -----------------------------
df_orig = amortization_table(principal, rate, months, extra_payment=0)
df_extra = amortization_table(principal, rate, months, extra_payment=extra)

emi = calculate_emi(principal, rate, months)
total_interest = df_orig["Interest"].sum()
tax_benefit = total_interest * (tax_rate / 100)

extra_months_saved = len(df_orig) - len(df_extra)
interest_saved = df_orig["Interest"].sum() - df_extra["Interest"].sum()

# -----------------------------
# SUMMARY CARDS
# -----------------------------
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown(f"""
    <div class='fin-card'>
        <div class='metric-label'>Monthly EMI</div>
        <div class='metric-value'>{fmt(emi)}</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class='fin-card'>
        <div class='metric-label'>Total Interest</div>
        <div class='metric-value'>{fmt(total_interest)}</div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class='fin-card'>
        <div class='metric-label'>Tax Benefit</div>
        <div class='metric-value'>{fmt(tax_benefit)}</div>
    </div>
    """, unsafe_allow_html=True)

with c4:
    st.markdown(f"""
    <div class='fin-card'>
        <div class='metric-label'>Loan Ends In</div>
        <div class='metric-value'>{len(df_orig)//12} yrs</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# -----------------------------
# EXTRA PAYMENT IMPACT
# -----------------------------
if extra > 0:
    st.markdown("<div class='section-title'>🔥 Extra Payment Impact</div>", unsafe_allow_html=True)

    a, b, c = st.columns(3)

    with a:
        st.metric("New Monthly Payment", fmt(emi + extra))

    with b:
        st.metric("Interest Saved", fmt(interest_saved))

    with c:
        st.metric("Months Saved", extra_months_saved)

    # Chart
    comp = pd.DataFrame({
        "Month": df_orig["Month"],
        "Original": df_orig["Balance"],
    })
    comp = comp.merge(
        df_extra[["Month", "Balance"]].rename(columns={"Balance": "Extra Payment"}),
        on="Month", how="left"
    ).melt("Month", var_name="Type", value_name="Balance")

    chart = alt.Chart(comp).mark_line().encode(
        x="Month",
        y=alt.Y("Balance", title="Remaining Balance ($)"),
        color="Type"
    ).properties(height=400)

    st.altair_chart(chart, use_container_width=True)

st.markdown("---")

# -----------------------------
# TABLES + DOWNLOADS
# -----------------------------
tab1, tab2, tab3 = st.tabs(["📊 Amortization Table", "📅 Yearly Summary", "📥 Downloads"])

with tab1:
    st.dataframe(df_orig, use_container_width=True)

with tab2:
    st.dataframe(yearly_summary(df_orig), use_container_width=True)

with tab3:
    st.download_button(
        "Download Amortization (Excel)",
        data=to_excel(df_orig),
        file_name="amortization.xlsx"
    )
    st.download_button(
        "Download Amortization (CSV)",
        df_orig.to_csv(index=False),
        file_name="amortization.csv"
    )
