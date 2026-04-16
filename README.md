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

```
src/        pipeline + controller + live-demo scripts
docs/       full project log, pipeline review, slides
results/    metrics, plots, classification report
dashboard/  static + live HTML dashboards (event_server.py feeds the live one)
```

## Running it

1. **Data.** Grab the [UNSW-NB15 dataset](https://research.unsw.edu.au/projects/unsw-nb15-dataset) (`UNSW_NB15_training-set.csv`, `UNSW_NB15_testing-set.csv`) and drop the files into `src/`. The datasets aren't committed since they're about 117 MB.
2. **ML pipeline** (any Linux/macOS/WSL2 box):
   ```bash
   pip install -r requirements.txt
   cd src
   python preprocess.py
   python feature_selection.py
   python dbscan_segmentation.py
   python train_xgboost.py
   python integration.py
   ```
3. **Network enforcement demo** (Mininet VM, Ubuntu 20.04):
   ```bash
   sudo pip3 install eventlet==0.30.2   # Ryu is incompatible with newer eventlet
   ryu-manager ryu_controller.py &
   sudo python3 mininet_topology.py
   ```
   For the live dashboard, run `event_server.py` next to `ryu_controller_live.py`, open `dashboard/zeroseg_dashboard_live.html`, and drive traffic with `attack_demo.py` from inside Mininet.

## Design decisions

A few calls worth explaining:

- **XGBoost over Isolation Forest.** The data is labeled, so a supervised model just wins. I also narrowed the scope to Exploits and Recon (the lateral-movement kill chain: scan, then pivot) after it became clear that general anomaly detection was a rabbit hole.
- **DBSCAN over K-Means.** I didn't want to pin down a segment count up front. Picking eps automatically from the k-distance elbow plus silhouette scoring surfaced 29 natural segments on its own.
- **Frequency encoding** for `proto`, `state`, and `service`. It keeps the frequency signal without the fake ordering that label encoding sneaks in, and it plays nicely with both a distance-based model (DBSCAN) and a tree-based one (XGBoost).
- **SMOTE.** Recon only had about 10k samples against 56k Normal, and without rebalancing the model basically ignores the minority class.

## Known limitations

- `sttl` carries 73.4% of the feature importance (it's really picking up OS-default TTL signatures), so this may not carry over to networks with a different OS mix than UNSW-NB15.
- The enforcement pipeline replays dataset flows. A real deployment would tap live traffic off a mirror port and pull the flow features online.
- The topology uses a static IP-to-segment mapping. In production you'd want dynamic host discovery instead.

## Credits

Built as a small team project. My part was preprocessing, feature selection, the integration pipeline, and the live dashboard; the DBSCAN segmentation, XGBoost training, Mininet topology, and Ryu controller were worked on together.
