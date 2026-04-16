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

The other pipeline runs PCA before both DBSCAN and XGBoost, squeezing the features down to 24 principal components. For this project specifically, that's a problem.

Our proposal names this deliverable outright:

> "Produce a feature importance analysis identifying which of the 49 UNSW-NB15 features are most predictive of lateral movement, providing interpretability for the model decisions."

Once you PCA-transform the data, those 24 components are linear blends of every original feature. You can't say "sttl is the strongest signal for detecting Exploits" anymore. All you can say is "PC7 is important," which means nothing to a network security operator.

Here's our feature importance result without PCA:

```
sttl              0.7338   <- source TTL alone is 73% of model signal
dbytes            0.0361   <- destination bytes
ct_srv_dst        0.0322   <- connection frequency to same service+dst
smean             0.0309   <- mean source packet size
dmean             0.0269   <- mean destination packet size
...
```

That's actionable. A security team can look at it and understand that TTL values are the strongest indicator of attack traffic, because tools like Nmap produce different TTL signatures than normal OS traffic. PCA throws all of that away.

And XGBoost doesn't even need PCA. The code comment justifies it with "DBSCAN uses Euclidean distance which degrades in high dimensions." Sure, that's a reasonable argument for DBSCAN with 35+ features. But PCA also gets applied before XGBoost, and there it's pointless: tree models handle high dimensionality natively and never touch Euclidean distance. They split on individual features, so the curse of dimensionality doesn't bite them.

Our answer to DBSCAN's dimensionality concern isn't PCA. Instead we:

1. Use only 12 domain-relevant features rather than 35+
2. Add sttl and dttl, which sharpen cluster separation a lot
3. Tune eps automatically so it adapts to the feature space

The payoff: silhouette 0.51 with interpretable features, versus 0.33 with PCA components.

## What We Actually Use XGBoost For in Feature Selection

To be clear, we're not training the final XGBoost classifier in Phase 1. That comes later, in Phase 2, with SMOTE, hyperparameter tuning, and a proper train/test split.

What we did here was borrow XGBoost for one narrow question: out of these 35 features, which ones actually help separate Normal from Exploits from Reconnaissance?

Why importance instead of correlation filtering? The alternative pipeline leans on correlation-based selection, dropping features that correlate heavily with each other. That's genuinely useful, and we do it too as Step 2, but it only tells you which features are redundant. It says nothing about which features are useful for classification. Two features can be totally uncorrelated and both useless for spotting attacks; two correlated features might both be critical signals.

XGBoost importance measures the thing we care about directly: what helps classify attacks. Trained on all 35 features, it reported:

- sttl alone carries 73.4% of the classification signal
- the top 14 features cover 95.3% of total importance
- the remaining 21 features add up to just 4.7%, basically noise

We checked it: 14 features give identical F1 scores to all 35 (Exploits 0.932, Normal 0.986, Recon 0.818). So we drop 21 features at zero performance cost. This is the feature selection method the proposal describes, and it hands us the interpretable importance analysis we committed to.

## Updated Pipeline Results

### Preprocessing
- Frequency encoding (not LabelEncoder)
- Both train and test processed
- inf handling, ct_ftp_cmd cleanup, median fill

### DBSCAN Segmentation
| Metric | Old | Updated |
|--------|-----|---------|
| Features | 10 (manual) | 12 (domain-informed, includes sttl/dttl/state) |
| eps selection | Hardcoded 0.3 | Automated (k-distance + grid search + silhouette) |
| eps value | 0.3 | 0.3003 (auto-selected) |
| Clusters | 64 | 29 |
| Noise | 14.8% | 14.4% |
| Silhouette | 0.15 | 0.51 |
| Pure clusters (>80% one class) | unknown | 23/29 (79%) |

### Feature Selection
| Metric | Result |
|--------|--------|
| Starting features | 42 |
| After correlation removal | 35 |
| After XGBoost importance | 14 (95.3% cumulative importance) |
| Performance vs all 35 | Identical F1 scores |
| Top feature | sttl (73.4% importance) |

## What's Next (Phase 2)

All three scripts are finalized and produce consistent outputs. Phase 2 breaks down like this:

1. XGBoost classifier training (teammate): train on the 14 selected features with SMOTE oversampling. Target F1 > 0.85 per class.
2. Mininet topology (Kaivalya): build the virtual network with OpenFlow switches mapped to DBSCAN segments.
3. OpenFlow enforcement (teammate): deny-by-default policy that uses XGBoost output to block cross-segment Exploit/Recon traffic.
4. Integration (all of us): wire the full pipeline together and test end-to-end.

Deadline: April 8, 2026.
