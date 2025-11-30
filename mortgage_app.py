# mortgage_app.py
import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO

# ---------------------------
# Reset session state so every new visitor gets fresh fields
# ---------------------------
if "initialized" not in st.session_state:
    st.session_state.clear()
    st.session_state["lump_events"] = []  # list of {"amount": float, "month": int}
    st.session_state["initialized"] = True

st.set_page_config(page_title="Mortgage vs Invest Planner (2025) — Multiple Lump Sums + PV", layout="wide", page_icon="🏦")

# ---------------------------
# Helpers / formatters / io
# ---------------------------
def fmt_usd(x):
    try:
        return f"${float(x):,.2f}"
    except:
        return str(x)

def fmt_pct(x):
    try:
        return f"{x:.2f}%"
    except:
        return str(x)

def to_excel_bytes(df, sheet_name="Sheet1"):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return out.getvalue()

# ---------------------------
# 2025 standard deductions (final)
# ---------------------------
STANDARD_DEDUCTION_2025 = {
    "Single": 15750.0,
    "Married Filing Separately": 15750.0,
    "Head of Household": 23625.0,
    "Married Filing Jointly": 31500.0,
    "Surviving Spouses": 31500.0,
}

# ---------------------------
# 2025 federal tax brackets (cutpoints)
# ---------------------------
FEDERAL_BRACKETS_2025 = {
    "Single": [
        (0, 11925, 0.10),
        (11925, 48475, 0.12),
        (48475, 103350, 0.22),
        (103350, 197300, 0.24),
        (197300, 250525, 0.32),
        (250525, 626350, 0.35),
        (626350, float("inf"), 0.37),
    ],
    "Married Filing Jointly": [
        (0, 23850, 0.10),
        (23850, 96950, 0.12),
        (96950, 206700, 0.22),
        (206700, 394600, 0.24),
        (394600, 501050, 0.32),
        (501050, 751600, 0.35),
        (751600, float("inf"), 0.37),
    ],
    "Married Filing Separately": [
        (0, 11925, 0.10),
        (11925, 48475, 0.12),
        (48475, 103350, 0.22),
        (103350, 197300, 0.24),
        (197300, 250525, 0.32),
        (250525, 626350, 0.35),
        (626350, float("inf"), 0.37),
    ],
    "Head of Household": [
        (0, 17000, 0.10),
        (17000, 64850, 0.12),
        (64850, 103350, 0.22),
        (103350, 197300, 0.24),
        (197300, 250500, 0.32),
        (250500, 626350, 0.35),
        (626350, float("inf"), 0.37),
    ],
    "Surviving Spouses": [
        (0, 23850, 0.10),
        (23850, 96950, 0.12),
        (96950, 206700, 0.22),
        (206700, 394600, 0.24),
        (394600, 501050, 0.32),
        (501050, 751600, 0.35),
        (751600, float("inf"), 0.37),
    ],
}

# ---------------------------
# Tax engine: progressive federal tax
# ---------------------------
def compute_progressive_tax(taxable_income, filing_status):
    if taxable_income <= 0:
        return 0.0
    tax = 0.0
    for low, high, rate in FEDERAL_BRACKETS_2025[filing_status]:
        if taxable_income > low:
            taxed = min(taxable_income, high) - low
            if taxed > 0:
                tax += taxed * rate
        else:
            break
    return tax

# ---------------------------
# Mortgage math & amortization
# ---------------------------
def compute_emi(P, annual_rate_pct, n_months):
    r = annual_rate_pct / 100.0 / 12.0
    if n_months <= 0:
        return 0.0
    if r == 0:
        return P / n_months
    powv = (1 + r) ** n_months
    return P * r * powv / (powv - 1)

