"""
train.py
========
Trains the EcoPilot household energy consumption predictor on the UCI
Appliances Energy Prediction dataset, using ONLY the reduced, realistic
feature set defined in model.py (see that file's docstring for the full
rationale).

Usage:
    python train.py --data data/energydata_complete.csv --out artifacts

Produces (in --out):
    model.joblib   -- the selected scikit-learn Pipeline (preprocessing + model)
    metrics.json   -- validation/test metrics for BOTH candidate models, so the
                       final choice is auditable, not just asserted

METHODOLOGY NOTES
------------------
- Split is CHRONOLOGICAL (70% train / 15% val / 15% test by time), not a
  random shuffle. This dataset is a single continuous time series recorded
  every 10 minutes; a random split would put near-duplicate adjacent rows
  on both sides of the split and inflate the reported accuracy. A
  chronological split is the honest way to estimate how well this would
  generalize to *future* data, which is the actual use case here.
- Two candidate models are trained: a Linear Regression baseline (fully
  transparent, coefficients are directly inspectable) and a
  RandomForestRegressor (usually stronger on this kind of tabular data).
  The one with the better validation RMSE is selected as the deployed
  model; both sets of metrics are kept in metrics.json for transparency.
- Metrics reported: RMSE, MAE, R^2 on both validation and test sets, plus
  a naive baseline (predicting the training-set mean) so the reader can
  judge whether the model is actually adding value.
"""

import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
import joblib

from model import FEATURE_COLUMNS, TARGET_COLUMN, load_raw_dataset, build_feature_frame

MODEL_VERSION = "ecopilot-energy-predictor-v1"


def chronological_split(df: pd.DataFrame, train_frac=0.70, val_frac=0.15):
    n = len(df)
    train_end = int(n * train_frac)
    val_end = int(n * (train_frac + val_frac))
    return df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]


def evaluate(y_true, y_pred) -> dict:
    return {
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/energydata_complete.csv")
    parser.add_argument("--out", default="artifacts")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    print(f"Loading dataset from {args.data} ...")
    raw = load_raw_dataset(args.data)
    X_all = build_feature_frame(raw)
    y_all = raw[TARGET_COLUMN].astype(float)

    df = pd.concat([X_all, y_all.rename(TARGET_COLUMN)], axis=1)
    train_df, val_df, test_df = chronological_split(df)
    print(f"Split sizes -> train={len(train_df)}, val={len(val_df)}, test={len(test_df)}")

    X_train, y_train = train_df[FEATURE_COLUMNS], train_df[TARGET_COLUMN]
    X_val, y_val = val_df[FEATURE_COLUMNS], val_df[TARGET_COLUMN]
    X_test, y_test = test_df[FEATURE_COLUMNS], test_df[TARGET_COLUMN]

    # Naive baseline: always predict the training-set mean. Any real model
    # should beat this on RMSE/MAE, or it isn't adding value.
    naive_pred_val = np.full_like(y_val, fill_value=y_train.mean(), dtype=float)
    naive_pred_test = np.full_like(y_test, fill_value=y_train.mean(), dtype=float)
    naive_metrics = {
        "val": evaluate(y_val, naive_pred_val),
        "test": evaluate(y_test, naive_pred_test),
    }

    candidates = {
        "linear_regression": Pipeline([
            ("scaler", StandardScaler()),
            ("model", LinearRegression()),
        ]),
        "random_forest": Pipeline([
            ("scaler", StandardScaler()),  # harmless for trees, keeps pipeline uniform
            ("model", RandomForestRegressor(
                n_estimators=200, max_depth=10, min_samples_leaf=5,
                random_state=42, n_jobs=-1,
            )),
        ]),
    }

    results = {}
    fitted = {}
    for name, pipe in candidates.items():
        print(f"Training {name} ...")
        pipe.fit(X_train, y_train)
        fitted[name] = pipe
        val_pred = pipe.predict(X_val)
        test_pred = pipe.predict(X_test)
        results[name] = {
            "val": evaluate(y_val, val_pred),
            "test": evaluate(y_test, test_pred),
        }
        print(f"  {name}: val_rmse={results[name]['val']['rmse']:.2f} "
              f"test_rmse={results[name]['test']['rmse']:.2f}")

    best_name = min(results, key=lambda k: results[k]["val"]["rmse"])
    best_pipeline = fitted[best_name]
    print(f"Selected model: {best_name} (lowest validation RMSE)")

    model_path = os.path.join(args.out, "model.joblib")
    joblib.dump(best_pipeline, model_path)
    print(f"Saved model to {model_path}")

    metrics = {
        "model_version": MODEL_VERSION,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_model": best_name,
        "feature_columns": FEATURE_COLUMNS,
        "target_column": TARGET_COLUMN,
        "dataset": "UCI Appliances Energy Prediction (Candanedo et al.), single Belgian household, Jan-May 2016",
        "split": {"train_frac": 0.70, "val_frac": 0.15, "test_frac": 0.15, "method": "chronological"},
        "naive_baseline_metrics": naive_metrics,
        "candidate_metrics": results,
        "selected_model_test_metrics": results[best_name]["test"],
        "disclaimer": (
            "This model predicts whole-household appliance energy (Wh), not "
            "per-appliance energy, and was trained on a single Belgian home. "
            "It is not validated for Indian households or Indian climate "
            "conditions. Treat predictions as an approximate trend signal, "
            "not ground truth."
        ),
    }
    metrics_path = os.path.join(args.out, "metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Saved metrics to {metrics_path}")

    print("\n=== Summary ===")
    print(json.dumps({
        "selected_model": best_name,
        "test_rmse": results[best_name]["test"]["rmse"],
        "test_mae": results[best_name]["test"]["mae"],
        "test_r2": results[best_name]["test"]["r2"],
        "naive_baseline_test_rmse": naive_metrics["test"]["rmse"],
    }, indent=2))


if __name__ == "__main__":
    main()
