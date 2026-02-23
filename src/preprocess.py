"""
Preprocessing Pipeline for AI-Powered Microsegmentation
========================================================
Filters UNSW-NB15 to Normal/Exploits/Reconnaissance,
cleans data, encodes categoricals, and saves train + test CSVs.

Usage:
    python preprocess.py
    
Inputs:  UNSW_NB15_training-set.csv, UNSW_NB15_testing-set.csv
Outputs: filtered_training.csv, filtered_testing.csv
"""

import pandas as pd
import numpy as np

# ── Configuration ────────────────────────────────────────────────
TARGET_CLASSES = ["Normal", "Exploits", "Reconnaissance"]
DROP_COLS = ["id", "srcip", "sport", "dstip", "dsport"]
CAT_COLS = ["proto", "state", "service"]

# ── Step 1: Load ─────────────────────────────────────────────────
print("Step 1: Loading datasets...")
df_train = pd.read_csv("UNSW_NB15_training-set.csv", encoding="utf-8-sig")
df_test = pd.read_csv("UNSW_NB15_testing-set.csv", encoding="utf-8-sig")

print(f"  Raw training: {df_train.shape[0]:,} rows x {df_train.shape[1]} cols")
print(f"  Raw testing:  {df_test.shape[0]:,} rows x {df_test.shape[1]} cols")

# ── Step 2: Filter to 3 classes ──────────────────────────────────
print("\nStep 2: Filtering to target classes...")

# Normalize whitespace in attack_cat
df_train["attack_cat"] = df_train["attack_cat"].astype(str).str.strip()
df_test["attack_cat"] = df_test["attack_cat"].astype(str).str.strip()

df_train = df_train[df_train["attack_cat"].isin(TARGET_CLASSES)].copy()
df_test = df_test[df_test["attack_cat"].isin(TARGET_CLASSES)].copy()

print(f"  Filtered training: {df_train.shape[0]:,} rows")
print(f"  Filtered testing:  {df_test.shape[0]:,} rows")
print(f"\n  Training class distribution:")
for cat, count in df_train["attack_cat"].value_counts().items():
    pct = 100 * count / len(df_train)
    print(f"    {cat:20s}: {count:>6,} ({pct:.1f}%)")

# ── Step 3: Drop identity / non-feature columns ─────────────────
print("\nStep 3: Dropping identity columns...")
for col in DROP_COLS:
    if col in df_train.columns:
        df_train.drop(columns=[col], inplace=True)
        df_test.drop(columns=[col], inplace=True)
        print(f"  Dropped: {col}")

# ── Step 4: Handle problematic columns ───────────────────────────
print("\nStep 4: Cleaning data...")

# ct_ftp_cmd has space values that should be 0
for df in [df_train, df_test]:
    if "ct_ftp_cmd" in df.columns:
        df["ct_ftp_cmd"] = pd.to_numeric(df["ct_ftp_cmd"], errors="coerce").fillna(0).astype(int)

# Replace inf with NaN
for df in [df_train, df_test]:
    df.replace([np.inf, -np.inf], np.nan, inplace=True)

# ── Step 5: Frequency-encode categoricals ────────────────────────
# Frequency encoding preserves relative importance of each category
# and works well with both DBSCAN (distance-based) and XGBoost (tree-based)
print("\nStep 5: Frequency-encoding categoricals...")
freq_maps = {}
for col in CAT_COLS:
    if col in df_train.columns:
        freq_map = df_train[col].value_counts(normalize=True).to_dict()
        freq_maps[col] = freq_map
        df_train[col] = df_train[col].map(freq_map).fillna(0).astype(float)
        df_test[col] = df_test[col].map(freq_map).fillna(0).astype(float)
        print(f"  Encoded '{col}' ({len(freq_map)} unique values)")

# ── Step 6: Fill remaining missing values ────────────────────────
print("\nStep 6: Handling missing values...")
numeric_cols = df_train.select_dtypes(include=[np.number]).columns
missing = df_train[numeric_cols].isnull().sum()
missing_cols = missing[missing > 0]

if len(missing_cols) > 0:
    print(f"  Found missing values in {len(missing_cols)} columns")
    for col in missing_cols.index:
        median_val = df_train[col].median()
        df_train[col].fillna(median_val, inplace=True)
        df_test[col].fillna(median_val, inplace=True)
    print("  Filled with training set medians")
else:
    # Fallback: fill any remaining NaN with 0
    df_train.fillna(0, inplace=True)
    df_test.fillna(0, inplace=True)
    print("  No missing values found")

# Ensure all feature columns are numeric
feature_cols = [c for c in df_train.columns if c not in ["attack_cat", "label"]]
for col in feature_cols:
    df_train[col] = pd.to_numeric(df_train[col], errors="coerce").fillna(0)
    df_test[col] = pd.to_numeric(df_test[col], errors="coerce").fillna(0)

# ── Step 7: Save ─────────────────────────────────────────────────
df_train.to_csv("filtered_training.csv", index=False)
df_test.to_csv("filtered_testing.csv", index=False)

print(f"\nSaved filtered_training.csv: {df_train.shape}")
print(f"Saved filtered_testing.csv:  {df_test.shape}")
print(f"Features: {len(feature_cols)}")
print(f"\nDone.")
