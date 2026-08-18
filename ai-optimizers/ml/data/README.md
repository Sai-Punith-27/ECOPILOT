# Dataset: UCI Appliances Energy Prediction

This folder is where `energydata_complete.csv` goes for training (`train.py`).
The CSV is **not committed to git** (see root `.gitignore`) — it's ~12MB and
not needed at runtime (only `train.py`, which is run offline/locally, needs
it). The trained outputs (`../artifacts/model.joblib`, `../artifacts/metrics.json`)
ARE committed, since the deployed backend needs them and they're small.

## Get the dataset

Original source (UCI Machine Learning Repository):
https://archive.ics.uci.edu/dataset/374/appliances+energy+prediction

Direct CSV mirror (published by the dataset's own author, Luis Candanedo):
```bash
curl -L -o energydata_complete.csv \
  https://raw.githubusercontent.com/LuisM78/Appliances-energy-prediction-data/master/energydata_complete.csv
```

Expected: 19,735 rows, 29 columns, `date` ranging 2016-01-11 to 2016-05-27.

## Then train

```bash
cd ai-optimizers/ml
pip install -r requirements.txt
python train.py --data data/energydata_complete.csv --out artifacts
```

This overwrites `artifacts/model.joblib` and `artifacts/metrics.json`. Commit
those two files (not the CSV) if you retrain and want the new model deployed.
