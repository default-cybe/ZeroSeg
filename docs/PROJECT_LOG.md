# AI-Powered Microsegmentation for Zero Trust Networks
## Project Log

A small team project.  
**Last Updated:** April 8, 2026

---

## Project Overview

We are building an automated microsegmentation system that enforces Zero Trust security on a network using machine learning. The system detects two specific lateral movement attack vectors, Exploit and Reconnaissance traffic, from the UNSW-NB15 dataset and automatically blocks them using a deny-by-default OpenFlow enforcement layer running in Mininet.

**Stack:** Python · XGBoost · DBSCAN · Mininet · Ryu OpenFlow · UNSW-NB15 dataset

**Pipeline:**
```
UNSW-NB15 Dataset
    → preprocess.py          (filter + encode)
    → feature_selection.py   (select top 14 features)
    → dbscan_segmentation.py (discover network segments)
    → train_xgboost.py       (train attack classifier)
    → integration.py         (connect ML to enforcement)
    → ryu_controller.py      (OpenFlow deny-by-default)
    → mininet_topology.py    (simulate network)
```

---

## Timeline

| Date | Milestone |
|------|-----------|
| Jan 30, 2026 | Team formed |
| Feb 6, 2026 | Project idea drafted |
| Feb 20, 2026 | Project proposal written |
| Feb 23, 2026 | Review feedback: narrow attack scope |
| Feb 23, 2026 | Remote servers offered + CORE suggestion |
| Mar 7, 2026 | Preprocessing complete |
| Mar 8, 2026 | Mininet installed and verified on WSL2 |
| Mar 11, 2026 | Feature selection and upgraded DBSCAN complete |
| Mar 13, 2026 | Progress Update 1 submitted |
| Apr 8, 2026 | XGBoost trained, Mininet topology + OpenFlow live, integration complete |
| Apr 8, 2026 | Progress Update 2 submitted |
| Apr 22, 2026 | Demo presentation |
| Apr 29, 2026 | Final write-up |

---

## Review Feedback Log

### Feb 23, 2026: Proposal Feedback
> "Do you have specific attack vectors in mind? General anomaly detection is very hard, so I imagine you'll be focusing on a smaller attack surface."

**Response:** Scoped to Exploits and Reconnaissance only. These directly represent the lateral movement kill chain: Recon is the scan phase, Exploit is the pivot phase. Switched from Isolation Forest (unsupervised) to XGBoost (supervised on labeled data).

### Feb 23, 2026: Server Offer
> "I have multiple servers that can be made available remotely. There might be performance/scaling tradeoffs between Mininet and CORE due to different levels of virtualization."

**Response:** Started with Mininet (already working). Will evaluate CORE if performance becomes a bottleneck. Server offer noted as fallback.

---

## Phase 1: Data Preparation and Segmentation (Feb 20 to Mar 13) ✓ COMPLETE

### Step 1: Preprocessing (`preprocess.py`)
**Completed:** March 7, 2026 | **Owner:** Kaivalya

- Filtered UNSW-NB15 to 3 classes: Normal, Exploits, Reconnaissance
- Dropped identity columns: `id`, `srcip`, `sport`, `dstip`, `dsport`
- Frequency-encoded categoricals: `proto`, `state`, `service`
- Filled missing values with training medians

**Results:**
| Class | Training | Testing |
|-------|----------|---------|
| Normal | 56,000 | 37,000 |
| Exploits | 33,393 | 11,132 |
| Reconnaissance | 10,491 | 3,496 |
| **Total** | **99,884** | **51,628** |

**Why frequency encoding:** Preserves relative category frequency as a signal. Better than label encoding (which implies false ordinal relationships) for both DBSCAN (distance-based) and XGBoost (tree-based).

---

### Step 2: Feature Selection (`feature_selection.py`)
**Completed:** March 11, 2026 | **Owner:** Kaivalya

- Removed zero-variance features
- Removed highly correlated features (|r| > 0.95)
- Trained XGBoost on 30k subsample, ranked by importance
- Selected top features covering 95% cumulative importance

