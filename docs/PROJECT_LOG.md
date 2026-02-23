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

