# FinSight — Transaction Risk Analytics

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-blue.svg)](https://www.postgresql.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

FinSight is an end-to-end batch analytics project for fraud-risk triage on payment transactions.
It validates 6.36M simulated transactions, loads them into PostgreSQL, scores them with both a
transparent rule engine and a gradient-boosting model, and explains each model score with SHAP.

The goal is **prioritising transactions for human review**, not automatically declaring fraud.

> **Scope:** a historical-data prototype built on the synthetic [PaySim](https://www.kaggle.com/datasets/ealaxi/paysim1)
> dataset. It is not a real-time payment system, and results on simulated data do not establish
> performance against real financial crime.

---

## How it works

```text
PaySim CSV (6.36M rows)
   │
   ▼
pipeline.py ──── invalid rows ──► rejection report (reason codes)
   │  validated + derived hour/day
   ▼
load_to_postgres.py ──► fct_transactions ──► SQL analytics + views
   │
   ├──► risk_rules.py      rule score 0–100, tier, plain-English reasons
   └──► models.py          HistGradientBoosting fraud score
             └──► explainability.py   per-transaction SHAP attributions
```

| Module | Responsibility |
| :--- | :--- |
| [`pipeline.py`](src/finsight/pipeline.py) | Chunked ingestion and validation; rejects bad rows with reason codes; derives `transaction_hour` / `transaction_day` |
| [`load_to_postgres.py`](src/finsight/load_to_postgres.py) | Streams the cleaned file into PostgreSQL with `COPY`; refuses to double-load |
| [`features.py`](src/finsight/features.py) | Builds the model feature matrix and blocks leakage columns |
| [`risk_rules.py`](src/finsight/risk_rules.py) | Rule engine driven by [`config/risk_rules.yaml`](config/risk_rules.yaml) |
| [`models.py`](src/finsight/models.py) | Chronological train/validation/holdout split, training, threshold selection |
| [`ml_experiments.py`](src/finsight/ml_experiments.py) | Benchmarks, feature and class-weight experiments, temporal robustness |
| [`explainability.py`](src/finsight/explainability.py) | TreeSHAP global and local explanations |

---

## Results

Evaluated on the unseen holdout period (simulation steps ≥ 551: 196,601 transactions, 2,148 frauds).
Thresholds were chosen on the validation period, never on the holdout.

| System | PR-AUC | ROC-AUC | Precision | Recall | F1 | Alerts |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Majority-class baseline | 0.011 | 0.500 | 0.0% | 0.0% | 0.000 | 0 |
| Rule engine (HIGH tier, score ≥ 70) | — | — | **72.0%** | 18.7% | 0.297 | 558 |
| Logistic regression (balanced) | 0.181 | 0.915 | 24.3% | 29.1% | 0.265 | 2,576 |
| HistGradientBoosting (all features) | 0.384 | 0.919 | 60.5% | 39.3% | 0.477 | 1,396 |
| **HistGradientBoosting, no `transaction_day` (champion)** | **0.448** | **0.949** | 57.7% | **42.7%** | **0.491** | 1,590 |

**What this means:** the rules are precise but catch under a fifth of fraud. The champion model
catches more than twice as much at a manageable alert volume. Neither is good enough alone,
and combining them is on the roadmap.

---

## Key design decisions

- **No leakage.** Balance columns are excluded: 98% of PaySim fraud drains the origin account to
  exactly $0, which would let a model learn a simulator artifact. `isFlaggedFraud` and raw account
  IDs are excluded too. [`validate_no_leakage_columns`](src/finsight/features.py) enforces this in code.
- **Chronological split.** Train on steps 1–450, tune on 451–550, report on 551+. No random
  splitting, so no look-ahead.
- **Imbalance-aware metrics.** Fraud is 0.13% of rows, so a model predicting "never fraud" is
  99.87% accurate. Results are reported with PR-AUC, precision and recall instead.
- **Removing a shortcut feature helped.** Legitimate volume collapses after simulated day 17,
  so `transaction_day` acted as a proxy for fraud prevalence. Dropping it raised holdout PR-AUC
  from 0.384 to 0.448.
- **Explanations are attributions, not causes.** SHAP values describe what the model learned
  from simulated data. They are not evidence of intent.

---

## Quickstart

**Prerequisites:** Python 3.11+, and PostgreSQL 15+ for the database steps.

```bash
git clone https://github.com/dheemant-k/FinSight.git
cd FinSight
python -m venv .venv
.venv\Scripts\activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
python -m pytest tests/ -q      # runs without the dataset or a database
```

To run the full pipeline, download the PaySim CSV (`PS_20174392719_1491204439457_log.csv`) from
[Kaggle](https://www.kaggle.com/datasets/ealaxi/paysim1) into `data/raw/`, then:

```bash
python src/finsight/pipeline.py --max-rows 50000          # or omit --max-rows for all 6.36M rows
python src/finsight/load_to_postgres.py --create-schema --truncate
python src/finsight/models.py --evaluate-frozen --model-path models/hist_gradient_boosting_no_day.joblib --reports-dir reports/remediation
python src/finsight/explainability.py --data-path data/processed/transactions.csv.gz --model-path models/hist_gradient_boosting_no_day.joblib --sample-size 2000 --random-seed 42
```

Database settings are read from `.env` (copy [`.env.example`](.env.example)). The
[technical guide](docs/technical-guide.md) has every command and option.

---

## Project structure

```text
FinSight/
├── config/
│   ├── risk_rules.yaml        # Rule thresholds, weights and tiers (loaded by the rule engine)
│   └── pipeline.yaml          # Ingestion parameters (reference only, see roadmap)
├── data/                      # raw/ and processed/ are git-ignored
├── docs/                      # Technical guide, architecture, methodology, dictionaries
├── models/                    # Trained model artifacts (.joblib)
├── reports/                   # Generated evaluation, experiment and SHAP reports
├── sql/
│   ├── schema/                # Table definitions
│   ├── analytics/             # 7 analysis queries
│   └── views/                 # 4 analytical views
├── src/finsight/              # Pipeline, loader, features, rules, models, explainability
└── tests/                     # pytest suite
```

---

## Limitations

- **Synthetic data.** All PaySim fraud occurs on `TRANSFER` and `CASH_OUT`, so much of the
  model's signal is transaction type. Results do not transfer to real fraud.
- **Thin features.** 99.85% of accounts appear once, so customer-history and velocity features
  (the core of real fraud detection) cannot be built on this dataset.
- **Scores are not probabilities.** Balanced class weighting shifts the scores; they rank risk
  but are not calibrated.
- **One SQL view is static.** [`vw_risk_detection_benchmark`](sql/views/04_vw_risk_detection_benchmark.sql)
  holds evaluation results as literal values rather than computing them from scored tables.

More detail: [findings and limitations](docs/findings-and-limitations.md).

---

## Status and roadmap

| Area | Status |
| :--- | :--- |
| Ingestion, validation, PostgreSQL loading | Done |
| SQL analytics queries and views | Done |
| Rule engine (YAML-configured) | Done |
| ML models, threshold selection, SHAP | Done |
| Sample dataset, Docker setup, CI | Planned |
| Scored tables in PostgreSQL (replacing the static benchmark view) | Planned |
| Calibration, cost-based thresholds, rules + ML combination | Planned |
| Dashboard (Power BI or Streamlit) | Planned |
| Second dataset with customer history | Planned |

---

## Documentation

- [Technical guide](docs/technical-guide.md): milestone-by-milestone detail and all commands
- [Project summary](docs/project-summary.md) and [original brief](docs/project-brief.md)
- [Architecture](docs/architecture.md) · [Data dictionary](docs/data-dictionary.md) · [Metric dictionary](docs/metric-dictionary.md)
- [Risk methodology](docs/risk-methodology.md) · [Evaluation strategy](docs/evaluation-strategy.md)
- Reports: [model evaluation](reports/model_evaluation/model_comparison.md) ·
  [SHAP explainability](reports/explainability/explainability_report.md) ·
  [final verification](reports/remediation/final_verification_report.md)

## License

[MIT](LICENSE)
