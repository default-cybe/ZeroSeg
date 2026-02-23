"""
DBSCAN Host Segmentation for AI-Powered Microsegmentation
==========================================================
Groups hosts into logical network segments based on communication behavior.
Uses automated eps selection via k-distance elbow detection.

Usage:
    python dbscan_segmentation.py

Inputs:  filtered_training.csv
Outputs: segmented_data.csv, dbscan_segments.png, k_distance_graph.png
"""

import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import DBSCAN
from sklearn.decomposition import PCA
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import silhouette_score
from collections import Counter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore")

RANDOM_SEED = 42
np.random.seed(RANDOM_SEED)

# ── Host behavior features for segmentation ──────────────────────
# These describe HOW a host communicates on the network:
#   proto, service, state  → what kind of traffic
#   sttl, dttl             → OS/host type fingerprinting (different OS = different TTL)
#   spkts, dpkts           → packet volume in each direction
#   sbytes, dbytes         → data volume in each direction
#   ct_srv_src, ct_srv_dst → connection frequency to same services
#   ct_dst_src_ltm         → recent connection history

SEGMENT_FEATURES = [
    "proto", "service", "state", "sttl", "dttl",
    "spkts", "dpkts", "sbytes", "dbytes",
    "ct_srv_src", "ct_srv_dst", "ct_dst_src_ltm"
]

DBSCAN_SUBSAMPLE = 25000  # DBSCAN is O(n²), subsample for fitting
MIN_SAMPLES = 50


def find_optimal_eps(X_scaled, subsample_idx):
    """Find optimal eps using k-distance elbow + grid search with silhouette scoring."""

    X_sub = X_scaled[subsample_idx]
    n_dims = X_sub.shape[1]

    # k = 2 * dimensions (rule of thumb for DBSCAN), capped at 50
    k = min(max(2 * n_dims, 5), 50, len(X_sub) - 1)
    print(f"  Computing k-distance graph (k={k})...")

    nn = NearestNeighbors(n_neighbors=k)
    nn.fit(X_sub)
    distances, _ = nn.kneighbors(X_sub)
    k_distances = np.sort(distances[:, k - 1])

    print(f"  k-distance percentiles:")
    for p in [25, 50, 75, 90, 95]:
        print(f"    {p}th: {np.percentile(k_distances, p):.4f}")

    # Test eps candidates from percentiles
    candidate_pcts = [50, 60, 65, 70, 75, 80, 85, 90, 95]
    eps_candidates = sorted(set(np.percentile(k_distances, p) for p in candidate_pcts))

    print(f"\n  Testing {len(eps_candidates)} eps candidates...")

    results = []
    for eps_val in eps_candidates:
        db = DBSCAN(eps=eps_val, min_samples=MIN_SAMPLES)
        labels = db.fit_predict(X_sub)
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        noise_pct = (labels == -1).mean() * 100

        sil = None
        if n_clusters >= 2:
            valid = labels != -1
            if valid.sum() > 100:
                samp_idx = np.where(valid)[0]
                if len(samp_idx) > 8000:
                    samp_idx = np.random.choice(samp_idx, size=8000, replace=False)
                sil = silhouette_score(X_sub[samp_idx], labels[samp_idx])

        # Count pure clusters (>80% one class)
        pure = 0
        sub_cats = df.iloc[subsample_idx]["attack_cat"].values
        if n_clusters >= 2:
            for cid in set(labels):
                if cid == -1:
                    continue
                mask = labels == cid
                cat_counts = Counter(sub_cats[mask])
                total = sum(cat_counts.values())
                if total > 0 and max(cat_counts.values()) / total > 0.8:
                    pure += 1

        results.append({
            "eps": eps_val, "n_clusters": n_clusters, "noise_pct": noise_pct,
            "silhouette": sil, "labels": labels, "pure": pure
        })

        sil_str = f"{sil:.4f}" if sil is not None else "N/A"
        print(f"    eps={eps_val:.4f} -> {n_clusters:>3} clusters | "
              f"noise={noise_pct:>5.1f}% | sil={sil_str} | pure={pure}/{n_clusters}")

    # Select best: highest silhouette with >=2 clusters and noise < 25%
    valid_results = [r for r in results
                     if r["n_clusters"] >= 2 and r["silhouette"] is not None
                     and r["noise_pct"] < 25]

    if valid_results:
        best = max(valid_results, key=lambda r: r["silhouette"])
    else:
        multi = [r for r in results if r["n_clusters"] >= 2]
        best = min(multi, key=lambda r: r["noise_pct"]) if multi else results[-1]

    # Save k-distance plot
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(range(len(k_distances)), k_distances, color="#3498db", linewidth=0.5, alpha=0.8)
    ax.axhline(y=best["eps"], color="#e74c3c", linestyle="--", linewidth=2,
               label=f"Selected eps = {best['eps']:.4f}")
    ax.set_title(f"k-Distance Graph (k={k})", fontsize=14, fontweight="bold")
    ax.set_xlabel("Points (sorted by distance)")
    ax.set_ylabel(f"{k}-th Nearest Neighbor Distance")
    ax.legend(fontsize=11)
    ax.grid(alpha=0.3)
    fig.savefig("k_distance_graph.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Saved k_distance_graph.png")

    return best


