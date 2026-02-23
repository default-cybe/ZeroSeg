"""
Feature Selection for XGBoost Classifier
=========================================
Trains XGBoost on all features, ranks by importance, selects top features
covering 95%+ cumulative importance, and validates performance.

Usage:
    python feature_selection.py

Inputs:  filtered_training.csv
Outputs: feature_matrix.csv, feature_importance.png
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import cross_val_predict, StratifiedKFold
from sklearn.metrics import classification_report
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore")

RANDOM_SEED = 42
CUM_IMPORTANCE_THRESHOLD = 0.95
np.random.seed(RANDOM_SEED)

# ── Load data ────────────────────────────────────────────────────
print("Loading data...")
df = pd.read_csv("filtered_training.csv")

drop_cols = ["id", "attack_cat", "label"]
all_features = [c for c in df.columns if c not in drop_cols]

le = LabelEncoder()
y = le.fit_transform(df["attack_cat"])
X = df[all_features].fillna(0)

print(f"  Shape: {X.shape}")
print(f"  Classes: {list(le.classes_)}")
print(f"  Features: {len(all_features)}")

# ── Step 1: Remove zero-variance features ────────────────────────
print("\nStep 1: Removing zero-variance features...")
variances = X.var()
zero_var = variances[variances == 0].index.tolist()
if zero_var:
    print(f"  Removed {len(zero_var)} zero-variance features: {zero_var}")
    all_features = [f for f in all_features if f not in zero_var]
    X = X[all_features]
else:
    print("  None found")

# ── Step 2: Remove highly correlated features (|r| > 0.95) ──────
print("\nStep 2: Removing highly correlated features...")
corr_matrix = X.corr().abs()
upper_tri = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
to_drop = set()
for col in upper_tri.columns:
    for row in upper_tri.index:
        if upper_tri.loc[row, col] > 0.95:
            # Drop whichever has higher mean correlation overall
            mean_r1 = corr_matrix[row].mean()
            mean_r2 = corr_matrix[col].mean()
            drop = row if mean_r1 > mean_r2 else col
            to_drop.add(drop)

if to_drop:
    print(f"  Removed {len(to_drop)} correlated features: {sorted(to_drop)}")
    all_features = [f for f in all_features if f not in to_drop]
    X = X[all_features]
else:
    print("  None found")

print(f"  Features after cleanup: {len(all_features)}")

# ── Step 3: Train model on all remaining features ────────────────
# Subsample for speed (GradientBoosting on 100k is slow)
train_idx = np.random.choice(len(df), size=min(30000, len(df)), replace=False)
X_train = X.iloc[train_idx]
y_train = y[train_idx]

print(f"\nStep 3: Training on {len(all_features)} features ({len(X_train):,} samples)...")

# Use XGBoost (GradientBoosting as fallback if xgboost not installed)
try:
    from xgboost import XGBClassifier
    clf = XGBClassifier(
        n_estimators=200, max_depth=5, random_state=RANDOM_SEED,
        subsample=0.8, use_label_encoder=False, eval_metric="mlogloss",
        verbosity=0
    )
    model_name = "XGBoost"
except ImportError:
    clf = GradientBoostingClassifier(
        n_estimators=200, max_depth=5, random_state=RANDOM_SEED, subsample=0.8
    )
    model_name = "GradientBoosting (XGBoost fallback)"

print(f"  Model: {model_name}")
clf.fit(X_train, y_train)

# ── Step 4: Rank features by importance ──────────────────────────
print("\nStep 4: Ranking features by importance...")
importances = pd.Series(clf.feature_importances_, index=all_features).sort_values(ascending=False)

print(f"\n  {'Feature':25s} {'Importance':>10s} {'Cumulative':>10s}")
print(f"  {'-'*47}")
cumsum = 0
for feat, imp in importances.items():
    cumsum += imp
    print(f"  {feat:25s} {imp:>10.4f} {cumsum:>10.4f}")

# ── Step 5: Select top features covering threshold ───────────────
cumulative = importances.cumsum()
selected = cumulative[cumulative <= CUM_IMPORTANCE_THRESHOLD].index.tolist()
# Include the feature that pushes past the threshold
if len(selected) < len(importances):
    selected.append(importances.index[len(selected)])

print(f"\nStep 5: Selected {len(selected)} features covering "
      f"{importances[selected].sum():.1%} of total importance")
print(f"  Features: {selected}")

# ── Step 6: Validate, compare all features vs selected ──────────
print(f"\nStep 6: Validating (3-fold CV on 20k subsample)...")

idx = np.random.choice(len(df), size=min(20000, len(df)), replace=False)
cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=RANDOM_SEED)

for name, feat_list in [("All features", all_features), ("Selected features", selected)]:
    X_val = df[feat_list].fillna(0).iloc[idx]
    y_val = y[idx]

    try:
        from xgboost import XGBClassifier
        clf_val = XGBClassifier(
            n_estimators=100, max_depth=5, random_state=RANDOM_SEED,
            subsample=0.8, use_label_encoder=False, eval_metric="mlogloss",
            verbosity=0
        )
    except ImportError:
        clf_val = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, random_state=RANDOM_SEED, subsample=0.8
        )

    y_pred = cross_val_predict(clf_val, X_val, y_val, cv=cv)
    print(f"\n  {name} ({len(feat_list)}):")
    print(classification_report(y_val, y_pred, target_names=le.classes_, digits=3))

# ── Step 7: Generate feature importance plot ─────────────────────
print("Step 7: Generating feature importance plot...")
feats_plot = selected[::-1]
imps_plot = [importances[f] for f in feats_plot]
cum_total = importances[selected].sum()

fig, ax = plt.subplots(figsize=(10, max(6, len(selected) * 0.5)))
bars = ax.barh(feats_plot, imps_plot, color="#2563eb", edgecolor="white", height=0.7)
ax.set_xlabel("Feature Importance", fontsize=12)
ax.set_title(f"XGBoost Feature Importance: Top {len(selected)} Features\n"
             f"(Cumulative: {cum_total:.1%} of total importance)",
             fontsize=13)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

for bar, val in zip(bars, imps_plot):
    ax.text(bar.get_width() + 0.003, bar.get_y() + bar.get_height() / 2,
            f"{val:.3f}", va="center", fontsize=9)

plt.tight_layout()
fig.savefig("feature_importance.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print("Saved feature_importance.png")

# ── Step 8: Save feature matrix ──────────────────────────────────
print("\nStep 8: Saving feature matrix...")
X_final = df[selected].fillna(0).copy()
X_final["attack_cat"] = df["attack_cat"]
X_final["label"] = df["label"]
X_final.to_csv("feature_matrix.csv", index=False)

print(f"Saved feature_matrix.csv: {X_final.shape}")
print(f"\nSelected features for XGBoost classifier:")
for i, feat in enumerate(selected, 1):
    print(f"  {i:2d}. {feat:25s} (importance: {importances[feat]:.4f})")
print(f"\nDone.")
