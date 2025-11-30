import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ================================================================
# FIX: Wipe all previous widget state so each user sees fresh app
# ================================================================
for key in list(st.session_state.keys()):
    del st.session_state[key]


# ---------------------------------------------------------------
# Utility: Currency formatting
# ---------------------------------------------------------------
def fmt(x, currency="USD"):
    if currency == "USD":
        return f"${x:,.2f}"
    else:
        return f"₹{x:,.2f}"


# ---------------------------------------------------------------
# Excel download helper
# ---------------------------------------------------------------
def to_excel_bytes(df, sheet_name="Sheet1"):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


# ---------------------------------------------------------------
# Mortgage EMI calculation
# ---------------------------------------------------------------
def calculate_emi(principal, annual_rate, months):
    r = annual_rate / 12 / 100
    if r == 0:
        return principal / months
    emi = principal * r * (1 + r) ** months / ((1 + r) ** months - 1)
    return emi


# ---------------------------------------------------------------
# Build amortization schedule
# ---------------------------------------------------------------
def amortization_table(principal, rate, months, extra_payment=0):
    r = rate / 12 / 100
    emi = calculate_emi(principal, rate, months)

    data = []
    balance = principal
    month = 1

    while balance > 0 and month <= 2000:  # safety cap
        interest = balance * r
        principal_component = emi - interest + extra_payment

        if principal_component > balance:
            principal_component = balance

        balance -= principal_component

        data.append([
            month,
            emi + extra_payment,
            interest,
            principal_component,
            max(balance, 0)
        ])

        month += 1

    df = pd.DataFrame(data, columns=["Month", "Payment", "Interest", "Principal", "Balance"])
    return df


# ---------------------------------------------------------------
# U.S. Standard Deduction 2025 (IRS)
# ---------------------------------------------------------------
def get_standard_deduction(filing_status, dependents):
    base = {
        "Single": 14600,
        "Married Filing Jointly": 29200,
        "Married Filing Separately": 14600,
        "Head of Household": 21900
    }
    extra = dependents * 500  # simple assumption
    return base[filing_status] + extra


# ---------------------------------------------------------------
# Tax Savings from Mortgage Interest
# ---------------------------------------------------------------
def tax_savings_from_interest(total_interest, filing_status, dependents, marginal_rate):
    std_deduction = get_standard_deduction(filing_status, dependents)

    # Only the *amount exceeding standard deduction* gives benefit
    deductible_interest = max(total_interest - std_deduction, 0)

    tax_saved = deductible_interest * (marginal_rate / 100)
    return tax_saved, std_deduction, deductible_interest


# ---------------------------------------------------------------
# MAIN APP UI
# ---------------------------------------------------------------
def main():

    st.markdown("<h1 style='color:black;'>🏦 Mortgage Planner</h1>", unsafe_allow_html=True)
    st.write("A clean, premium mortgage planner with tax optimization.")

    st.divider()

    # -------------------------------
    # Currency toggle
    # -------------------------------
    currency = st.selectbox("Currency", ["USD", "INR"], index=0)

    # -------------------------------
    # Inputs
    # -------------------------------
    col1, col2 = st.columns(2)
    with col1:
        principal = st.number_input("Remaining Loan Amount", min_value=1000.0, step=1000.0)
        annual_rate = st.number_input("Annual Interest Rate (%)", min_value=0.1, step=0.1)
        tenure_years = st.number_input("Remaining Tenure (Years)", min_value=1.0, step=1.0)
    with col2:
        extra_payment = st.number_input("Extra Monthly Payment (Optional)", min_value=0.0, step=50.0)
        filing_status = st.selectbox("Filing Status", [
            "Single", "Married Filing Jointly", "Married Filing Separately", "Head of Household"
        ])
        dependents = st.number_input("Number of Dependents", min_value=0, step=1)
        marginal_rate = st.number_input("Marginal Tax Rate (%)", min_value=0.0, max_value=50.0, step=1.0)

    months = int(tenure_years * 12)

    if principal <= 0:
        st.warning("Enter your mortgage details to begin.")
        return

    st.divider()

    # -------------------------------
    # BASE amortization
    # -------------------------------
    df_base = amortization_table(principal, annual_rate, months, extra_payment=0)
    total_interest_base = df_base["Interest"].sum()

    # -------------------------------
    # With extra payment
    # -------------------------------
    df_extra = amortization_table(principal, annual_rate, months, extra_payment=extra_payment)
    total_interest_extra = df_extra["Interest"].sum()

    months_saved = len(df_base) - len(df_extra)
    interest_saved = total_interest_base - total_interest_extra

    # -------------------------------
    # Tax savings
    # -------------------------------
    tax_saved, standard_ded, deductible_interest = tax_savings_from_interest(
        total_interest_extra, filing_status, dependents, marginal_rate
    )

    effective_interest_cost = total_interest_extra - tax_saved
    effective_interest_rate = (effective_interest_cost / principal) / tenure_years * 100

    # -------------------------------
    # Summary Cards
    # -------------------------------
    st.subheader("Summary")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Monthly EMI", fmt(calculate_emi(principal, annual_rate, months), currency))
    c2.metric("Total Interest", fmt(total_interest_extra, currency))
    c3.metric("Tax Savings", fmt(tax_saved, currency))
    c4.metric("Effective Interest Rate", f"{effective_interest_rate:.2f}%")

    st.divider()

    # -------------------------------
    # Tenure + interest savings
    # -------------------------------
    st.subheader("Impact of Extra Payment")
    st.write(f"**Months Saved:** {months_saved}")
    st.write(f"**Interest Saved:** {fmt(interest_saved, currency)}")

    st.divider()

    # -------------------------------
    # Amortization tables
    # -------------------------------
    tab1, tab2 = st.tabs(["📄 Amortization (Base)", "📄 With Extra Payment"])

    with tab1:
        st.dataframe(df_base, height=400)
        csv = df_base.to_csv(index=False)
        st.download_button("Download CSV", csv, "amortization_base.csv")

    with tab2:
        st.dataframe(df_extra, height=400)
        csv = df_extra.to_csv(index=False)
        st.download_button("Download CSV", csv, "amortization_extra.csv")

    st.divider()

    # -------------------------------
    # Excel download (combined)
    # -------------------------------
    df_extra["Type"] = "With Extra Payment"
    df_base["Type"] = "Base"
    df_merge = pd.concat([df_base, df_extra])

    excel_bytes = to_excel_bytes(df_merge, sheet_name="Mortgage")
    st.download_button("Download Excel (Full Data)", excel_bytes, "mortgage_full.xlsx")

    st.success("Your mortgage plan is ready.")


# ---------------------------------------------------------------
# Run the app
# ---------------------------------------------------------------
if __name__ == "__main__":
    main()