def amortization_schedule(P, annual_rate_pct, n_months, extra_monthly=0.0):
    monthly_r = annual_rate_pct / 100.0 / 12.0
    base_emi = compute_emi(P, annual_rate_pct, n_months)
    balance = float(P)
    month = 0
    rows = []
    cap = max(n_months * 10, 1200)
    while balance > 0.005 and month < cap:
        month += 1
        interest = balance * monthly_r
        principal_base = base_emi - interest
        if principal_base < 0:
            principal_base = 0.0
        extra = min(extra_monthly, max(0.0, balance - principal_base))
        payment = base_emi + extra
        if principal_base + extra >= balance - 1e-9:
            principal_paid = balance
            payment = interest + principal_paid
            balance = 0.0
            rows.append([month, round(base_emi,2), round(interest,2), round(principal_paid,2), round(extra,2), round(payment,2), round(balance,2)])
            break
        else:
            principal_paid = principal_base + extra
            balance -= principal_paid
            rows.append([month, round(base_emi,2), round(interest,2), round(principal_base,2), round(extra,2), round(payment,2), round(balance,2)])
    return pd.DataFrame(rows, columns=["Month","BaseEMI","Interest","PrincipalBase","ExtraPayment","TotalPayment","Balance"])

# ---------------------------
# Apply multiple lump sums (apply AFTER that month's EMI) and re-simulate
# ---------------------------
def apply_multiple_lumps_and_resimulate(P, annual_rate_pct, n_months, lumps, extra_monthly=0.0):
    """
    lumps: list of {"amount":float, "month":int}
    We apply each lump after the scheduled payment in the specified month.
    EMI is kept constant; tenure will shorten.
    Returns new amortization DataFrame.
    """
    if not lumps:
        return amortization_schedule(P, annual_rate_pct, n_months, extra_monthly=extra_monthly)
    # sort lumps by month ascending
    lumps_sorted = sorted(lumps, key=lambda x: int(x["month"]))
    monthly_r = annual_rate_pct / 100.0 / 12.0
    base_emi = compute_emi(P, annual_rate_pct, n_months)
    balance = float(P)
    month = 0
    rows = []
    cap = max(n_months * 10, 1200)
    lump_idx = 0
    while balance > 0.005 and month < cap:
        month += 1
        interest = balance * monthly_r
        principal_base = base_emi - interest
        if principal_base < 0:
            principal_base = 0.0
        extra = 0.0  # we'll apply recurring extra after all lumps if provided (extra_monthly applied after lumps in this model)
        # regular payment
        if principal_base >= balance:
            principal_paid = balance
            payment = interest + principal_paid
            balance = 0.0
            rows.append([month, round(base_emi,2), round(interest,2), round(principal_paid,2), round(extra,2), round(payment,2), round(balance,2)])
            break
        else:
            payment = base_emi
            balance -= principal_base
            rows.append([month, round(base_emi,2), round(interest,2), round(principal_base,2), round(extra,2), round(payment,2), round(balance,2)])
        # apply any lumps scheduled for this month (there could be multiple entries with same month)
        while lump_idx < len(lumps_sorted) and int(lumps_sorted[lump_idx]["month"]) == month:
            applied = min(float(lumps_sorted[lump_idx]["amount"]), balance)
            balance -= applied
            lump_idx += 1
            # if loan paid off by lump
            if balance <= 0.005:
                month += 1
                rows.append([month, 0.0, 0.0, round(0.0,2), round(0.0,2), round(0.0,2), round(0.0,2)])
                break
    # continue amortization with extra_monthly if still outstanding
    if balance > 0.005 and month < cap:
        while balance > 0.005 and month < cap:
            month += 1
            interest = balance * monthly_r
            principal_base = base_emi - interest
            if principal_base < 0:
                principal_base = 0.0
            extra = min(extra_monthly, max(0.0, balance - principal_base)) if extra_monthly > 0 else 0.0
            if principal_base + extra >= balance - 1e-9:
                principal_paid = balance
                payment = interest + principal_paid
                balance = 0.0
                rows.append([month, round(base_emi,2), round(interest,2), round(principal_paid,2), round(extra,2), round(payment,2), round(balance,2)])
                break
            else:
                principal_paid = principal_base + extra
                balance -= principal_paid
                rows.append([month, round(base_emi,2), round(interest,2), round(principal_base,2), round(extra,2), round(base_emi + extra,2), round(balance,2)])
    return pd.DataFrame(rows, columns=["Month","BaseEMI","Interest","PrincipalBase","ExtraPayment","TotalPayment","Balance"])