# ── Load data ────────────────────────────────────────────────────
print("Loading data...")
df = pd.read_csv("filtered_training.csv")
X = df[SEGMENT_FEATURES].fillna(0)
print(f"  Shape: {X.shape}")
print(f"  Features: {SEGMENT_FEATURES}")

# ── Scale ────────────────────────────────────────────────────────
print("\nScaling features...")
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# ── Subsample for DBSCAN fitting ─────────────────────────────────
n_samples = len(X_scaled)
if n_samples > DBSCAN_SUBSAMPLE:
    print(f"\nSubsampling {DBSCAN_SUBSAMPLE:,} from {n_samples:,} (stratified)...")
    subsample_idx = []
    for cat in df["attack_cat"].unique():
        cat_idx = df.index[df["attack_cat"] == cat].tolist()
        n_cat = int(DBSCAN_SUBSAMPLE * len(cat_idx) / n_samples)
        sampled = np.random.choice(cat_idx, size=n_cat, replace=False)
        subsample_idx.extend(sampled.tolist())
    np.random.shuffle(subsample_idx)
    subsample_idx = subsample_idx[:DBSCAN_SUBSAMPLE]
else:
    subsample_idx = list(range(n_samples))

# ── Find optimal eps ─────────────────────────────────────────────
print(f"\nFinding optimal eps...")
best = find_optimal_eps(X_scaled, subsample_idx)

eps_optimal = best["eps"]
labels_sub = best["labels"]
sil_score = best["silhouette"]
n_clusters = best["n_clusters"]

print(f"\n{'='*50}")
print(f"  Selected: eps={eps_optimal:.4f}, min_samples={MIN_SAMPLES}")
print(f"  Clusters: {n_clusters}")
print(f"  Noise:    {best['noise_pct']:.1f}%")
print(f"  Silhouette: {sil_score:.4f}" if sil_score else "  Silhouette: N/A")
print(f"  Pure clusters: {best['pure']}/{n_clusters}")
print(f"{'='*50}")

# ── Assign clusters to full dataset via nearest-neighbor ─────────
print(f"\nAssigning clusters to full dataset ({n_samples:,} points)...")
full_labels = np.full(n_samples, -1, dtype=int)
X_sub = X_scaled[subsample_idx]

# Set subsample labels
for pos, lbl in zip(subsample_idx, labels_sub):
    full_labels[pos] = lbl

# Assign remaining points via nearest-neighbor (using non-noise points only)
remaining = np.array([i for i in range(n_samples) if i not in set(subsample_idx)])
if len(remaining) > 0:
    # Only use non-noise subsample points as NN references
    non_noise_mask = labels_sub != -1
    X_sub_clean = X_sub[non_noise_mask]
    labels_sub_clean = labels_sub[non_noise_mask]
    
    nn = NearestNeighbors(n_neighbors=1)
    nn.fit(X_sub_clean)
    dists, nn_idx = nn.kneighbors(X_scaled[remaining])
    
    # Assign to nearest non-noise cluster, but mark as noise if too far
    dist_threshold = eps_optimal * 2  # Points far from any cluster stay noise
    for i, ri in enumerate(remaining):
        if dists[i, 0] <= dist_threshold:
            full_labels[ri] = labels_sub_clean[nn_idx[i, 0]]
        # else stays -1 (noise → deny-by-default)
    
    assigned = sum(1 for i, ri in enumerate(remaining) if full_labels[ri] != -1)
    print(f"  Assigned {assigned:,} of {len(remaining):,} remaining points via nearest-neighbor")
    print(f"  {len(remaining) - assigned:,} remaining points kept as noise (too far from clusters)")

