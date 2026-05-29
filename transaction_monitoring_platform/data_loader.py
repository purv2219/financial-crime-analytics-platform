# data_loader.py
# Purv Savalia — FinWatch AML Analytics Platform
#
# Handles two modes:
#   1. Real PaySim dataset from Kaggle (preferred)
#      Download from: https://www.kaggle.com/datasets/ealaxi/paysim1
#      Drop the CSV in this folder as "PS_20174392719_1491204439457_log.csv"
#
#   2. Synthetic fallback — generates data with the exact same PaySim schema
#      so the whole pipeline works without needing Kaggle credentials
#
# PaySim is a mobile money simulator built for AML research.
# Published by Lopez-Rojas et al. (2016) — widely used in fraud detection.
# Original dataset: 6.3M transactions across 30 days of simulated activity.

import os
import sqlite3
import pandas as pd
import numpy as np
import random

random.seed(7)
np.random.seed(7)

# paths
BASE_DIR    = os.path.dirname(__file__)
DB_PATH     = os.path.join(BASE_DIR, "finwatch.db")

# PaySim CSV name (as downloaded from Kaggle)
PAYSIM_CSV  = os.path.join(BASE_DIR, "PS_20174392719_1491204439457_log.csv")

# how many rows to load from the real CSV (full file is 6.3M rows — heavy)
# 200K gives a representative sample and stays fast on a laptop
SAMPLE_SIZE = 200_000

# PaySim full file = 6.3M rows; 2.5M is the working scale from the resume project
SYNTHETIC_SIZE = 100_000   # 2.5M on prod hardware (set NUM_TRANSACTIONS = 2_500_000)


# ------------------------------------------------------------------
# PaySim transaction types (from the paper)
# CASH_IN / CASH_OUT / DEBIT / PAYMENT / TRANSFER
# Fraud only occurs in CASH_OUT and TRANSFER per the original research
# ------------------------------------------------------------------
TX_TYPES = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]

# merchant name prefixes (PaySim uses C for customers, M for merchants)
def _random_name(prefix="C"):
    return f"{prefix}{random.randint(1_000_000, 9_999_999)}"


def generate_synthetic_paysim(n=SYNTHETIC_SIZE):
    """
    Generate a synthetic dataset that exactly mirrors the PaySim schema.
    Used when the real Kaggle CSV isn't available.

    PaySim columns:
        step            - hour of simulation (1 to 744 = 30 days)
        type            - transaction type
        amount          - transaction amount
        nameOrig        - origin account
        oldbalanceOrg   - balance before transaction
        newbalanceOrig  - balance after transaction
        nameDest        - destination account
        oldbalanceDest  - destination balance before
        newbalanceDest  - destination balance after
        isFraud         - ground truth fraud label
        isFlaggedFraud  - whether system flagged it (old rule-based system)
    """
    print(f"Generating {n:,} synthetic PaySim-format records...")
    rows = []

    for i in range(n):
        tx_type     = random.choices(TX_TYPES, weights=[0.22, 0.35, 0.04, 0.34, 0.05])[0]
        step        = random.randint(1, 744)

        # fraud only possible in CASH_OUT and TRANSFER (per PaySim paper)
        is_fraud = 0
        if tx_type in ("CASH_OUT", "TRANSFER"):
            is_fraud = int(random.random() < 0.003)   # ~0.3% fraud rate

        # balance logic — fraud transactions often drain accounts to 0
        old_orig = round(random.uniform(0, 500_000), 2)
        if is_fraud:
            amount      = round(old_orig * random.uniform(0.5, 1.0), 2)
            new_orig    = 0.0
        else:
            amount      = round(np.random.lognormal(mean=7, sigma=2), 2)
            amount      = min(amount, old_orig) if old_orig > 0 else amount
            new_orig    = max(0, round(old_orig - amount, 2))

        old_dest = round(random.uniform(0, 200_000), 2)
        new_dest = round(old_dest + amount, 2) if tx_type in ("TRANSFER", "PAYMENT") else old_dest

        dest_prefix = "M" if tx_type in ("PAYMENT", "DEBIT") else "C"

        rows.append({
            "step":            step,
            "type":            tx_type,
            "amount":          amount,
            "nameOrig":        _random_name("C"),
            "oldbalanceOrg":   old_orig,
            "newbalanceOrig":  new_orig,
            "nameDest":        _random_name(dest_prefix),
            "oldbalanceDest":  old_dest,
            "newbalanceDest":  new_dest,
            "isFraud":         is_fraud,
            "isFlaggedFraud":  0,
        })

    return pd.DataFrame(rows)


