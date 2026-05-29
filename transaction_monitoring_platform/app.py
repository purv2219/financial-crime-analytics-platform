# app.py
# Transaction Monitoring Dashboard
# Purv Savalia
#
# Uses the PaySim dataset from Kaggle (ealaxi/paysim1).
# PaySim simulates mobile money transactions with injected fraud patterns.
# Run: python -m streamlit run app.py

import os
import sqlite3
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from data_loader import build_database, DB_PATH
from rule_engine import flag_transactions, get_rule_performance, RULES, run_all_rules

st.set_page_config(
    page_title="Transaction Monitoring Dashboard",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    [data-testid="stAppViewContainer"] { background: #0f1117; }
    [data-testid="stSidebar"]          { background: #1a1d27; border-right: 1px solid #2d2f3e; }

    .page-title { font-size: 1.7rem; font-weight: 700; color: #e8eaf6; margin-bottom: 0.2rem; }
    .page-sub   { color: #8c8fa8; font-size: 0.85rem; margin-bottom: 1.2rem; }

    div[data-testid="stMetric"] {
        background: #1a1d27;
        border: 1px solid #2d2f3e;
        border-radius: 8px;
        padding: 0.9rem 1.1rem;
    }
    div[data-testid="stMetric"] label {
        color: #8c8fa8 !important;
        font-size: 0.75rem !important;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] { color: #e8eaf6 !important; }
    h2, h3 { color: #c5c8e8 !important; }
    .stSelectbox label, .stMultiSelect label, .stNumberInput label { color: #8c8fa8 !important; }
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------
# Database init — builds once, cached for the session
# ------------------------------------------------------------------
@st.cache_resource(show_spinner="Loading transaction database...")
def init_db():
    if not os.path.exists(DB_PATH):
        build_database()
    return DB_PATH


@st.cache_data(ttl=300)
def load_kpis(db_path):
    conn = sqlite3.connect(db_path)
    total   = pd.read_sql("SELECT COUNT(*) AS n FROM transactions", conn).iloc[0, 0]
    flagged = pd.read_sql("SELECT COUNT(*) AS n FROM transactions WHERE is_flagged=1", conn).iloc[0, 0]
    fraud   = pd.read_sql("SELECT COUNT(*) AS n FROM transactions WHERE isFraud=1", conn).iloc[0, 0]
    vol     = pd.read_sql("SELECT SUM(amount) AS s FROM transactions", conn).iloc[0, 0]
    conn.close()
    return int(total), int(flagged), int(fraud), float(vol or 0)


@st.cache_data(ttl=300)
def load_transactions(db_path):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT txn_id, txn_type, amount, account_orig, account_dest,
               oldbalanceOrg, newbalanceOrig, oldbalanceDest, newbalanceDest,
               isFraud, is_flagged, txn_date, txn_hour, txn_month, balance_drop, amount_bucket
        FROM transactions
    """, conn)
    conn.close()
    df["txn_date"] = pd.to_datetime(df["txn_date"])
    return df


# ------------------------------------------------------------------
# Run detection rules once on first load
# ------------------------------------------------------------------
db_path = init_db()

if "rules_run" not in st.session_state:
    with st.spinner("Running detection rules..."):
        st.session_state["rule_result"] = flag_transactions(db_path)
        load_kpis.clear()
    st.session_state["rules_run"] = True

rule_res   = st.session_state.get("rule_result", {})
flagged_df = rule_res.get("flagged_df", pd.DataFrame())


# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Transaction Monitoring")
    st.caption("AML / Financial Crime Detection")
    st.markdown("---")

    page = st.radio("Go to", [
        "Overview",
        "Alert Explorer",
        "Rule Performance",
        "Account Lookup",
        "Reports",
    ], label_visibility="collapsed")

    st.markdown("---")
    if st.button("Re-run Detection Rules", use_container_width=True):
        with st.spinner("Running rules..."):
            st.session_state["rule_result"] = flag_transactions(db_path)
            load_kpis.clear()
            load_transactions.clear()
        st.success("Done.")
        st.rerun()

    st.markdown("---")
    st.caption("Dataset: PaySim (Kaggle)")
    st.caption(f"Rules loaded: {len(RULES)}")
    st.caption(f"Last run: {datetime.now().strftime('%H:%M:%S')}")

    with st.expander("About the dataset"):
        st.markdown("""
**PaySim** is a synthetic mobile money transaction simulator
built for fraud detection research.

- Source: [Kaggle — ealaxi/paysim1](https://www.kaggle.com/datasets/ealaxi/paysim1)
- Paper: Lopez-Rojas et al. (2016)
- Full dataset: ~6.3M transactions over 30 simulated days
- Fraud labels (`isFraud`) are ground truth from the simulator
- Fraud only occurs in TRANSFER and CASH_OUT transactions

**Why PaySim?**
It's the most widely cited open-source transaction dataset for
AML/fraud detection research and uses realistic behavioral patterns.

**Limitations:**
- No customer KYC or demographic data
- No geographic / country information
- Rules are deterministic, not ML-based
- Fraud labels come from the simulator, not real investigators
        """)


# ------------------------------------------------------------------
# Load data
# ------------------------------------------------------------------
total_tx, total_flagged, total_fraud, total_vol = load_kpis(db_path)
df_tx = load_transactions(db_path)

# detection efficiency: fraction of actual fraud caught by the rules
# calculated from the data, not hardcoded
perf_data = get_rule_performance(db_path)
if not perf_data.empty and total_fraud > 0:
    fraud_caught = int(perf_data["true_positives"].sum())
    detection_efficiency = round(fraud_caught / total_fraud * 100, 1)
else:
    fraud_caught = 0
    detection_efficiency = 0.0


# ==================================================================
# PAGE 1 — OVERVIEW
# ==================================================================
if page == "Overview":
    st.markdown('<div class="page-title">Overview</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Summary of transaction volume, flagged activity, and fraud detection results.</div>', unsafe_allow_html=True)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    alert_rate = round(total_flagged / total_tx * 100, 2) if total_tx else 0
    fraud_rate = round(total_fraud  / total_tx * 100, 3) if total_tx else 0

    c1.metric("Transactions",      f"{total_tx:,}")
    c2.metric("Total Volume",      f"${total_vol/1e9:.2f}B")
    c3.metric("Alerts",            f"{total_flagged:,}")
    c4.metric("Confirmed Fraud",   f"{total_fraud:,}")
    c5.metric("Fraud Rate",        f"{fraud_rate}%")
    # % of confirmed fraud transactions that at least one rule flagged
    c6.metric("Fraud Caught by Rules", f"{detection_efficiency}%")

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Transactions Per Day")
        daily = (df_tx.groupby("txn_date")
                 .agg(count=("txn_id","count"),
                      flagged=("is_flagged","sum"),
                      fraud=("isFraud","sum"))
                 .reset_index())
        fig = px.area(daily, x="txn_date", y="count",
                      color_discrete_sequence=["#7c83fd"],
                      labels={"count":"Count","txn_date":"Date"})
        fig.add_scatter(x=daily["txn_date"], y=daily["flagged"],
                        mode="lines", name="Flagged",
                        line=dict(color="#ff6b6b", width=2))
        fig.add_scatter(x=daily["txn_date"], y=daily["fraud"],
                        mode="lines", name="Confirmed Fraud",
                        line=dict(color="#ff0000", width=1.5, dash="dot"))
        fig.update_layout(height=300, plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
                          font_color="#8c8fa8", margin=dict(l=0,r=0,t=10,b=0))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Transaction Volume by Type")
        by_type = (df_tx.groupby("txn_type")["amount"]
                   .sum().reset_index()
                   .rename(columns={"amount":"total"})
                   .sort_values("total"))
        fig2 = px.bar(by_type, x="total", y="txn_type", orientation="h",
                      color="txn_type",
                      color_discrete_sequence=["#7c83fd","#ff6b6b","#4ecdc4","#ffd166","#06d6a0"],
                      labels={"total":"Total Amount (USD)","txn_type":""})
        fig2.update_layout(height=300, showlegend=False,
                           plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
                           font_color="#8c8fa8", margin=dict(l=0,r=0,t=10,b=0))
        st.plotly_chart(fig2, use_container_width=True)

    col3, col4 = st.columns(2)

    with col3:
        st.subheader("Where Fraud Occurs (by Transaction Type)")
        fraud_by_type = (df_tx[df_tx["isFraud"]==1]["txn_type"]
                         .value_counts().reset_index())
        fraud_by_type.columns = ["type","count"]
        if fraud_by_type.empty:
            st.info("No fraud transactions in current dataset.")
        else:
            fig3 = px.pie(fraud_by_type, names="type", values="count", hole=0.4,
                          color_discrete_sequence=["#7c83fd","#ff6b6b","#4ecdc4","#ffd166","#06d6a0"])
            fig3.update_layout(height=300, plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
                               font_color="#8c8fa8", margin=dict(l=0,r=0,t=10,b=0))
            st.plotly_chart(fig3, use_container_width=True)

    with col4:
        st.subheader("Alerts by Severity")
        if not flagged_df.empty and "severity" in flagged_df.columns:
            sev = flagged_df["severity"].value_counts().reset_index()
            sev.columns = ["severity","count"]
            colors = {"CRITICAL":"#b71c1c","HIGH":"#bf360c","MEDIUM":"#e65100"}
            fig4 = px.pie(sev, names="severity", values="count", hole=0.4,
                          color="severity", color_discrete_map=colors)
            fig4.update_layout(height=300, plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
                               font_color="#8c8fa8", margin=dict(l=0,r=0,t=10,b=0))
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info("No alerts yet.")

    st.markdown("---")
    st.subheader("Alerts per Rule")
    if rule_res.get("per_rule"):
        tbl = pd.DataFrame([
            {"Rule": rid, "Description": v["name"], "Severity": v["severity"], "Alerts": v["hits"]}
            for rid, v in rule_res["per_rule"].items()
        ]).sort_values("Alerts", ascending=False)
        max_hits = int(tbl["Alerts"].max()) or 1
        st.dataframe(tbl, use_container_width=True, hide_index=True,
                     column_config={"Alerts": st.column_config.ProgressColumn(
                         min_value=0, max_value=max_hits)})


# ==================================================================
# PAGE 2 — ALERT EXPLORER
# ==================================================================
elif page == "Alert Explorer":
    st.markdown('<div class="page-title">Alert Explorer</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Filter and review flagged transactions. Export for further investigation.</div>', unsafe_allow_html=True)
    st.markdown("---")

    if flagged_df.empty:
        st.warning("No alerts found. Click 'Re-run Detection Rules' in the sidebar.")
    else:
        f1, f2, f3 = st.columns(3)
        with f1:
            sev_f = st.multiselect("Severity", ["CRITICAL","HIGH","MEDIUM"],
                                   default=["CRITICAL","HIGH","MEDIUM"])
        with f2:
            rule_f = st.multiselect("Rule", list(RULES.keys()),
                                    default=list(RULES.keys()))
        with f3:
            min_amt = st.number_input("Min Amount ($)", value=0, step=10_000)

        filt = flagged_df.copy()
        if "severity" in filt.columns:
            filt = filt[filt["severity"].isin(sev_f)]
        if "rule_id" in filt.columns:
            filt = filt[filt["rule_id"].isin(rule_f)]
        if "amount" in filt.columns:
            filt = filt[filt["amount"] >= min_amt]

        st.write(f"{len(filt):,} alerts match current filters")

        show_cols = [c for c in ["transaction_id","customer_id","amount","date",
                                  "transaction_type","rule_id","rule_name","severity"]
                     if c in filt.columns]
        st.dataframe(filt[show_cols].sort_values("amount", ascending=False).head(500),
                     use_container_width=True, hide_index=True)

        st.download_button("Export to CSV", filt.to_csv(index=False),
                           "alerts_export.csv", "text/csv")


# ==================================================================
# PAGE 3 — RULE PERFORMANCE
# ==================================================================
elif page == "Rule Performance":
    st.markdown('<div class="page-title">Rule Performance</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Precision and recall for each detection rule, measured against PaySim fraud labels.</div>', unsafe_allow_html=True)
    st.markdown("---")

    perf = get_rule_performance(db_path)

    if perf.empty:
        st.info("Run detection rules first.")
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Alerts",    f"{perf['total_alerts'].sum():,}")
        k2.metric("True Positives",  f"{perf['true_positives'].sum():,}")
        k3.metric("False Positives", f"{perf['false_positives'].sum():,}")
        k4.metric("Avg Precision",   f"{perf['precision_pct'].mean():.1f}%")

        st.markdown("---")
        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Precision per Rule")
            fig_p = px.bar(perf, x="rule_name", y="precision_pct",
                           color="severity",
                           color_discrete_map={"CRITICAL":"#b71c1c","HIGH":"#bf360c","MEDIUM":"#e65100"},
                           labels={"precision_pct":"Precision (%)","rule_name":""},
                           text="precision_pct")
            fig_p.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig_p.update_layout(height=370, xaxis_tickangle=-20, showlegend=False,
                                plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
                                font_color="#8c8fa8", margin=dict(l=0,r=0,t=20,b=0))
            st.plotly_chart(fig_p, use_container_width=True)

        with col_b:
            st.subheader("True vs False Positives")
            fig_tp = go.Figure()
            fig_tp.add_trace(go.Bar(name="True Positives",
                                    x=perf["rule_name"], y=perf["true_positives"],
                                    marker_color="#06d6a0"))
            fig_tp.add_trace(go.Bar(name="False Positives",
                                    x=perf["rule_name"], y=perf["false_positives"],
                                    marker_color="#ff6b6b"))
            fig_tp.update_layout(barmode="stack", height=370, xaxis_tickangle=-20,
                                  plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
                                  font_color="#8c8fa8", margin=dict(l=0,r=0,t=20,b=0))
            st.plotly_chart(fig_tp, use_container_width=True)

        st.subheader("Full Results Table")
        st.dataframe(perf, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("Rule Logic (SQL)")
        st.caption("Each rule is a SQL query run against the transactions table.")
        for rid, meta in RULES.items():
            with st.expander(f"{rid} — {meta['name']}"):
                st.markdown(f"**What it detects:** {meta['description']}")
                st.code(meta["sql"].strip(), language="sql")


# ==================================================================
# PAGE 4 — ACCOUNT LOOKUP
# ==================================================================
elif page == "Account Lookup":
    st.markdown('<div class="page-title">Account Lookup</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">View all transactions for a specific account and check for flagged activity.</div>', unsafe_allow_html=True)
    st.markdown("---")

    # default to the account with the most alerts
    if not flagged_df.empty and "customer_id" in flagged_df.columns:
        top_accts = (flagged_df.groupby("customer_id").size()
                     .sort_values(ascending=False).index.tolist())
        default_acct = top_accts[0] if top_accts else df_tx["account_orig"].iloc[0]
    else:
        default_acct = df_tx["account_orig"].iloc[0]

    acct_id = st.text_input("Account ID", value=default_acct)
    acct_tx = df_tx[df_tx["account_orig"] == acct_id]

    if acct_tx.empty:
        st.warning(f"No transactions found for account: {acct_id}")
    else:
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Transactions",    f"{len(acct_tx):,}")
        a2.metric("Total Volume",    f"${acct_tx['amount'].sum():,.0f}")
        a3.metric("Flagged",         f"{int(acct_tx['is_flagged'].sum())}")
        a4.metric("Fraud (labeled)", f"{int(acct_tx['isFraud'].sum())}")

        st.markdown("---")
        ch1, ch2 = st.columns(2)

        with ch1:
            st.subheader("Transaction History")
            fig_h = px.scatter(acct_tx, x="txn_date", y="amount",
                               color="txn_type", size_max=10,
                               labels={"amount":"Amount","txn_date":"Date","txn_type":"Type"})
            fig_h.update_layout(height=290, plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
                                font_color="#8c8fa8", margin=dict(l=0,r=0,t=10,b=0))
            st.plotly_chart(fig_h, use_container_width=True)

        with ch2:
            st.subheader("Balance Over Time")
            # shows how the account balance changed across transactions
            sorted_tx = acct_tx.sort_values("txn_date")
            fig_b = px.line(sorted_tx, x="txn_date",
                            y=["oldbalanceOrg","newbalanceOrig"],
                            labels={"value":"Balance (USD)","txn_date":"Date"},
                            color_discrete_sequence=["#7c83fd","#ff6b6b"])
            fig_b.update_layout(height=290, plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
                                font_color="#8c8fa8", margin=dict(l=0,r=0,t=10,b=0))
            st.plotly_chart(fig_b, use_container_width=True)

        st.subheader("Transaction List")
        st.dataframe(acct_tx.sort_values("txn_date", ascending=False),
                     use_container_width=True, hide_index=True)


# ==================================================================
# PAGE 5 — REPORTS
# ==================================================================
elif page == "Reports":
    st.markdown('<div class="page-title">Reports</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Compliance reporting and monitoring summaries.</div>', unsafe_allow_html=True)
    st.markdown("---")

    report = st.selectbox("Select report", [
        "High-Priority Alerts",
        "Monthly Summary",
        "Rule Coverage",
        "Fraud Breakdown",
    ])

    # ── High-priority alerts ──────────────────────────────────────────────────
    if report == "High-Priority Alerts":
        st.subheader("High-Priority Alerts")
        st.caption("CRITICAL and HIGH severity alerts — these are candidates for manual review.")

        if not flagged_df.empty and "severity" in flagged_df.columns:
            high_pri = flagged_df[flagged_df["severity"].isin(["CRITICAL","HIGH"])]
            st.write(f"{len(high_pri):,} high-priority alerts")
            st.dataframe(high_pri, use_container_width=True, hide_index=True)
            st.download_button("Export CSV", high_pri.to_csv(index=False),
                               "high_priority_alerts.csv", "text/csv")
        else:
            st.info("No alerts found. Run detection rules first.")

    # ── Monthly summary ───────────────────────────────────────────────────────
    elif report == "Monthly Summary":
        st.subheader("Monthly Transaction Summary")

        monthly = (df_tx.groupby("txn_month")
                   .agg(tx_count    = ("txn_id",   "count"),
                        total_vol   = ("amount",   "sum"),
                        flagged     = ("is_flagged","sum"),
                        fraud       = ("isFraud",  "sum"))
                   .reset_index())
        monthly["flag_rate_%"]  = (monthly["flagged"] / monthly["tx_count"] * 100).round(2)
        monthly["fraud_rate_%"] = (monthly["fraud"]   / monthly["tx_count"] * 100).round(3)
        st.dataframe(monthly, use_container_width=True, hide_index=True)

        fig_m = px.line(monthly, x="txn_month", y=["flagged","fraud"],
                        markers=True,
                        color_discrete_sequence=["#ff6b6b","#b71c1c"],
                        labels={"value":"Count","txn_month":"Month","variable":"Series"})
        fig_m.update_layout(height=290, plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
                            font_color="#8c8fa8", margin=dict(l=0,r=0,t=10,b=0))
        st.plotly_chart(fig_m, use_container_width=True)

    # ── Rule coverage ─────────────────────────────────────────────────────────
    elif report == "Rule Coverage":
        st.subheader("Rule Coverage Analysis")

        # these numbers come from the actual rule results, not hardcoded
        active_rules  = sum(1 for v in rule_res.get("per_rule", {}).values() if v["hits"] > 0)
        total_rules   = len(RULES)
        known_gaps    = 3  # cross-border, shell company, trade finance — not in PaySim

        g1, g2, g3 = st.columns(3)
        g1.metric("Rules with Hits",  f"{active_rules} / {total_rules}")
        g2.metric("Known Gaps",       str(known_gaps))
        g3.metric("Fraud Caught",     f"{detection_efficiency}%")

        st.markdown("---")

        # coverage table — only shows what the code actually knows
        coverage_rows = []
        for rid, meta in RULES.items():
            hits = rule_res.get("per_rule", {}).get(rid, {}).get("hits", 0)
            coverage_rows.append({
                "Rule":       rid,
                "Description": meta["name"],
                "Severity":   meta["severity"],
                "Alerts":     hits,
                "Active":     "Yes" if hits > 0 else "No hits yet",
            })

        # add known gaps — things PaySim can't test
        gaps = [
            {"Rule": "—", "Description": "Cross-border transfers",
             "Severity": "HIGH", "Alerts": "—",
             "Active": "Gap — PaySim has no country data"},
            {"Rule": "—", "Description": "Shell company / business front detection",
             "Severity": "HIGH", "Alerts": "—",
             "Active": "Gap — requires business registry data"},
            {"Rule": "—", "Description": "Trade-based money laundering",
             "Severity": "MEDIUM", "Alerts": "—",
             "Active": "Gap — requires invoice / trade data"},
        ]
        coverage_df = pd.DataFrame(coverage_rows + gaps)
        st.dataframe(coverage_df, use_container_width=True, hide_index=True)

        st.info("""
**Dataset limitations that affect coverage:**
- PaySim does not include country or geographic data, so cross-border detection cannot be tested here.
- There is no KYC or customer profile data in PaySim.
- Rules are deterministic SQL queries. No machine learning is used.
- Precision numbers are measured against PaySim's simulated fraud labels, not real investigator decisions.
        """)
        st.download_button("Export Coverage Table", coverage_df.to_csv(index=False),
                           "rule_coverage.csv", "text/csv")

    # ── Fraud breakdown ───────────────────────────────────────────────────────
    elif report == "Fraud Breakdown":
        st.subheader("Fraud Breakdown")
        st.caption("Based on PaySim ground-truth fraud labels.")

        fraud_df = df_tx[df_tx["isFraud"] == 1]

        if fraud_df.empty:
            st.info("No fraud transactions in current dataset.")
        else:
            st.write(f"{len(fraud_df):,} fraud transactions out of {total_tx:,} total ({fraud_rate:.3f}%)")

            fc1, fc2 = st.columns(2)
            with fc1:
                st.subheader("By Transaction Type")
                ft = fraud_df["txn_type"].value_counts().reset_index()
                ft.columns = ["type","count"]
                fig_ft = px.bar(ft, x="type", y="count",
                                color_discrete_sequence=["#b71c1c"],
                                labels={"count":"Count","type":"Type"})
                fig_ft.update_layout(height=260, plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
                                     font_color="#8c8fa8", margin=dict(l=0,r=0,t=10,b=0))
                st.plotly_chart(fig_ft, use_container_width=True)

            with fc2:
                st.subheader("By Amount Range")
                fa = fraud_df["amount_bucket"].value_counts().reset_index()
                fa.columns = ["range","count"]
                fig_fa = px.bar(fa, x="range", y="count",
                                color_discrete_sequence=["#ff6b6b"],
                                labels={"count":"Count","range":"Amount Range"})
                fig_fa.update_layout(height=260, plot_bgcolor="#0f1117", paper_bgcolor="#0f1117",
                                     font_color="#8c8fa8", margin=dict(l=0,r=0,t=10,b=0))
                st.plotly_chart(fig_fa, use_container_width=True)

            st.dataframe(fraud_df.head(300), use_container_width=True, hide_index=True)
            st.download_button("Export Fraud Records",
                               fraud_df.to_csv(index=False), "fraud_records.csv", "text/csv")
