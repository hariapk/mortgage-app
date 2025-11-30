# mortgage_app.py
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from io import BytesIO
import math
from datetime import datetime

st.set_page_config(page_title="Mortgage + Tax Planner", layout="wide", page_icon="🏦")

# ---------------------------
# Helper functions
# ---------------------------

def format_usd(x):
    try:
        return f"${x:,.2f}"
    except:
        return str(x)

def indian_format(x):
    # Not used by default; kept for completeness
    return f"₹{x:,.2f}"

def to_excel_bytes(df, sheet_name="Sheet1"):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()

# ---------------------------
# Tax data (2025-style brackets & standard deductions)
# NOTE: brackets are represented as (threshold, rate)
# thresholds are taxable-income lower bounds
# ---------------------------

STANDARD_DEDUCTION = {
    "Single": 13850,  # example 2023/2024 changed; adjust if you want exact 2025 figures
    "Married Filing Jointly": 27700,
    "Married Filing Separately": 13850,
    "Head of Household": 20800
}

# We'll use reasonable 2024/2025-like progressive thresholds (approximate).
# You can update numbers later; structure below supports easy change.
FEDERAL_BRACKETS = {
    "Single": [
        (0, 0.10),
        (11000, 0.12),
        (44725, 0.22),
        (95375, 0.24),
        (182100, 0.32),
        (231250, 0.35),
        (578125, 0.37)
    ],
    "Married Filing Jointly": [
        (0, 0.10),
        (22000, 0.12),
        (89450, 0.22),
        (190750, 0.24),
        (364200, 0.32),
        (462500, 0.35),
        (693750, 0.37)
    ],
    "Married Filing Separately": [
        (0, 0.10),
        (11000, 0.12),
        (44725, 0.22),
        (95375, 0.24),
        (182100, 0.32),
        (231250, 0.35),
        (346875, 0.37)
    ],
    "Head of Household": [
        (0, 0.10),
        (15700, 0.12),
        (59850, 0.22),
        (95350, 0.24),
        (182100, 0.32),
        (231250, 0.35),
        (578100, 0.37)
    ]
}

CHILD_TAX_CREDIT_PER_DEP = 2000  # simple assumption; user can edit in UI if desired
SALT_CAP = 10000  # $10k SALT cap

def compute_progressive_tax(taxable_income, filing_status):
    """
    Compute federal tax given taxable_income using FEDERAL_BRACKETS table.
    This returns the tax liability before credits.
    """
    if taxable_income <= 0:
        return 0.0
    brackets = FEDERAL_BRACKETS[filing_status]
    tax = 0.0
    # iterate thresholds ascending, compute tax in each bracket
    for i in range(len(brackets)):
        lower, rate = brackets[i]
        if i + 1 < len(brackets):
            upper = brackets[i + 1][0]
        else:
            upper = math.inf
        if taxable_income > lower:
            taxed_amount = min(taxable_income, upper) - lower
            if taxed_amount > 0:
                tax += taxed_amount * rate
        else:
            break
    return tax

# ---------------------------
# Mortgage / Amortization functions
# ---------------------------

def monthly_emi_for_P_r_n(P, annual_rate, n_months):
    r = annual_rate / 12.0 / 100.0
    if n_months <= 0:
        return 0.0
    if r == 0:
        return P / n_months
    pow_val = (1 + r) ** n_months
    emi = P * r * pow_val / (pow_val - 1)
    return emi

def build_amortization(P, annual_rate, n_months, extra_monthly=0.0):
    """
    Returns DataFrame with Month, EMI (base EMI), Interest, Principal, ExtraPayment, TotalPayment, Balance
    This simulates months until balance <= small epsilon.
    """
    schedule = []
    monthly_rate = annual_rate / 12.0 / 100.0
    if monthly_rate == 0:
        base_emi = P / n_months if n_months > 0 else 0.0
    else:
        base_emi = monthly_emi_for_P_r_n(P, annual_rate, n_months)
    balance = float(P)
    month = 0
    cap = max(n_months * 10, 12000)
    while balance > 0.005 and month < cap:
        month += 1
        interest = balance * monthly_rate
        principal_component = base_emi - interest
        if principal_component < 0:
            # interest-only scenario; avoid negative amortization
            principal_component = 0.0
        extra = min(extra_monthly, balance - principal_component) if (balance - principal_component) > 0 else 0.0
        total_principal = principal_component + extra
        total_payment = base_emi + extra
        # if total payment would overpay:
        if interest + total_principal >= balance + interest - 1e-9:
            # final payment
            total_payment = balance + interest
            principal_component = balance
            extra = max(0.0, total_payment - base_emi - interest)
            total_principal = principal_component
            balance = 0.0
            schedule.append({
                "Month": month,
                "BaseEMI": base_emi,
                "Interest": interest,
                "Principal": principal_component,
                "ExtraPayment": extra,
                "TotalPayment": total_payment,
                "Balance": balance
            })
            break
        else:
            balance = balance - total_principal
            schedule.append({
                "Month": month,
                "BaseEMI": base_emi,
                "Interest": interest,
                "Principal": principal_component,
                "ExtraPayment": extra,
                "TotalPayment": total_payment,
                "Balance": balance
            })
    df = pd.DataFrame(schedule)
    if not df.empty:
        df.index = np.arange(1, len(df) + 1)
    return df