def load_paysim_csv(path=PAYSIM_CSV, sample=SAMPLE_SIZE):
    """Load the real PaySim CSV from Kaggle, take a sample."""
    print(f"Loading real PaySim dataset from {path}...")
    df = pd.read_csv(path, nrows=sample)
    print(f"Loaded {len(df):,} rows from Kaggle dataset.")
    return df


def _enrich(df):
    """
    Add derived columns needed by the dashboard and rule engine.
    Works on both real and synthetic PaySim data.
    """
    df = df.copy()

    # convert step (hour) to a readable date
    # PaySim step 1 = Jan 1 2023 00:00
    import datetime
    base = datetime.datetime(2022, 1, 1)
    df["txn_datetime"] = df["step"].apply(
        lambda s: base + datetime.timedelta(hours=int(s))
    )
    df["txn_date"] = df["txn_datetime"].dt.strftime("%Y-%m-%d")
    df["txn_hour"] = df["txn_datetime"].dt.hour
    df["txn_month"]= df["txn_datetime"].dt.strftime("%Y-%m")

    # balance drop flag — common in fraud cases
    df["balance_drop"] = (df["newbalanceOrig"] == 0) & (df["oldbalanceOrg"] > 0)

    # amount buckets for easy analysis
    df["amount_bucket"] = pd.cut(
        df["amount"],
        bins=[0, 1_000, 10_000, 50_000, 200_000, float("inf")],
        labels=["<1K", "1K-10K", "10K-50K", "50K-200K", ">200K"]
    )

    # unique transaction id
    df.insert(0, "txn_id", [f"T{i+1:08d}" for i in range(len(df))])

    # rename for consistency
    df.rename(columns={
        "type":  "txn_type",
        "nameOrig": "account_orig",
        "nameDest": "account_dest",
    }, inplace=True)

    # rule flag column (set by rule engine)
    df["is_flagged"] = 0

    return df


def build_database():
    """
    Main entry point. Loads or generates data, enriches it, writes to SQLite.
    """
    # prefer real data if CSV exists
    if os.path.exists(PAYSIM_CSV):
        raw = load_paysim_csv()
    else:
        print("PaySim CSV not found — using synthetic data.")
        print("To use real data: download from kaggle.com/datasets/ealaxi/paysim1")
        print("and place CSV in this folder.\n")
        raw = generate_synthetic_paysim()

    df = _enrich(raw)

    print(f"Writing {len(df):,} rows to {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    df.to_sql("transactions", conn, if_exists="replace", index=False)

    # indexes — critical for dashboard query speed
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date    ON transactions(txn_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_type    ON transactions(txn_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fraud   ON transactions(isFraud)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orig    ON transactions(account_orig)")
    conn.commit()
    conn.close()

    fraud_count = df["isFraud"].sum()
    print(f"Database ready.")
    print(f"  Total transactions : {len(df):,}")
    print(f"  Fraud transactions : {int(fraud_count):,} ({fraud_count/len(df)*100:.2f}%)")
    print(f"  Transaction types  : {df['txn_type'].value_counts().to_dict()}")
    return DB_PATH


if __name__ == "__main__":
    build_database()
