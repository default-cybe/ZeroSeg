# ZeroSeg: AI-Powered Microsegmentation for Zero Trust Networks

ZeroSeg is a machine-learning driven take on network microsegmentation. It watches for lateral movement (Reconnaissance and Exploit traffic) and, when it sees something bad, pushes a deny-by-default rule through an SDN controller automatically. No human in the loop.

I built it as a hands-on way to dig into Zero Trust enforcement and see how far you can get wiring an ML classifier straight into an OpenFlow control plane.

## How it works

```
UNSW-NB15 Dataset
    → preprocess.py           filter to Normal/Exploits/Recon, frequency-encode categoricals
    → feature_selection.py    variance + correlation pruning, XGBoost importance → top 14 features
    → dbscan_segmentation.py  discover network segments (auto-eps DBSCAN, 29 segments)
    → train_xgboost.py        3-class attack classifier (SMOTE-balanced)
    → integration.py          bridge ML verdicts to enforcement
    → ryu_controller.py       OpenFlow 1.3 deny-by-default policy engine
    → mininet_topology.py     6-host, 3-segment simulated network
```

The controller runs a layered policy. Traffic inside a segment is allowed. Cross-segment traffic from an untrusted segment gets dropped at priority 10. And anything the XGBoost model flags as Exploit or Recon gets a priority-20 drop rule that overrides everything else.

## Results

| Class | Precision | Recall | F1 |
|-------|-----------|--------|-----|
| Normal | 0.994 | 0.966 | 0.980 |
| Exploits | 0.857 | 0.947 | 0.900 |
| Reconnaissance | 0.866 | 0.841 | 0.853 |
| **Overall accuracy** | | | **95.31%** |

For the end-to-end enforcement test I replayed a 500-flow attack sequence: 93.4% enforcement accuracy, and every nmap scan and cross-segment exploit attempt out of the attacker segment got blocked (100%).

Plots and reports live in [`results/`](results/): confusion matrix, ROC curves, the DBSCAN segment visualization, feature importance, and a live attack timeline.

## Repo layout
