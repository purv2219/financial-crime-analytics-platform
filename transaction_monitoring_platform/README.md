# FinWatch

FinWatch is a Streamlit dashboard for transaction monitoring and AML-style rule analysis.

The project uses Python, SQL, SQLite, Pandas, and Plotly to load transaction data, apply rule-based checks, and show alerts in an interactive dashboard.

## Overview

This project was built to practice financial crime analytics using a simulated mobile money dataset. The main idea is to take raw transaction data, run SQL-based detection rules, and review the flagged activity through a dashboard.

The app includes:

* transaction-level monitoring
* rule-based alert generation
* rule performance metrics
* account-level transaction review
* simple compliance-style reports

## Dataset

This project uses the PaySim dataset from Kaggle.

PaySim is a simulated mobile money transaction dataset with fields such as transaction type, amount, origin account, destination account, account balances, and fraud labels.

Dataset file:

```text
PS_20174392719_1491204439457_log.csv
```

The app can run with the real PaySim CSV file. If the CSV is not available, it creates synthetic sample data with the same structure so the dashboard can still be tested.

## Project Structure

```text
FinWatch/
├── app.py
├── data_loader.py
├── rule_engine.py
├── requirements.txt
└── README.md
```

## Files

| File               | Description                                                      |
| ------------------ | ---------------------------------------------------------------- |
| `app.py`           | Main Streamlit dashboard                                         |
| `data_loader.py`   | Loads data, creates extra fields, and builds the SQLite database |
| `rule_engine.py`   | Runs detection rules and calculates rule performance             |
| `requirements.txt` | Python dependencies                                              |

## How It Works

```text
CSV file
   ↓
data_loader.py
   ↓
SQLite database
   ↓
rule_engine.py
   ↓
Streamlit dashboard
```

## Detection Rules

The current version uses 7 SQL-based rules:

| Rule | Description                                          |
| ---- | ---------------------------------------------------- |
| R001 | Full balance transfer or account drain               |
| R002 | Large cash-out transaction                           |
| R003 | Large transfer to an empty destination account       |
| R004 | Multiple transfers from the same account in one hour |
| R005 | Balance mismatch after transaction                   |
| R006 | Large late-night cash activity                       |
| R007 | Large round-number transfer                          |

The rules are kept simple on purpose so the logic is easy to read, test, and adjust.

## Dashboard Pages

The app has five main pages:

1. **Executive Dashboard**
   Shows overall transaction volume, fraud count, alert count, alert rate, and charts.

2. **Alert Explorer**
   Allows filtering flagged transactions by severity, rule, and amount.

3. **Rule Performance**
   Shows true positives, false positives, and precision by rule.

4. **Account Deep Dive**
   Lets users search one account and review its transaction history.

5. **Compliance Reports**
   Provides downloadable summaries for alerts, fraud records, and rule coverage.

## Setup

Install the required packages:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
python -m streamlit run app.py
```

Then open:

```text
http://localhost:8501
```

## Using the PaySim Dataset

1. Download the PaySim dataset from Kaggle.
2. Place the CSV file in the project folder.
3. Run the Streamlit app.

Expected file name:

```text
PS_20174392719_1491204439457_log.csv
```

## Notes

* The project uses simulated data, not real customer data.
* Detection is rule-based, not machine learning-based.
* The dashboard is meant for analytics and portfolio demonstration.
* Some AML patterns cannot be tested because PaySim does not include fields like country, KYC profile, device ID, or IP address.

## Future Improvements

Possible next steps:

* add ML-based anomaly detection
* add network graph analysis between accounts
* add more rule tuning history
* add user-uploaded CSV support
* add email alerts for high-risk transactions

## Tech Stack

Python
SQL / SQLite
Pandas
Streamlit
Plotly
NumPy