# ---------------------------
# Investment simulation: multiple lumps + monthly invest
# ---------------------------
def simulate_investment_multiple_lumps(lump_events, monthly_invest, annual_return_pct, invest_months):
    """
    lump_events: list of {"amount":float, "month":int}
    monthly_invest: monthly contribution amount (applied at end of month, starting at the earliest lump month if lumps exist, else start at month 1)
    annual_return_pct: percent
    invest_months: total months to simulate
    Returns final balance at invest_months.
    Assumptions:
    - Each lump event is invested at the END of its specified month (so it grows starting next period).
    - Monthly contributions are added at end of each month starting at first_lump_month (if lumps exist) else month 1.
    """
    r_month = (1 + annual_return_pct/100.0) ** (1/12.0) - 1.0
    balance = 0.0
    if lump_events:
        first_lump_month = min(int(e["month"]) for e in lump_events)
        start_monthly = first_lump_month
    else:
        start_monthly = 1
    # map lumps by month for quick add
    lumps_by_month = {}
    for e in lump_events:
        m = int(e["month"])
        lumps_by_month.setdefault(m, 0.0)
        lumps_by_month[m] += float(e["amount"])
    for m in range(1, invest_months + 1):
        # grow
        balance = balance * (1 + r_month)
        # add any lump scheduled this month
        if m in lumps_by_month and m <= invest_months:
            balance += lumps_by_month[m]
        # add monthly invest if month >= start_monthly
        if monthly_invest > 0 and m >= start_monthly:
            balance += monthly_invest
    return balance

# ---------------------------
# Tax savings calculator
# ---------------------------
def compute_annual_tax_savings(first_year_interest, income, filing_status, num_dependents, include_state, annual_property_tax, salt_cap=10000.0):
    std = STANDARD_DEDUCTION_2025.get(filing_status, 0.0)
    salt = min(annual_property_tax, salt_cap)
    itemized = first_year_interest + salt
    taxable_standard = max(0.0, income - std)
    taxable_itemized = max(0.0, income - itemized)
    tax_standard = compute_progressive_tax(taxable_standard, filing_status)
    tax_itemized = compute_progressive_tax(taxable_itemized, filing_status)
    CHILD_TAX_CREDIT = 2000.0
    credit = num_dependents * CHILD_TAX_CREDIT
    tax_after_standard = max(0.0, tax_standard - credit)
    tax_after_itemized = max(0.0, tax_itemized - credit)
    federal_savings = tax_after_standard - tax_after_itemized
    state_savings = 0.0
    total = max(0.0, federal_savings + state_savings)
    return total, federal_savings, state_savings

# ---------------------------
# UI - Layout and Inputs
# ---------------------------
left_col, right_col = st.columns([1, 2])