# ---------------------------
# Streamlit UI
# ---------------------------

st.title("🏦 Mortgage + Tax Planner (US)")

st.sidebar.header("Mortgage Inputs")
hp = st.sidebar.number_input("Home price ($)", value=780000.0, step=1000.0, format="%.2f")
down = st.sidebar.number_input("Down payment ($)", value=0.0, step=500.0, format="%.2f")
loan_amount = max(0.0, hp - down)

rate = st.sidebar.slider("Annual interest rate (%)", min_value=0.01, max_value=15.0, value=5.5, step=0.01)
term_years = st.sidebar.selectbox("Loan term (years)", options=[10,15,20,25,30], index=3)
n_months = int(term_years * 12)

extra_monthly = st.sidebar.number_input("Extra monthly payment ($)", value=0.0, step=50.0, format="%.2f")

st.sidebar.markdown("---")
st.sidebar.header("Tax Inputs (US)")

filing_status = st.sidebar.selectbox("Filing status", options=list(STANDARD_DEDUCTION.keys()), index=1)
income = st.sidebar.number_input("Annual household income ($)", value=700000.0, step=1000.0, format="%.2f")
num_dependents = st.sidebar.number_input("Number of dependents (children)", value=0, min_value=0, max_value=10, step=1)
child_credit_per = st.sidebar.number_input("Child tax credit per dependent ($)", value=2000, step=100)
state_tax_rate = st.sidebar.slider("State income tax rate (%)", 0.0, 13.0, 0.0, step=0.1)/100.0

force_itemize = st.sidebar.checkbox("Force itemize (override standard deduction)", value=False)
include_property_tax = st.sidebar.checkbox("Include property tax in itemized deductions (SALT)", value=True)

st.sidebar.markdown("---")
st.sidebar.write("SALT cap (property + state/local tax) is applied at $10,000 by default.")
salt_cap = st.sidebar.number_input("SALT cap ($)", value=10000.0, step=100.0)

# ---------------------------
# Compute amortization schedules
# ---------------------------

df_orig = build_amortization(loan_amount, rate, n_months, extra_monthly=0.0)
df_extra = build_amortization(loan_amount, rate, n_months, extra_monthly=extra_monthly if extra_monthly>0 else 0.0)

# First-year interest (sum of interest in months 1..12 or all if <12)
def first_year_interest(df):
    if df.empty:
        return 0.0
    return df.loc[df["Month"] <= 12, "Interest"].sum()

first_year_interest_orig = first_year_interest(df_orig)
first_year_interest_extra = first_year_interest(df_extra)

total_interest_orig = df_orig["Interest"].sum() if not df_orig.empty else 0.0
total_interest_extra = df_extra["Interest"].sum() if not df_extra.empty else 0.0

# Property tax (annual) input and compute SALT
property_tax_rate = st.sidebar.slider("Property tax rate (%)", 0.0, 3.0, 0.2, step=0.01)/100.0
annual_property_tax = hp * property_tax_rate if include_property_tax else 0.0
salt_deduction = min(annual_property_tax, salt_cap)

# Itemized deductions: mortgage interest (first-year estimate) + SALT
itemized_annual = first_year_interest_orig + salt_deduction

# Decide deduction used
std_ded = STANDARD_DEDUCTION[filing_status]
is_itemizing = (itemized_annual > std_ded) or force_itemize
deduction_used = "Itemized" if is_itemizing else "Standard"

# Compute taxable incomes & tax with and without interest deduction
# Tax when itemizing and including interest:
if is_itemizing:
    taxable_with_interest = max(0.0, income - itemized_annual)
else:
    taxable_with_interest = max(0.0, income - std_ded)

# Tax if interest were NOT deductible (simulate by removing mortgage interest)
itemized_without_interest = (itemized_annual - first_year_interest_orig) if include_property_tax else 0.0 + salt_deduction
if is_itemizing:
    taxable_without_interest = max(0.0, income - (itemized_annual - first_year_interest_orig))