**Selected 14 features (95.3% cumulative importance):**
| Rank | Feature | Importance |
|------|---------|------------|
| 1 | `sttl` | 0.734 |
| 2 | `dbytes` | 0.036 |
| 3 | `ct_srv_dst` | 0.032 |
| 4 | `smean` | 0.031 |
| 5 | `dmean` | 0.027 |
| 6 | `sbytes` | 0.022 |
| 7 | `ct_dst_src_ltm` | 0.016 |
| 8 | `swin` | 0.014 |
| 9 | `service` | 0.013 |
| 10 | `ct_srv_src` | 0.008 |
| 11 | `trans_depth` | 0.007 |
| 12 | `synack` | 0.005 |
| 13 | `tcprtt` | 0.005 |
| 14 | `response_body_len` | 0.004 |

**Notable finding:** `sttl` dominates at 73.4% importance. Different OS types use different default TTL values (Linux=64, Windows=128, Cisco=255). Exploit/Recon traffic often originates from specific OS types with distinct TTL signatures, which makes it a strong discriminating feature for lateral movement.

---

### Step 3: DBSCAN Host Segmentation (`dbscan_segmentation.py`)
**Completed:** March 11, 2026 | **Owner:** Teammate

- Subsampled 25,000 records (stratified) for DBSCAN fitting
- Automated eps selection via k-distance elbow + silhouette scoring
- Assigned remaining points via nearest-neighbor

**Results:**
- Optimal eps: 0.3003 (auto-selected, k=24)
- Clusters discovered: **29 segments**
- Noise points (segment -1): deny-by-default hosts

**Upgrade from initial run:** First run used eps=1.0 manually → 15 segments. Upgraded to automated eps selection → 29 clusters with better separation. Added side-by-side PCA visualization (segments vs ground truth).

---

## Phase 2: Model Training, Network Simulation, Integration (Mar 13 to Apr 8) ✓ COMPLETE

### Step 4: XGBoost Training (`train_xgboost.py`)
**Completed:** April 8, 2026 | **Owner:** Teammate

- Loaded `feature_matrix.csv` (14 selected features, 99,884 rows)
- Applied SMOTE oversampling, balancing all 3 classes to 56,000 each
- Trained XGBoost with tuned hyperparameters
- Evaluated on held-out `filtered_testing.csv` (51,628 rows)

**Hyperparameters:**
```python
n_estimators=300, max_depth=6, learning_rate=0.1,
subsample=0.8, colsample_bytree=0.8,
min_child_weight=5, gamma=0.1,
reg_alpha=0.1, reg_lambda=1.0
```

**Test Set Results:**
| Class | Precision | Recall | F1 | Support | Status |
|-------|-----------|--------|----|---------|--------|
| Exploits | 0.8574 | 0.9472 | **0.9000** | 11,132 | PASS |
| Normal | 0.9940 | 0.9655 | **0.9796** | 37,000 | PASS |
| Reconnaissance | 0.8662 | 0.8407 | **0.8532** | 3,496 | PASS |
| **Overall** | | | **0.9531** | 51,628 | ALL PASS |

All three classes exceeded the F1 > 0.85 target. Overall accuracy: 95.31%.

**Why SMOTE:** Reconnaissance had only 10,491 samples vs 56,000 Normal. Without balancing the model would ignore Reconnaissance. SMOTE synthesizes new samples by interpolating between existing ones.

**Outputs generated:** `xgboost_model.json`, `confusion_matrix.png`, `roc_curves.png`, `classification_report.txt`, `results_summary.csv`

---

### Step 5: Mininet Topology (`mininet_topology.py`)
**Completed:** April 8, 2026 | **Owner:** Teammate

**Environment:** VMware Workstation, Mininet 2.3.0 VM (Ubuntu 20.04), Ryu OpenFlow controller

**Topology:**
```
Segment 0 (Normal):   h1=10.0.0.1, h2=10.0.0.2  → switch s1 → core s0
Segment 1 (App):      h3=10.0.1.1, h4=10.0.1.2  → switch s2 → core s0
Segment 2 (Attacker): h5=10.0.2.1, h6=10.0.2.2  → switch s3 → core s0
```

**Connectivity test results:**
| Test | Result |
|------|--------|
| h1 ↔ h2 (same segment) | 0% dropped: ALLOWED |
| h3 ↔ h4 (same segment) | 0% dropped: ALLOWED |
| h5 → h1 (cross segment, Exploit origin) | 100% dropped: BLOCKED |
| h5 → h3 (cross segment, Recon) | 100% dropped: BLOCKED |
| h5 nmap scan of 10.0.0.0/24 | 0 hosts up: BLOCKED |
| h5 ping to h1 (Exploit attempt) | 100% loss: BLOCKED |
