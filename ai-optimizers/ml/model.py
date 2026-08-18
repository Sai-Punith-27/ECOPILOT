"""
model.py
========
Shared feature schema + preprocessing for the EcoPilot household energy
predictor. This is the SINGLE SOURCE OF TRUTH for what a "feature row"
looks like -- both train.py (training) and inference.py (serving) import
from here, so training and serving can never drift apart.

SCOPE / HONESTY NOTE
---------------------
This model predicts *whole-household* appliance energy consumption (Wh),
trained on the UCI "Appliances Energy Prediction" dataset (Candanedo et
al., a single Belgian home, Jan-May 2016). It is NOT a per-appliance model
(the dataset doesn't provide per-appliance/circuit breakdown -- only a
single whole-house "Appliances" meter), and it is NOT validated on Indian
households or Indian climate data. Both limitations are surfaced in the
dashboard, not just in this docstring.

FEATURE SELECTION RATIONALE (avoiding leakage + matching what EcoPilot's
own simulator/IoT telemetry can realistically provide)
---------------------------------------------------------------------------
The raw dataset has 26 candidate feature columns: 9 indoor room
temperatures (T1-T9), 9 indoor room humidities (RH_1-RH_9), a `lights`
submeter, outdoor T/RH/pressure/windspeed/visibility/dewpoint, and two
literally-random columns (`rv1`, `rv2`) the original authors included as a
leakage/overfitting sanity check.

EcoPilot's simulator/telemetry does NOT have 9 separate room sensors or a
`lights` submeter -- it has ONE indoor temperature + humidity reading per
appliance (AC/cooler) and outdoor temperature/humidity from the live
weather client. So we deliberately use a reduced, realistic feature set:

    T_indoor_avg   = mean(T1..T9)      -- proxy for "our" single indoor sensor
    RH_indoor_avg  = mean(RH_1..RH_9)  -- proxy for "our" single indoor sensor
    T_out, RH_out  = used as-is        -- directly available from weather_client.py
    hour, dayofweek = derived from timestamp -- always available, not leakage
                       (captures daily/weekly usage patterns without using
                       any value that wouldn't be known ahead of the
                       prediction interval)
    appliances_lag_1 = the PREVIOUS interval's household energy reading --
                       a legitimate autoregressive feature. Our backend
                       already stores historical telemetry, so "the most
                       recently observed total power reading" is something
                       we can genuinely supply at inference time. This is
                       a past value relative to the prediction target, so
                       it is NOT leakage.

Excluded (not available from our system, or explicitly a leakage risk):
`lights`, individual T1-T9/RH_1-RH_9, `Press_mm_hg`, `Windspeed`,
`Visibility`, `Tdewpoint`, `rv1`, `rv2`.

IMPORTANT, MEASURED FINDING (see ml/artifacts/metrics.json for the exact
numbers): the weather+time-only feature set (T_indoor_avg, RH_indoor_avg,
T_out, RH_out, hour, dayofweek) was tried FIRST and found to perform only
marginally better than a naive "predict the training-set mean" baseline on
this dataset (test R^2 ~ 0). This matches published results for this
dataset -- weather alone is a weak predictor of appliance energy. Adding
`appliances_lag_1` measurably improves this (see metrics.json), which is
why it is included as a feature. We report both results in metrics.json
rather than hiding the weaker one.
"""

from typing import Dict, List
import pandas as pd

FEATURE_COLUMNS: List[str] = [
    "T_indoor_avg",
    "RH_indoor_avg",
    "T_out",
    "RH_out",
    "hour",
    "dayofweek",
    "appliances_lag_1",
]

TARGET_COLUMN = "Appliances"  # Wh, whole-household appliance energy

_INDOOR_T_COLS = [f"T{i}" for i in range(1, 10)]
_INDOOR_RH_COLS = [f"RH_{i}" for i in range(1, 10)]


def load_raw_dataset(csv_path: str) -> pd.DataFrame:
    """Load the UCI CSV and normalize column names (strip whitespace the
    original file has around some header names)."""
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def build_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Turn a raw UCI-format dataframe (with T1-T9, RH_1-RH_9, T_out, RH_out,
    date columns) into the reduced FEATURE_COLUMNS feature frame used for
    both training and (via engineer_features_from_dict) inference.
    """
    out = pd.DataFrame(index=df.index)
    out["T_indoor_avg"] = df[_INDOOR_T_COLS].mean(axis=1)
    out["RH_indoor_avg"] = df[_INDOOR_RH_COLS].mean(axis=1)
    out["T_out"] = df["T_out"]
    out["RH_out"] = df["RH_out"]
    out["hour"] = df["date"].dt.hour
    out["dayofweek"] = df["date"].dt.dayofweek
    out["appliances_lag_1"] = df[TARGET_COLUMN].shift(1)
    # First row has no prior reading -- back-fill with its own value rather
    # than dropping (keeps the frame aligned 1:1 with df; train.py drops any
    # remaining NaNs after this call if needed).
    out["appliances_lag_1"] = out["appliances_lag_1"].bfill()
    return out[FEATURE_COLUMNS]


def engineer_features_from_dict(payload: Dict) -> pd.DataFrame:
    """
    Build a single-row feature frame from a live telemetry-shaped payload,
    for inference. Expected keys (all required):

        indoor_temperature  (C)   -- from AC/cooler telemetry
        indoor_humidity      (%)   -- from AC/cooler telemetry
        outdoor_temperature   (C)   -- from weather_client.py
        outdoor_humidity       (%)   -- from weather_client.py
        recent_energy_wh          -- most recently observed total household
                                     power/energy reading (Wh), pulled by the
                                     backend from its own telemetry history
        timestamp                -- ISO datetime string or pandas-parseable;
                                     used only to derive hour/dayofweek

    Raises KeyError/ValueError on missing/invalid fields -- the caller
    (inference.py) is responsible for turning that into a clean
    "prediction unavailable" response rather than a 500.
    """
    required = [
        "indoor_temperature", "indoor_humidity",
        "outdoor_temperature", "outdoor_humidity",
        "recent_energy_wh", "timestamp",
    ]
    missing = [k for k in required if k not in payload or payload[k] is None]
    if missing:
        raise ValueError(f"Missing required feature(s) for prediction: {missing}")

    ts = pd.to_datetime(payload["timestamp"])
    row = {
        "T_indoor_avg": float(payload["indoor_temperature"]),
        "RH_indoor_avg": float(payload["indoor_humidity"]),
        "T_out": float(payload["outdoor_temperature"]),
        "RH_out": float(payload["outdoor_humidity"]),
        "hour": ts.hour,
        "dayofweek": ts.dayofweek,
        "appliances_lag_1": float(payload["recent_energy_wh"]),
    }
    return pd.DataFrame([row])[FEATURE_COLUMNS]