else:
    taxable_without_interest = taxable_with_interest  # standard deduction chosen: no change

# Compute federal tax liabilities before credits
tax_with_interest = compute_progressive_tax(taxable_with_interest, filing_status)
tax_without_interest = compute_progressive_tax(taxable_without_interest, filing_status)

# Compute child tax credit (simple model): applied to tax_with_interest
child_credit_total = num_dependents * child_credit_per
tax_after_credits_with_interest = max(0.0, tax_with_interest - child_credit_total)
tax_after_credits_without_interest = max(0.0, tax_without_interest - child_credit_total)

# State tax effect: if user itemizes, state tax paid may reduce federal taxable amounts (we included property tax via SALT cap)
# For simple model, we add state tax as a portion of income paid (income * state_tax_rate) but recall SALT cap already limits deduction on state/local taxes.
# We'll compute state tax paid (for information) but not double-count it.
state_tax_paid = income * state_tax_rate

# Tax savings due to interest deduction:
annual_tax_savings = tax_after_credits_without_interest - tax_after_credits_with_interest
if annual_tax_savings < 0:
    # shouldn't be negative; clamp
    annual_tax_savings = 0.0

# Effective mortgage cost after tax for first-year interest:
effective_first_year_interest = first_year_interest_orig - annual_tax_savings
effective_interest_rate = (effective_first_year_interest / loan_amount) * 100 if loan_amount > 0 else 0.0

# For extra-payment scenario, compute savings & months saved & interest saved
months_orig = len(df_orig)
months_extra = len(df_extra)
months_saved = max(0, months_orig - months_extra)
interest_saved = total_interest_orig - total_interest_extra

# ---------------------------
# Layout: Summary cards & outputs
# ---------------------------
st.markdown("## Summary")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Monthly Payment (base EMI)", format_usd(monthly_emi_for_P_r_n(loan_amount, rate, n_months)))
    st.write("Loan amount")
    st.write(format_usd(loan_amount))

with col2:
    st.metric("First-year interest (approx)", format_usd(first_year_interest_orig))
    st.write("Annual property tax (est.)")
    st.write(format_usd(annual_property_tax))

with col3:
    st.metric("Deduction used", deduction_used)
    st.write("Standard deduction")
    st.write(format_usd(std_ded))

with col4:
    st.metric("Annual Tax Savings (estimate)", format_usd(annual_tax_savings))
    st.write("Effective mortgage rate (first year)")
    st.write(f"{effective_interest_rate:.2f}%")

st.markdown("---")

# ---------------------------
# Charts: Balance comparison
# ---------------------------
st.header("Balance over time — Original vs With Extra Payment")

# prepare merged DF up to max months
max_months = max(len(df_orig), len(df_extra))
months_index = np.arange(1, max_months+1)
df_plot = pd.DataFrame({"Month": months_index})
if not df_orig.empty:
    df_plot = df_plot.merge(df_orig[["Month", "Balance"]].rename(columns={"Balance":"Balance_Original"}), on="Month", how="left")
else:
    df_plot["Balance_Original"] = 0.0
if not df_extra.empty:
    df_plot = df_plot.merge(df_extra[["Month", "Balance"]].rename(columns={"Balance":"Balance_Extra"}), on="Month", how="left")
else:
    df_plot["Balance_Extra"] = 0.0

df_plot["Balance_Original"].ffill(inplace=True)
df_plot["Balance_Original"].fillna(0, inplace=True)
df_plot["Balance_Extra"].ffill(inplace=True)
df_plot["Balance_Extra"].fillna(0, inplace=True)

melt = df_plot.melt("Month", value_vars=["Balance_Original", "Balance_Extra"], var_name="Scenario", value_name="Balance")
melt["Scenario"] = melt["Scenario"].map({"Balance_Original": "Original", "Balance_Extra":"With Extra"})

chart = alt.Chart(melt).mark_line().encode(
    x="Month",
    y=alt.Y("Balance", title="Outstanding Balance ($)"),
    color="Scenario"
).properties(height=400)
st.altair_chart(chart, use_container_width=True)

# ---------------------------
# Amortization Tables
# ---------------------------
st.header("Amortization Schedules")

tab1, tab2 = st.tabs(["Original schedule", "With extra payment"])