df["segment"] = full_labels

# ── Cluster composition ──────────────────────────────────────────
print(f"\nCluster Composition:")
print(f"  {'Cluster':>8s} | {'Size':>7s} | {'Normal':>8s} | {'Exploits':>8s} | {'Recon':>8s} | Dominant")
print(f"  {'-'*72}")

for cid in sorted(df["segment"].unique()):
    mask = df["segment"] == cid
    size = mask.sum()
    cats = df.loc[mask, "attack_cat"]
    cat_counts = cats.value_counts()
    normal_pct = 100 * cat_counts.get("Normal", 0) / size
    exploits_pct = 100 * cat_counts.get("Exploits", 0) / size
    recon_pct = 100 * cat_counts.get("Reconnaissance", 0) / size
    dominant = cat_counts.index[0]
    label = "Noise" if cid == -1 else str(cid)
    print(f"  {label:>8s} | {size:>7,} | {normal_pct:>7.1f}% | "
          f"{exploits_pct:>7.1f}% | {recon_pct:>7.1f}% | {dominant}")

# ── PCA Visualization ────────────────────────────────────────────
print("\nGenerating PCA visualization...")
pca = PCA(n_components=2)
X_pca = pca.fit_transform(X_scaled)

fig, axes = plt.subplots(1, 2, figsize=(20, 8))

# Left: DBSCAN clusters
ax = axes[0]
cmap = plt.colormaps.get_cmap("tab20")
for cid in sorted(df["segment"].unique()):
    mask = df["segment"] == cid
    if cid == -1:
        ax.scatter(X_pca[mask, 0], X_pca[mask, 1], c="lightgray", s=1, alpha=0.3, label="Noise")
    else:
        ax.scatter(X_pca[mask, 0], X_pca[mask, 1], color=cmap(cid % 20), s=1, alpha=0.5)
ax.set_title(f"DBSCAN Segments (eps={eps_optimal:.2f}, {n_clusters} clusters)", fontsize=13, fontweight="bold")
ax.set_xlabel("PCA Component 1")
ax.set_ylabel("PCA Component 2")
ax.grid(alpha=0.3)

# Right: ground truth
ax = axes[1]
attack_colors = {"Normal": "#2ecc71", "Exploits": "#e74c3c", "Reconnaissance": "#f39c12"}
for cat, color in attack_colors.items():
    mask = df["attack_cat"] == cat
    ax.scatter(X_pca[mask, 0], X_pca[mask, 1], c=color, s=1, alpha=0.4, label=cat)
ax.set_title("Ground Truth Labels", fontsize=13, fontweight="bold")
ax.set_xlabel("PCA Component 1")
ax.set_ylabel("PCA Component 2")
ax.legend(fontsize=10, markerscale=8)
ax.grid(alpha=0.3)

plt.tight_layout()
fig.savefig("dbscan_segments.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print("Saved dbscan_segments.png")

# ── Save ─────────────────────────────────────────────────────────
df.to_csv("segmented_data.csv", index=False)

print(f"\nSaved segmented_data.csv")
print(f"\nSummary:")
print(f"  Features used:  {len(SEGMENT_FEATURES)} ({', '.join(SEGMENT_FEATURES)})")
print(f"  eps:            {eps_optimal:.4f}")
print(f"  min_samples:    {MIN_SAMPLES}")
print(f"  Clusters:       {n_clusters}")
print(f"  Noise:          {(df['segment'] == -1).sum():,} ({(df['segment'] == -1).mean()*100:.1f}%)")
print(f"  Silhouette:     {sil_score:.4f}" if sil_score else f"  Silhouette:     N/A")
print(f"  Pure clusters:  {best['pure']}/{n_clusters}")
print(f"\nDone.")
