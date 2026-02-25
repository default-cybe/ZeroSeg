"""
XGBoost Classifier Training and Evaluation
============================================
Trains a multiclass XGBoost classifier on the 14 selected features
to detect Normal, Exploits, and Reconnaissance traffic.
Evaluates on the held-out test set and generates all result plots.

Usage:
    python train_xgboost.py

Inputs:  feature_matrix.csv, filtered_testing.csv
Outputs: xgboost_model.json, classification_report.txt,
         confusion_matrix.png, roc_curves.png, results_summary.csv
"""

import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import (
    classification_report, confusion_matrix,
    roc_curve, auc, ConfusionMatrixDisplay
)
from imblearn.over_sampling import SMOTE
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import warnings, json
warnings.filterwarnings("ignore")

try:
    from xgboost import XGBClassifier
except ImportError:
    raise ImportError("Run: pip install xgboost imbalanced-learn")

RANDOM_SEED = 42
np.random.seed(RANDOM_SEED)

FEATURES = [
    "sttl", "dbytes", "ct_srv_dst", "smean", "dmean",
    "sbytes", "ct_dst_src_ltm", "swin", "service",
    "ct_srv_src", "trans_depth", "synack", "tcprtt", "response_body_len"
]

# ── Load training data ────────────────────────────────────────────
print("Loading training data...")
df_train = pd.read_csv("feature_matrix.csv")
print(f"  Training shape: {df_train.shape}")
print(f"  Classes: {df_train['attack_cat'].value_counts().to_dict()}")

le = LabelEncoder()
X_train = df_train[FEATURES].fillna(0).values
y_train = le.fit_transform(df_train["attack_cat"])
print(f"  Label encoding: {dict(zip(le.classes_, le.transform(le.classes_)))}")

# ── SMOTE oversampling for Reconnaissance ────────────────────────
print("\nApplying SMOTE to balance Reconnaissance class...")
smote = SMOTE(random_state=RANDOM_SEED, k_neighbors=5)
X_resampled, y_resampled = smote.fit_resample(X_train, y_train)
unique, counts = np.unique(y_resampled, return_counts=True)
for cls, cnt in zip(le.inverse_transform(unique), counts):
    print(f"  {cls}: {cnt:,}")

# ── Train XGBoost ─────────────────────────────────────────────────
print("\nTraining XGBoost classifier...")
clf = XGBClassifier(
    n_estimators=300,
    max_depth=6,
    learning_rate=0.1,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    gamma=0.1,
    reg_alpha=0.1,
    reg_lambda=1.0,
    random_state=RANDOM_SEED,
    use_label_encoder=False,
    eval_metric="mlogloss",
    verbosity=0,
    n_jobs=-1
)
clf.fit(X_resampled, y_resampled)
print("  Training complete.")

# ── Load and prepare test set ─────────────────────────────────────
print("\nLoading test set...")
df_test = pd.read_csv("filtered_testing.csv")
df_test = df_test[df_test["attack_cat"].isin(["Normal", "Exploits", "Reconnaissance"])]
print(f"  Test shape: {df_test.shape}")
print(f"  Test classes: {df_test['attack_cat'].value_counts().to_dict()}")

# Apply same frequency encoding as training for categorical features
# (service is already frequency-encoded in filtered_testing.csv from preprocess.py)
X_test = df_test[FEATURES].fillna(0).values
y_test = le.transform(df_test["attack_cat"])

# ── Evaluate ──────────────────────────────────────────────────────
print("\nEvaluating on test set...")
y_pred = clf.predict(X_test)
y_prob = clf.predict_proba(X_test)

report = classification_report(y_test, y_pred, target_names=le.classes_, digits=4)
print("\nClassification Report:")
print(report)

# Save report
with open("classification_report.txt", "w") as f:
    f.write("XGBoost Classifier: Test Set Evaluation\n")
    f.write("=" * 50 + "\n\n")
    f.write(f"Features used: {FEATURES}\n\n")
    f.write(f"Test set distribution:\n")
    for cat, cnt in df_test["attack_cat"].value_counts().items():
        f.write(f"  {cat}: {cnt:,}\n")
    f.write("\n" + report)
print("Saved classification_report.txt")

# ── Confusion Matrix ──────────────────────────────────────────────
print("\nGenerating confusion matrix...")
cm = confusion_matrix(y_test, y_pred)
fig, ax = plt.subplots(figsize=(8, 6))
disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=le.classes_)
disp.plot(ax=ax, colorbar=True, cmap="Blues")
ax.set_title("XGBoost Confusion Matrix: Test Set", fontsize=14, fontweight="bold", pad=15)
plt.tight_layout()
fig.savefig("confusion_matrix.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print("Saved confusion_matrix.png")

# ── ROC Curves ───────────────────────────────────────────────────
print("Generating ROC curves...")
fig, ax = plt.subplots(figsize=(8, 6))
colors = {"Normal": "#2ecc71", "Exploits": "#e74c3c", "Reconnaissance": "#f39c12"}

for i, cls in enumerate(le.classes_):
    fpr, tpr, _ = roc_curve((y_test == i).astype(int), y_prob[:, i])
    roc_auc = auc(fpr, tpr)
    ax.plot(fpr, tpr, label=f"{cls} (AUC = {roc_auc:.4f})",
            color=colors.get(cls, "blue"), linewidth=2)

ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="Random")
ax.set_xlabel("False Positive Rate", fontsize=12)
ax.set_ylabel("True Positive Rate", fontsize=12)
ax.set_title("ROC Curves: XGBoost Classifier", fontsize=14, fontweight="bold")
ax.legend(fontsize=11)
ax.grid(alpha=0.3)
plt.tight_layout()
fig.savefig("roc_curves.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print("Saved roc_curves.png")

# ── Save model ────────────────────────────────────────────────────
clf.save_model("xgboost_model.json")
print("Saved xgboost_model.json")

# ── Results summary ───────────────────────────────────────────────
from sklearn.metrics import precision_score, recall_score, f1_score
results = []
for i, cls in enumerate(le.classes_):
    mask = y_test == i
    precision = precision_score(y_test == i, y_pred == i)
    recall = recall_score(y_test == i, y_pred == i)
    f1 = f1_score(y_test == i, y_pred == i)
    results.append({"class": cls, "precision": round(precision, 4),
                    "recall": round(recall, 4), "f1": round(f1, 4),
                    "support": int(mask.sum())})

df_results = pd.DataFrame(results)
df_results.to_csv("results_summary.csv", index=False)
print("Saved results_summary.csv")

print("\n" + "="*50)
print("FINAL RESULTS SUMMARY")
print("="*50)
for r in results:
    status = "PASS" if r["f1"] >= 0.85 else "NEEDS TUNING"
    print(f"  {r['class']:20s} | F1: {r['f1']:.4f} | Precision: {r['precision']:.4f} | Recall: {r['recall']:.4f} | {status}")
print("="*50)
print("\nDone.")
