# rule_engine.py
# Purv Savalia — FinWatch AML Analytics Platform
#
# SQL-based AML detection rules designed around the PaySim transaction schema.
# Rules are based on FinCEN guidance, FATF typologies, and behavioral patterns
# documented in the PaySim research paper (Lopez-Rojas et al., 2016).
#
# I organized rules as a catalogue dict so adding, disabling, or threshold-tuning
# a single rule doesn't touch the runner logic at all. Makes it easy to A/B test
# different thresholds and document the reasoning behind each one.

import sqlite3
import pandas as pd

DEFAULT_DB = "finwatch.db"

# ------------------------------------------------------------------
# RULE CATALOGUE
# Each entry contains:
#   name        — short display name for dashboard
#   description — explanation of the pattern being detected
#   severity    — CRITICAL > HIGH > MEDIUM
#   sql         — detection query (returns transactions to flag)
#
# Column reference (PaySim schema + enriched columns):
#   txn_id, txn_type, amount, account_orig, account_dest
#   oldbalanceOrg, newbalanceOrig, oldbalanceDest, newbalanceDest
#   isFraud, isFlaggedFraud, txn_date, txn_hour, balance_drop
# ------------------------------------------------------------------

RULES = {

    "R001": {
        "name":        "Full Balance Drained on Transfer",
        "description": (
            "Account's entire balance transferred out in a single transaction "
            "(newbalanceOrig = 0 and oldbalanceOrg > 0). Classic fraud signature "
            "in the PaySim dataset — seen in both TRANSFER and CASH_OUT fraud cases."
        ),
        "severity": "CRITICAL",
        "sql": """
            SELECT
                txn_id          AS transaction_id,
                account_orig    AS customer_id,
                amount,
                txn_date        AS date,
                txn_type        AS transaction_type,
                'R001'          AS rule_id,
                'Full Balance Drained on Transfer' AS rule_name,
                'CRITICAL'      AS severity
            FROM transactions
            WHERE newbalanceOrig = 0
              AND oldbalanceOrg > 0
              AND txn_type IN ('TRANSFER', 'CASH_OUT')
              AND amount > 1000
        """,
    },

    "R002": {
        "name":        "Large Cash Withdrawal",
        "description": (
            "CASH_OUT transaction exceeding $200,000. Large cash withdrawals "
            "are a primary money laundering vector. The $200K threshold catches "
            "meaningful outliers without over-alerting on normal business activity."
        ),
        "severity": "HIGH",
        # Initial threshold was $100K. After running against PaySim I was getting a lot of alerts
        # on normal large transactions. Raised it to $200K and the false positive count dropped significantly.
        "sql": """
            SELECT
                txn_id          AS transaction_id,
                account_orig    AS customer_id,
                amount,
                txn_date        AS date,
                txn_type        AS transaction_type,
                'R002'          AS rule_id,
                'Large Cash Withdrawal' AS rule_name,
                'HIGH'          AS severity
            FROM transactions
            WHERE txn_type = 'CASH_OUT'
              AND amount > 200000
        """,
    },

    "R003": {
        "name":        "Large Transfer To Empty Destination Account",
        "description": (
            "Transfer over $100,000 to a destination account with zero prior balance. "
            "Suggests the destination is a newly opened or mule account — "
            "common in placement/layering schemes."
        ),
        "severity": "HIGH",
        "sql": """
            SELECT
                txn_id          AS transaction_id,
                account_orig    AS customer_id,
                amount,
                txn_date        AS date,
                txn_type        AS transaction_type,
                'R003'          AS rule_id,
                'Large Transfer To Empty Destination Account' AS rule_name,
                'HIGH'          AS severity
            FROM transactions
            WHERE txn_type = 'TRANSFER'
              AND oldbalanceDest = 0
              AND amount > 100000
        """,
    },

    "R004": {
        "name":        "Multiple Transfers Within One Hour",
        "description": (
            "Account making 3+ TRANSFER or CASH_OUT transactions in the same hour. "
            "Rapid sequential outflows indicate layering — moving funds quickly "
            "across multiple accounts to obscure the trail."
        ),
        "severity": "HIGH",
        # tried using a CTE first but SQLite had issues with it on larger row counts
        "sql": """
            SELECT
                t.txn_id        AS transaction_id,
                t.account_orig  AS customer_id,
                t.amount,
                t.txn_date      AS date,
                t.txn_type      AS transaction_type,
                'R004'          AS rule_id,
                'Multiple Transfers Within One Hour' AS rule_name,
                'HIGH'          AS severity
            FROM transactions t
            WHERE t.txn_type IN ('TRANSFER', 'CASH_OUT')
              AND t.account_orig IN (
                  SELECT account_orig
                  FROM transactions
                  WHERE txn_type IN ('TRANSFER', 'CASH_OUT')
                  GROUP BY account_orig, txn_date, txn_hour
                  HAVING COUNT(*) >= 3
              )
        """,
    },

    "R005": {
        "name":        "Transaction Amount Does Not Match Balance Change",
        "description": (
            "Transaction where the amount doesn't reconcile with the balance change. "
            "Specifically: oldbalanceOrg - amount != newbalanceOrig (with tolerance). "
            "In real systems this flags potential record tampering or processing errors."
        ),
        "severity": "MEDIUM",
        # there is floating point rounding in the dataset so need a small tolerance here
        "sql": """
            SELECT
                txn_id          AS transaction_id,
                account_orig    AS customer_id,
                amount,
                txn_date        AS date,
                txn_type        AS transaction_type,
                'R005'          AS rule_id,
                'Amount Does Not Match Balance Change' AS rule_name,
                'MEDIUM'        AS severity
            FROM transactions
            WHERE txn_type IN ('TRANSFER', 'CASH_OUT')
              AND ABS((oldbalanceOrg - amount) - newbalanceOrig) > 1
              AND oldbalanceOrg > 0
              AND newbalanceOrig > 0
              AND amount > 5000
        """,
    },

    "R006": {
        "name":        "Large Cash Withdrawal Between Midnight and 5am",
        "description": (
            "CASH_OUT over $50,000 occurring between midnight and 5 AM. "
            "Legitimate businesses rarely process large cash at these hours."
        ),
        "severity": "MEDIUM",
        "sql": """
            SELECT
                txn_id          AS transaction_id,
                account_orig    AS customer_id,
                amount,
                txn_date        AS date,
                txn_type        AS transaction_type,
                'R006'          AS rule_id,
                'Large Cash Withdrawal Between Midnight and 5am' AS rule_name,
                'MEDIUM'        AS severity
            FROM transactions
            WHERE txn_hour BETWEEN 0 AND 4
              AND txn_type = 'CASH_OUT'
              AND amount > 50000
        """,
    },

    "R007": {
        "name":        "Large Transfer With Round Dollar Amount",
        "description": (
            "TRANSFER of a suspiciously round amount (divisible by 10,000) "
            "over $50,000. Round numbers are a known indicator of manual fund "
            "movement — fraudsters often move 'clean' amounts like $100,000 exactly."
        ),
        "severity": "MEDIUM",
        "sql": """
            SELECT
                txn_id          AS transaction_id,
                account_orig    AS customer_id,
                amount,
                txn_date        AS date,
                txn_type        AS transaction_type,
                'R007'          AS rule_id,
                'Large Transfer With Round Dollar Amount' AS rule_name,
                'MEDIUM'        AS severity
            FROM transactions
            WHERE txn_type = 'TRANSFER'
              AND amount >= 50000
              AND CAST(amount AS INTEGER) % 10000 = 0
        """,
    },
}


