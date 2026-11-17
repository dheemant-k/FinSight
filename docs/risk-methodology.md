# FinSight — Risk Rule Methodology

**Document version:** 1.1.0
**Implementation:** [`src/finsight/risk_rules.py`](../src/finsight/risk_rules.py)
**Configuration:** [`config/risk_rules.yaml`](../config/risk_rules.yaml)

---

## 1. Why a rule engine alongside the ML model

FinSight scores transactions two ways: a deterministic rule engine and a supervised
gradient-boosting model explained with SHAP. They play different roles:

- **Rules are directly auditable.** Every point in a score maps to one named condition with the
  exact threshold that fired, which an analyst can verify by hand.
- **Rules need no labels.** They work from day one, while supervised models need labelled
  history (in real payments, chargeback labels can lag by 60–90 days).
- **The ML model ranks better.** On the holdout period it catches more than twice as much fraud
  as the rules (recall 42.7% vs 18.7%). The rules are more precise (72.0% vs 57.7%).

Rule scores are investigation signals, not fraud determinations, and the engine never reads
the `isFraud` label.

---

## 2. Scoring framework

Each transaction starts at 0 and gains points for every enabled rule it triggers:

$$\text{Risk Score} = \min\left(100, \sum_{i \in \text{Triggered Rules}} \text{Risk Points}_i \right)$$

| Score | Tier | Recommended action |
| :---: | :---: | :--- |
| 0 – 29 | LOW | `AUTO_APPROVE` |
| 30 – 69 | MEDIUM | `MANUAL_REVIEW` |
| 70 – 100 | HIGH | `FLAG_SUSPICIOUS` |

The maximum possible score from the current rules is 100 (35 + 25 + 25 + 15).

---

## 3. Rules

All four rules use only fields available in PaySim: `amount`, `type`, and the hour derived from
`step`. Thresholds below are the values in `config/risk_rules.yaml`.

### 3.1 `RULE_001_HIGH_VALUE`: excessive single amount (35 points)
- **Triggers when:** `amount >= 200,000`
- **Why:** labelled fraudulent transfers and cash-outs average about $1.47M, against about $173k
  for legitimate cash-outs.
- **Limitation:** large legitimate payments (payroll, B2B, asset purchases) also exceed this.

### 3.2 `RULE_002_DRAINAGE_RAIL`: drainage rail exposure (25 points)
- **Triggers when:** `type` is `TRANSFER` or `CASH_OUT`
- **Why:** all labelled fraud in PaySim occurs on these two rails.
- **Limitation:** over 99% of transactions on these rails are legitimate.

### 3.3 `RULE_003_OVERNIGHT_DRAINAGE`: off-hours drainage (25 points)
- **Triggers when:** hour is 1–5, `type` is `TRANSFER` or `CASH_OUT`, and `amount >= 10,000`
- **Why:** legitimate simulated volume falls sharply overnight while fraud volume does not.
- **Limitation:** hours are simulated, not real clock times; legitimate overnight activity exists.

### 3.4 `RULE_004_LARGE_ROUND_AMOUNT`: large round amount (15 points)
- **Triggers when:** `amount >= 50,000`, `amount` is a multiple of 5,000, and `type` is
  `TRANSFER` or `CASH_OUT`
- **Why:** account liquidations often hit round limit ceilings.
- **Limitation:** round inter-account transfers are common and legitimate.

### Rules not possible on PaySim
Velocity (many transactions in a short window), impossible travel, merchant-category risk and
declines-before-approval are standard production rules. PaySim has no geography, merchant
categories or decline events, and 99.85% of accounts appear once, so these cannot be built on it.
They are planned for a second dataset with customer history.

---

## 4. Output format

`RiskEngine.evaluate_transaction` returns, for example, for a $352,750 transfer at hour 3:

```json
{
  "risk_score": 85,
  "risk_tier": "HIGH",
  "action_recommended": "FLAG_SUSPICIOUS",
  "triggered_rule_count": 3,
  "triggered_rules": ["RULE_001_HIGH_VALUE", "RULE_002_DRAINAGE_RAIL", "RULE_003_OVERNIGHT_DRAINAGE"],
  "reason_codes": [
    {"rule_id": "RULE_001_HIGH_VALUE", "points": 35, "message": "Transaction amount $352,750.00 meets or exceeds the single transaction monitoring threshold of $200,000.00."},
    {"rule_id": "RULE_002_DRAINAGE_RAIL", "points": 25, "message": "Transaction rail 'TRANSFER' matches high-risk fund drainage channel."},
    {"rule_id": "RULE_003_OVERNIGHT_DRAINAGE", "points": 25, "message": "Disbursement of $352,750.00 via 'TRANSFER' executed overnight at hour 03:00 (dormancy monitoring window)."}
  ]
}
```

(`name` and `severity` fields are omitted above for brevity.) `evaluate_dataframe` produces the
same scores for a whole DataFrame using vectorised operations.

---

## 5. Measured performance

Holdout period (steps ≥ 551, 196,601 transactions, 2,148 frauds), alerting on the HIGH tier:
precision 72.0%, recall 18.7%, F1 0.297, 558 alerts. See
[`reports/remediation/final_rules_vs_ml_review.md`](../reports/remediation/final_rules_vs_ml_review.md).

---

## 6. Changing rules

1. Edit thresholds, points, `enabled` flags or tier boundaries in `config/risk_rules.yaml`.
   `RiskEngine()` loads this file automatically.
2. The loader rejects unknown rule ids, duplicate ids and non-contiguous tiers, so the YAML cannot
   silently drift from the implemented rules.
3. A new rule type needs an evaluator in `risk_rules.py` and its id added to `SUPPORTED_RULE_IDS`.
4. Re-run the rule benchmark before adopting changes, and commit the YAML change with its
   measured effect.