with left_col:
    st.markdown("## Mortgage inputs")
    home_price = st.number_input("Home price ($)", value=500000.0, step=1000.0, format="%.2f")
    down_payment = st.number_input("Down payment ($)", value=100000.0, step=1000.0, format="%.2f")
    remaining_loan = max(0.0, home_price - down_payment)
    annual_interest = st.number_input("Annual interest rate (%)", value=6.5, step=0.01, format="%.2f")
    remaining_years = st.number_input("Remaining tenure (years)", value=20, min_value=0, step=1)
    extra_monthly = st.number_input("Extra monthly payment (optional $)", value=0.0, step=50.0, format="%.2f")
    property_tax_rate = st.number_input("Property tax rate (%)", value=1.0, step=0.01, format="%.2f") / 100.0

    st.markdown("---")
    st.markdown("## Tax inputs (US, 2025)")
    filing_status = st.selectbox("Filing status (2025)", list(STANDARD_DEDUCTION_2025.keys()), index=3)
    income = st.number_input("Annual gross income ($)", value=150000.0, step=1000.0, format="%.2f")
    num_dependents = st.number_input("Number of dependents (children)", value=0, min_value=0, step=1)
    include_state = st.checkbox("Include state tax in SALT modeling (approx)", value=False)
    state_tax_rate = st.number_input("State tax rate (%) (if enabled)", value=5.0 if include_state else 0.0, step=0.1, format="%.2f") / 100.0 if include_state else 0.0
    salt_cap = st.number_input("SALT cap ($)", value=10000.0, step=100.0, format="%.2f")

    st.markdown("---")
    st.markdown("## Investment inputs (multiple lumps supported)")
    # Inputs for adding a new lump event
    new_lump_amount = st.number_input("New lump amount ($)", value=20000.0, step=100.0, format="%.2f", key="new_lump_amount")
    new_lump_month = st.number_input("New lump month (1 = now)", value=5, min_value=1, step=1, key="new_lump_month")
    col_add1, col_add2 = st.columns([1,1])
    with col_add1:
        if st.button("Add lump-sum"):
            st.session_state["lump_events"].append({"amount": float(new_lump_amount), "month": int(new_lump_month)})
    with col_add2:
        if st.button("Remove last lump"):
            if st.session_state["lump_events"]:
                st.session_state["lump_events"].pop()
    if st.button("Remove all lumps"):
        st.session_state["lump_events"] = []

    # Show current lumps
    st.write("### Current lump-sum events (applied AFTER that month's EMI):")
    if st.session_state["lump_events"]:
        df_lumps_display = pd.DataFrame(st.session_state["lump_events"])
        df_lumps_display.index = np.arange(1, len(df_lumps_display) + 1)
        st.dataframe(df_lumps_display.rename(columns={"amount":"Amount ($)", "month":"Month"}), use_container_width=True)
    else:
        st.write("_No lump-sum events added._")

    st.markdown("---")
    st.write("Monthly contribution (if investing instead):")
    monthly_invest = st.number_input("Monthly invest amount (optional $)", value=0.0, step=10.0, format="%.2f")
    annual_return = st.number_input("Expected annual return (%)", value=10.0, step=0.1, format="%.2f")
    invest_horizon_years = st.number_input("Investment horizon (years)", value=10, min_value=1, step=1)