def run_all_rules(db_path=DEFAULT_DB):
    """Run every rule, combine results, deduplicate on txn_id."""
    conn = sqlite3.connect(db_path)
    frames = []
    for rule_id, meta in RULES.items():
        df = pd.read_sql_query(meta["sql"], conn)
        frames.append(df)
    conn.close()

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    # keep first rule that caught each transaction
    combined = combined.drop_duplicates(subset="transaction_id", keep="first")
    return combined


def flag_transactions(db_path=DEFAULT_DB):
    """Execute all rules, write flags to DB, return summary."""
    flagged = run_all_rules(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE transactions SET is_flagged = 0")

    if not flagged.empty:
        ids = tuple(flagged["transaction_id"].tolist())
        if len(ids) == 1:
            conn.execute(
                f"UPDATE transactions SET is_flagged = 1 WHERE txn_id = '{ids[0]}'"
            )
        else:
            conn.execute(
                f"UPDATE transactions SET is_flagged = 1 WHERE txn_id IN {ids}"
            )

    conn.commit()
    conn.close()

    per_rule = {}
    for rid, meta in RULES.items():
        hits = flagged[flagged["rule_id"] == rid] if not flagged.empty else pd.DataFrame()
        per_rule[rid] = {
            "name":     meta["name"],
            "severity": meta["severity"],
            "hits":     len(hits),
        }

    return {
        "flagged_total": len(flagged),
        "per_rule":      per_rule,
        "flagged_df":    flagged,
    }


def get_rule_performance(db_path=DEFAULT_DB):
    """
    Calculate precision per rule using isFraud ground-truth labels from PaySim.
    Unlike synthetic data where I inject patterns, PaySim's isFraud is
    determined by the simulator itself — so this is a real precision metric.
    """
    conn = sqlite3.connect(db_path)
    ground_truth = pd.read_sql_query(
        "SELECT txn_id AS transaction_id, isFraud FROM transactions", conn
    )
    conn.close()

    flagged = run_all_rules(db_path)
    if flagged.empty:
        return pd.DataFrame()

    merged = flagged.merge(ground_truth, on="transaction_id", how="left")

    rows = []
    for rid in merged["rule_id"].unique():
        sub       = merged[merged["rule_id"] == rid]
        total     = len(sub)
        true_pos  = int(sub["isFraud"].sum())
        false_pos = total - true_pos

        rows.append({
            "rule_id":         rid,
            "rule_name":       RULES[rid]["name"],
            "severity":        RULES[rid]["severity"],
            "total_alerts":    total,
            "true_positives":  true_pos,
            "false_positives": false_pos,
            "precision_pct":   round(true_pos / total * 100, 1) if total else 0.0,
        })

    return pd.DataFrame(rows).sort_values("total_alerts", ascending=False)


if __name__ == "__main__":
    import os, sys
    db = os.path.join(os.path.dirname(__file__), "finwatch.db")
    if not os.path.exists(db):
        print("Run data_loader.py first.")
        sys.exit(1)

    print("Running AML detection rules...\n")
    result = flag_transactions(db)

    print(f"Total flagged: {result['flagged_total']:,}\n")
    for rid, info in result["per_rule"].items():
        bar = "█" * min(int(info["hits"] / 30), 40)
        print(f"  {rid}  {info['name']:<45} {info['hits']:>6}  {bar}")

    print("\n--- Precision vs PaySim Ground Truth ---")
    perf = get_rule_performance(db)
    if not perf.empty:
        print(perf.to_string(index=False))