with tab1:
    if df_orig.empty:
        st.write("No schedule")
    else:
        df_display = df_orig.copy()
        df_display["BaseEMI"] = df_display["BaseEMI"].round(2)
        df_display["Interest"] = df_display["Interest"].round(2)
        df_display["Principal"] = df_display["Principal"].round(2)
        df_display["ExtraPayment"] = df_display["ExtraPayment"].round(2)
        df_display["TotalPayment"] = df_display["TotalPayment"].round(2)
        df_display["Balance"] = df_display["Balance"].round(2)
        st.dataframe(df_display, use_container_width=True)
        csv = df_display.to_csv(index=False).encode('utf-8')
        st.download_button("Download original schedule (CSV)", csv, "original_schedule.csv", "text/csv")
        st.download_button("Download original schedule (Excel)", to_excel_bytes(df_display, "Original"), "original_schedule.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab2:
    if df_extra.empty:
        st.write("No schedule")
    else:
        df_display2 = df_extra.copy()
        df_display2["BaseEMI"] = df_display2["BaseEMI"].round(2)
        df_display2["Interest"] = df_display2["Interest"].round(2)
        df_display2["Principal"] = df_display2["Principal"].round(2)
        df_display2["ExtraPayment"] = df_display2["ExtraPayment"].round(2)
        df_display2["TotalPayment"] = df_display2["TotalPayment"].round(2)
        df_display2["Balance"] = df_display2["Balance"].round(2)
        st.dataframe(df_display2, use_container_width=True)
        csv2 = df_display2.to_csv(index=False).encode('utf-8')
        st.download_button("Download extra schedule (CSV)", csv2, "extra_schedule.csv", "text/csv")
        st.download_button("Download extra schedule (Excel)", to_excel_bytes(df_display2, "WithExtra"), "extra_schedule.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.markdown("---")

# ---------------------------
# Yearly summary (original)
# ---------------------------
def yearly_summary(df):
    if df.empty:
        return pd.DataFrame()
    df2 = df.copy()
    df2["Year"] = ((df2["Month"] - 1) // 12) + 1
    yearly = df2.groupby("Year").agg({
        "Interest": "sum",
        "Principal": "sum",
        "ExtraPayment": "sum",
        "TotalPayment": "sum",
        "Balance": "last"
    }).reset_index()
    return yearly

st.header("Yearly Summary (Original)")
ys = yearly_summary(df_orig)
if ys.empty:
    st.write("No data")
else:
    ys_display = ys.copy()
    ys_display[["Interest","Principal","ExtraPayment","TotalPayment","Balance"]] = ys_display[["Interest","Principal","ExtraPayment","TotalPayment","Balance"]].round(2)
    st.dataframe(ys_display, use_container_width=True)
    st.download_button("Download yearly summary (CSV)", ys.to_csv(index=False).encode('utf-8'), "yearly_summary.csv", "text/csv")

st.markdown("---")

# ---------------------------
# Detailed Tax calculation box
# ---------------------------
st.header("Tax Calculation Details (estimate)")

colA, colB = st.columns(2)
with colA:
    st.subheader("Inputs")
    st.write(f"Filing status: **{filing_status}**")
    st.write(f"Annual income: **{format_usd(income)}**")
    st.write(f"Dependents: **{num_dependents}**, Child tax credit each: **{format_usd(child_credit_per)}**")
    st.write(f"Property tax (annual estimate): **{format_usd(annual_property_tax)}** (rate {property_tax_rate*100:.2f}%)")
    st.write(f"SALT cap used: **{format_usd(salt_deduction)}** (cap {format_usd(salt_cap)})")
    st.write(f"Itemized deductions (interest + SALT): **{format_usd(itemized_annual)}**")
    st.write(f"Standard deduction: **{format_usd(std_ded)}**")
    st.write(f"Deduction used: **{deduction_used}**")
with colB:
    st.subheader("Computed taxes")
    st.write(f"Taxable income (with interest): **{format_usd(taxable_with_interest)}**")
    st.write(f"Tax before credits (with interest): **{format_usd(tax_with_interest)}**")
    st.write(f"Tax after child credits (with interest): **{format_usd(tax_after_credits_with_interest)}**")
    st.write("----")
    st.write(f"Taxable income (without interest): **{format_usd(taxable_without_interest)}**")
    st.write(f"Tax before credits (without interest): **{format_usd(tax_without_interest)}**")
    st.write(f"Tax after child credits (without interest): **{format_usd(tax_after_credits_without_interest)}**")
    st.write("----")
    st.write(f"Estimated annual tax savings from interest deduction: **{format_usd(annual_tax_savings)}**")
    st.write(f"Effective first-year interest after tax savings: **{format_usd(effective_first_year_interest)}**")
    st.write(f"Effective mortgage interest rate (first year): **{effective_interest_rate:.2f}%**")

st.markdown("---")

st.caption("This tool provides estimates only. It uses first-year interest as a proxy for annual mortgage interest for deduction calculations and applies a simplified child tax credit model. For precise tax advice consult a tax professional.")