with right_col:
    st.title("Mortgage — Analysis and Comparison (Multiple Lump Sums)")

    months = int(max(1, round(remaining_years * 12)))
    # Base schedule (no extra, no lumps)
    df_base = amortization_schedule(remaining_loan, annual_interest, months, extra_monthly=0.0)
    # With extra monthly payments
    df_extra = amortization_schedule(remaining_loan, annual_interest, months, extra_monthly=extra_monthly if extra_monthly>0 else 0.0)
    # With multiple lumps applied
    lumps = st.session_state["lump_events"]
    df_lump = apply_multiple_lumps_and_resimulate(remaining_loan, annual_interest, months, lumps, extra_monthly=extra_monthly if extra_monthly>0 else 0.0)

    # Totals
    total_interest_base = float(df_base["Interest"].sum()) if not df_base.empty else 0.0
    total_interest_extra = float(df_extra["Interest"].sum()) if not df_extra.empty else 0.0
    total_interest_lump = float(df_lump["Interest"].sum()) if not df_lump.empty else 0.0

    # First-year interest
    first_year_interest_base = float(df_base.loc[df_base["Month"] <= 12, "Interest"].sum()) if not df_base.empty else 0.0
    first_year_interest_lump = float(df_lump.loc[df_lump["Month"] <= 12, "Interest"].sum()) if not df_lump.empty else 0.0

    months_base = len(df_base)
    months_extra = len(df_extra)
    months_lump = len(df_lump)

    months_saved_by_extra = max(0, months_base - months_extra)
    months_saved_by_lump = max(0, months_base - months_lump)

    interest_saved_by_extra = max(0.0, total_interest_base - total_interest_extra)
    interest_saved_by_lump = max(0.0, total_interest_base - total_interest_lump)

    # Tax calculations
    annual_property_tax = home_price * property_tax_rate
    tax_savings_base, fed_s_base, st_s_base = compute_annual_tax_savings(first_year_interest_base, income, filing_status, num_dependents, include_state, annual_property_tax, salt_cap)
    tax_savings_lump, fed_s_lump, st_s_lump = compute_annual_tax_savings(first_year_interest_lump, income, filing_status, num_dependents, include_state, annual_property_tax, salt_cap)
    lost_tax_savings_due_to_lumps = max(0.0, tax_savings_base - tax_savings_lump)

    # Investment FV simulation (multiple lumps invested instead)
    invest_months = int(invest_horizon_years * 12)
    monthly_return = (1 + annual_return / 100.0) ** (1/12.0) - 1.0
    inv_final_value = simulate_investment_multiple_lumps(lumps, monthly_invest, annual_return, invest_months)

    # Net FV-based heuristic
    net_mortgage_benefit = interest_saved_by_lump - lost_tax_savings_due_to_lumps

    # Effective APR after tax (first-year)
    effective_first_year_interest_base = first_year_interest_base - tax_savings_base
    effective_rate_base_pct = (effective_first_year_interest_base / remaining_loan) * 100.0 if remaining_loan > 0 else 0.0
    effective_first_year_interest_lump = first_year_interest_lump - tax_savings_lump
    effective_rate_lump_pct = (effective_first_year_interest_lump / remaining_loan) * 100.0 if remaining_loan > 0 else 0.0

    # ---------------------------
    # PV calculations (Option A): discount monthly interest saved series and investment FV
    # ---------------------------
    max_months = max(len(df_base), len(df_lump))
    interest_base_series = np.zeros(max_months)
    interest_lump_series = np.zeros(max_months)
    for idx in range(max_months):
        m = idx + 1
        if m <= len(df_base):
            interest_base_series[idx] = float(df_base.loc[df_base["Month"] == m, "Interest"].values[0])
        if m <= len(df_lump):
            interest_lump_series[idx] = float(df_lump.loc[df_lump["Month"] == m, "Interest"].values[0])
    interest_saved_series = np.maximum(interest_base_series - interest_lump_series, 0.0)
    # discount factors: for month t (starting 1) factor = (1+monthly_return)^t
    discount_factors = (1 + monthly_return) ** np.arange(1, max_months + 1)
    npv_mortgage_interest_savings = float(np.sum(interest_saved_series / discount_factors))
    # PV of lost tax savings: treat lost tax savings as annual amount at year 1 (month 12)
    pv_lost_tax_savings = 0.0
    if lost_tax_savings_due_to_lumps > 0:
        pv_lost_tax_savings = lost_tax_savings_due_to_lumps / ((1 + monthly_return) ** 12)
    npv_mortgage_net = npv_mortgage_interest_savings - pv_lost_tax_savings
    # PV of investment: discount inv_final_value back invest_months
    pv_invest = inv_final_value / ((1 + monthly_return) ** invest_months) if invest_months > 0 else inv_final_value

    # ---------------------------
    # Summary cards
    # ---------------------------
    st.subheader("Quick Summary")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Base monthly EMI", fmt_usd(compute_emi(remaining_loan, annual_interest, months)))
        st.write("Loan amount")
        st.write(fmt_usd(remaining_loan))
    with c2:
        st.metric("First-year interest (base)", fmt_usd(first_year_interest_base))
        st.write("Annual property tax (est.)")
        st.write(fmt_usd(annual_property_tax))
    with c3:
        st.metric("Annual tax savings (base estimate)", fmt_usd(tax_savings_base))
        st.write("Deduction used")
        st.write("Itemized" if (first_year_interest_base + min(annual_property_tax, salt_cap)) > STANDARD_DEDUCTION_2025[filing_status] else "Standard")
    with c4:
        st.metric("Effective mortgage rate (base, 1st yr)", fmt_pct(effective_rate_base_pct))
        st.write("Effective (after lumps)", f"{fmt_pct(effective_rate_lump_pct)} (after lumps)")

    st.markdown("---")

    # ---------------------------
    # Comparison (FV and PV)
    # ---------------------------
    st.subheader("Lump-sum Prepay vs Invest — Comparison (FV and PV)")

    left, right = st.columns(2)
    with left:
        st.markdown("### Prepay (multiple lumps) — results")
        st.write(f"New payoff: **{months_lump} months** (saved {months_saved_by_lump} months)")
        st.write(f"Total interest with lumps: **{fmt_usd(total_interest_lump)}** (saved {fmt_usd(interest_saved_by_lump)} vs base)")
        st.write(f"Estimated annual tax savings after lumps: **{fmt_usd(tax_savings_lump)}**")
        st.write(f"Lost annual tax savings vs base: **{fmt_usd(lost_tax_savings_due_to_lumps)}**")
        st.write(f"Net mortgage benefit (FV heuristic): **{fmt_usd(net_mortgage_benefit)}**")
        st.markdown("**PV (discounted)**")
        st.write(f"NPV of monthly interest saved: **{fmt_usd(npv_mortgage_interest_savings)}**")
        st.write(f"PV of lost tax savings (approx): **{fmt_usd(pv_lost_tax_savings)}**")
        st.write(f"Net mortgage NPV: **{fmt_usd(npv_mortgage_net)}**")

    with right:
        st.markdown("### Invest instead — results")
        st.write(f"Investment horizon: **{invest_horizon_years} years ({invest_months} months)**")
        st.write(f"Future value of lumps + monthly invest (FV): **{fmt_usd(inv_final_value)}**")
        st.write(f"Present value (discounted using expected return): **{fmt_usd(pv_invest)}**")
        st.write(f"Discount rate used (annual): **{fmt_pct(annual_return)}**")
        st.write(f"Monthly discount: **{fmt_pct(monthly_return*100)}**")

    st.markdown("---")
    st.subheader("Recommendations (both FV and PV)")

    # FV recommendation (heuristic)
    if inv_final_value > net_mortgage_benefit:
        st.success(f"(FV) Investing outperforms prepaying by approx {fmt_usd(inv_final_value - net_mortgage_benefit)} (Investment FV − Net mortgage FV heuristic).")
    else:
        st.info(f"(FV) Prepaying outperforms investing by approx {fmt_usd(net_mortgage_benefit - inv_final_value)} (Net mortgage FV heuristic − Investment FV).")

    # PV recommendation (apples-to-apples)
    if pv_invest > npv_mortgage_net:
        st.success(f"(PV) Investing outperforms prepaying by approx {fmt_usd(pv_invest - npv_mortgage_net)} in present value terms.")
    else:
        st.info(f"(PV) Prepaying outperforms investing by approx {fmt_usd(npv_mortgage_net - pv_invest)} in present value terms.")

    st.markdown("---")
    st.caption("Notes: PV uses expected annual return as discount rate (converted to monthly). Tax treatment is simplified (first-year interest used as deduction proxy; child credit modeled simply). Lump sums are applied AFTER that month's EMI. For precise tax or legal advice consult a professional.")

    # ---------------------------
    # Balance chart
    # ---------------------------
    try:
        import altair as alt
        st.subheader("Balance comparison")
        max_m = max(len(df_base), len(df_extra), len(df_lump))
        months_idx = np.arange(1, max_m + 1)
        df_plot = pd.DataFrame({"Month": months_idx})
        df_plot = df_plot.merge(df_base[["Month","Balance"]].rename(columns={"Balance":"Base"}), on="Month", how="left")
        df_plot = df_plot.merge(df_extra[["Month","Balance"]].rename(columns={"Balance":"WithExtra"}), on="Month", how="left")
        df_plot = df_plot.merge(df_lump[["Month","Balance"]].rename(columns={"Balance":"WithLumps"}), on="Month", how="left")
        df_plot[["Base","WithExtra","WithLumps"]].ffill(inplace=True); df_plot[["Base","WithExtra","WithLumps"]].fillna(0,inplace=True)
        melt = df_plot.melt("Month", value_vars=["Base","WithExtra","WithLumps"], var_name="Scenario", value_name="Balance")
        chart = alt.Chart(melt).mark_line().encode(x="Month", y=alt.Y("Balance", title="Outstanding balance ($)"), color="Scenario").properties(height=420)
        st.altair_chart(chart, use_container_width=True)
    except Exception:
        st.info("Install altair to see the balance chart.")

    st.markdown("---")

    # ---------------------------
    # Amortization tables & downloads
    # ---------------------------
    st.subheader("Amortization schedules & downloads")
    t1, t2, t3 = st.tabs(["Base schedule","With extra monthly","With lumps"])

    with t1:
        if df_base.empty:
            st.write("No schedule")
        else:
            st.dataframe(df_base, use_container_width=True)
            st.download_button("Download base CSV", df_base.to_csv(index=False), "amortization_base.csv", "text/csv")
            st.download_button("Download base Excel", to_excel_bytes(df_base, "Base"), "amortization_base.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with t2:
        if df_extra.empty:
            st.write("No schedule")
        else:
            st.dataframe(df_extra, use_container_width=True)
            st.download_button("Download extra CSV", df_extra.to_csv(index=False), "amortization_extra.csv", "text/csv")
            st.download_button("Download extra Excel", to_excel_bytes(df_extra, "Extra"), "amortization_extra.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with t3:
        if df_lump.empty:
            st.write("No schedule")
        else:
            st.dataframe(df_lump, use_container_width=True)
            st.download_button("Download lumps CSV", df_lump.to_csv(index=False), "amortization_lumps.csv", "text/csv")
            st.download_button("Download lumps Excel", to_excel_bytes(df_lump, "Lumps"), "amortization_lumps.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.markdown("---")

    # ---------------------------
    # Yearly summary (base)
    # ---------------------------
    def yearly_summary(df):
        if df.empty:
            return pd.DataFrame()
        df2 = df.copy()
        df2["Year"] = ((df2["Month"] - 1) // 12) + 1
        agg = df2.groupby("Year").agg({
            "Interest":"sum","PrincipalBase":"sum","ExtraPayment":"sum","TotalPayment":"sum","Balance":"last"
        }).reset_index()
        return agg

    st.subheader("Yearly summary (Base)")
    ys = yearly_summary(df_base)
    if ys.empty:
        st.write("No data")
    else:
        st.dataframe(ys, use_container_width=True)
        st.download_button("Download yearly CSV", ys.to_csv(index=False), "yearly_summary.csv", "text/csv")

    st.markdown("---")

    # ---------------------------
    # Tax details
    # ---------------------------
    st.subheader("Tax details (estimates) — 2025")
    st.write(f"Filing status: **{filing_status}**")
    st.write(f"Annual income: **{fmt_usd(income)}**")
    st.write(f"First-year mortgage interest (base): **{fmt_usd(first_year_interest_base)}**")
    st.write(f"First-year mortgage interest (with lumps): **{fmt_usd(first_year_interest_lump)}**")
    st.write(f"Estimated annual tax savings (base): **{fmt_usd(tax_savings_base)}**")
    st.write(f"Estimated annual tax savings (with lumps): **{fmt_usd(tax_savings_lump)}**")
    st.write(f"Estimated lost tax savings by prepaying: **{fmt_usd(lost_tax_savings_due_to_lumps)}**")
    st.caption("Estimates only. For definitive tax advice, consult a tax professional.")

# End of file
