# Pipeline Review: Addressing the Feedback

**From:** Kaivalya  
**Re:** Pipeline comparison and updated approach

## Summary

I went through the feedback on my pipeline. A few of the points were fair, and I've already fixed those. But some of the criticisms come from a misread of how the architecture actually works, and the alternative pipeline has a real problem of its own (PCA) that clashes with what we promised to deliver. Here's the whole breakdown.

## What Was Valid and What's Fixed

### 1. LabelEncoder for categoricals (FIXED)

The criticism: LabelEncoder assigns arbitrary integers (tcp=3, udp=4), which invents fake ordinal relationships and distorts DBSCAN's Euclidean distances.

That one was right. It was a real issue.

The fix: `preprocess.py` now uses frequency encoding, so each category is swapped for how often it shows up in the training set. That keeps the numeric relationships meaningful (common protocols end up with higher values) and behaves well for both the distance-based model (DBSCAN) and the tree-based one (XGBoost). The test set is encoded with the training set's frequency map so nothing leaks across.

```python
# Updated approach
freq_map = df_train[col].value_counts(normalize=True).to_dict()
df_train[col] = df_train[col].map(freq_map).fillna(0).astype(float)
df_test[col]  = df_test[col].map(freq_map).fillna(0).astype(float)
```

### 2. "Supervised feature selection for unsupervised clustering is data leakage" (incorrect)

The criticism: using GradientBoosting/XGBoost (trained on `attack_cat` labels) to pick features for DBSCAN is leakage, because the unsupervised step is indirectly leaning on labels.

This misreads the pipeline. DBSCAN and XGBoost run on completely separate feature sets for completely different jobs:

| Component | Purpose | Features | How selected |
|-----------|---------|----------|-------------|
| DBSCAN | Segment hosts by communication behavior | 12 host-behavior features (proto, service, state, sttl, dttl, spkts, dpkts, sbytes, dbytes, ct_srv_src, ct_srv_dst, ct_dst_src_ltm) | Domain knowledge: these describe how a host talks on the network |
| XGBoost | Classify individual flows as attack or normal | 14 importance-selected features (sttl, dbytes, ct_srv_dst, smean, dmean, sbytes, etc.) | Model-based importance ranking |

The XGBoost feature selection never feeds into DBSCAN. DBSCAN's features are chosen by domain reasoning about what describes host communication patterns, not by any supervised model. They're two independent steps, and the proposal spells them out that way.

Leakage would be DBSCAN using attack labels while clustering, which it doesn't. It only ever sees traffic-behavior features.

### 3. "DBSCAN uses 10 features that don't match the 12 selected features" (intentional)

The criticism: the feature sets are inconsistent between scripts, so it's a bug.

It's not a bug, it's the design. DBSCAN is answering "which hosts behave similarly?" (communication patterns). XGBoost is answering "is this flow malicious?" (attack signatures). Different questions, so different features.

The updated DBSCAN now uses 12 features:
`proto, service, state, sttl, dttl, spkts, dpkts, sbytes, dbytes, ct_srv_src, ct_srv_dst, ct_dst_src_ltm`

XGBoost uses 14 features:
`sttl, dbytes, ct_srv_dst, smean, dmean, sbytes, ct_dst_src_ltm, swin, service, ct_srv_src, trans_depth, synack, tcprtt, response_body_len`

They overlap (sttl, sbytes, dbytes, ct_srv_src, ct_srv_dst, ct_dst_src_ltm, service) because those are broadly useful network features. But each set carries features the other doesn't, which is exactly what we want.

### 4. Hardcoded eps=0.3 with no methodology (FIXED)

The criticism: no k-distance graph or silhouette analysis to justify the eps value. Fair.

The fix: `dbscan_segmentation.py` now selects eps automatically:

1. Computes the k-distance graph (k = 2 × dimensions = 24)
2. Tests 9 eps candidates drawn from percentiles of the k-distance distribution
3. Scores each one with silhouette plus cluster purity
4. Picks the best eps that keeps at least 2 clusters and noise under 25%

On our data:
```
eps=0.3003 (automatically selected)
29 clusters
14.4% noise
Silhouette: 0.5094
Pure clusters: 23/29 (79%)
```

The k-distance graph and every candidate result get saved as outputs for the write-up.

### 5. Doesn't process the test set (FIXED)

The criticism: only the training data was preprocessed, so holdout validation was impossible. Valid.

The fix: `preprocess.py` now runs both train and test through the same transformations. Frequency maps and median fill values come from training data only and get applied to both, so there's no test-to-train leakage.

```
Saved filtered_training.csv: (99884, 44)
Saved filtered_testing.csv:  (51628, 44)
```

## The Problem With the Alternative Pipeline: PCA Kills Interpretability

