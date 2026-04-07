"""
Integration: XGBoost → OpenFlow Enforcement
=============================================
Reads live traffic flows, classifies them with XGBoost,
and triggers OpenFlow block rules for detected attacks.

This script bridges the ML detection layer and the network enforcement layer.
In a real deployment this would tap live traffic. Here it simulates
a traffic stream from filtered_testing.csv and shows the full pipeline.

Usage:
    python integration.py

Inputs:  xgboost_model.json, filtered_testing.csv
Outputs: integration_log.csv, integration_log.txt, attack_timeline.png
"""

import pandas as pd
import numpy as np
import logging
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime
from xgboost import XGBClassifier
from sklearn.preprocessing import LabelEncoder
import warnings
warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("integration_log.txt"),
        logging.StreamHandler()
    ]
)
LOG = logging.getLogger("Integration")

FEATURES = [
    "sttl", "dbytes", "ct_srv_dst", "smean", "dmean",
    "sbytes", "ct_dst_src_ltm", "swin", "service",
    "ct_srv_src", "trans_depth", "synack", "tcprtt", "response_body_len"
]

# Simulated host IP mapping for the Mininet topology
SEGMENT_IPS = {
    "Normal":          ["10.0.0.1", "10.0.0.2"],
    "Exploits":        ["10.0.2.1"],  # attacker segment
    "Reconnaissance":  ["10.0.2.2"],  # attacker segment
}
DEST_IPS = {
    "Normal":          ["10.0.0.2", "10.0.1.1"],
    "Exploits":        ["10.0.0.1", "10.0.1.1"],  # targeting segments 0 and 1
    "Reconnaissance":  ["10.0.0.1", "10.0.1.1", "10.0.1.2"],
}


class XGBoostEnforcer:
    """
    Loads a trained XGBoost model and classifies traffic flows.
    Triggers OpenFlow block rules for detected attacks.
    """

    def __init__(self, model_path="xgboost_model.json"):
        LOG.info("Loading XGBoost model from %s", model_path)
        self.clf = XGBClassifier()
        self.clf.load_model(model_path)

        # Label encoder must match training order
        self.le = LabelEncoder()
        self.le.classes_ = np.array(["Exploits", "Normal", "Reconnaissance"])

        self.blocked_flows = set()
        self.event_log = []
        self.stats = {"allowed": 0, "exploit_blocked": 0, "recon_blocked": 0, "total": 0}
        LOG.info("Model loaded. Classes: %s", list(self.le.classes_))

    def classify_flow(self, flow_features, src_ip, dst_ip):
        """
        Classify a single flow and trigger enforcement if attack detected.
        Returns: (prediction, confidence, action)
        """
        X = np.array(flow_features).reshape(1, -1)
        pred_idx = self.clf.predict(X)[0]
        pred_proba = self.clf.predict_proba(X)[0]
        prediction = self.le.inverse_transform([pred_idx])[0]
        confidence = float(pred_proba[pred_idx])

        self.stats["total"] += 1

        if prediction in ["Exploits", "Reconnaissance"]:
            action = self._enforce_block(src_ip, dst_ip, prediction, confidence)
        else:
            action = "ALLOW"
            self.stats["allowed"] += 1

        # Log event
        self.event_log.append({
            "timestamp": datetime.now().isoformat(),
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "prediction": prediction,
            "confidence": round(confidence, 4),
            "action": action
        })

        return prediction, confidence, action

    def _enforce_block(self, src_ip, dst_ip, attack_type, confidence):
        """
        Install block rule via OpenFlow controller.
        In production this calls the Ryu REST API.
        Here we log the enforcement action.
        """
        flow_key = (src_ip, dst_ip)

        if flow_key not in self.blocked_flows:
            self.blocked_flows.add(flow_key)

            # In production: POST to Ryu REST API
            # requests.post("http://localhost:8080/stats/flowentry/add", json=flow_rule)
            # For demo: log the enforcement action
            LOG.warning(
                "ATTACK DETECTED | %s | %s -> %s | confidence=%.2f%% | BLOCKING",
                attack_type, src_ip, dst_ip, confidence * 100
            )

            if attack_type == "Exploits":
                self.stats["exploit_blocked"] += 1
            else:
                self.stats["recon_blocked"] += 1

            return "BLOCK_NEW"
        else:
            LOG.info("REPEAT ATTACK | %s -> %s already blocked", src_ip, dst_ip)
            return "BLOCK_EXISTING"


def simulate_pipeline(enforcer, df_test, n_flows=500):
    """
    Simulate a traffic stream with a mix of normal and attack flows.
    Models a realistic attack sequence: Recon first, then Exploit.
    """
    LOG.info("Starting pipeline simulation with %d flows", n_flows)
    LOG.info("Simulating attack sequence: Recon scan → Exploit attempt")

    # Build attack sequence: 60% normal, 20% recon, 20% exploit
    normal_rows = df_test[df_test["attack_cat"] == "Normal"].sample(
        n=int(n_flows * 0.6), random_state=42)
    recon_rows = df_test[df_test["attack_cat"] == "Reconnaissance"].sample(
        n=min(int(n_flows * 0.2), len(df_test[df_test["attack_cat"] == "Reconnaissance"])),
        random_state=42)
    exploit_rows = df_test[df_test["attack_cat"] == "Exploits"].sample(
        n=int(n_flows * 0.2), random_state=42)

    # Interleave: normal → recon scan → exploit attempt
    sequence = pd.concat([
        normal_rows.iloc[:int(n_flows * 0.3)],
        recon_rows,
        normal_rows.iloc[int(n_flows * 0.3):int(n_flows * 0.5)],
        exploit_rows,
        normal_rows.iloc[int(n_flows * 0.5):]
    ]).reset_index(drop=True)

    LOG.info("Flow sequence: %d normal, %d recon, %d exploit",
             len(normal_rows), len(recon_rows), len(exploit_rows))

    results = []
    for idx, row in sequence.iterrows():
        true_label = row["attack_cat"]
        features = [row.get(f, 0) for f in FEATURES]

        # Assign IPs based on true label
        src_ips = SEGMENT_IPS.get(true_label, ["10.0.0.1"])
        dst_ips = DEST_IPS.get(true_label, ["10.0.0.2"])
        src_ip = src_ips[idx % len(src_ips)]
        dst_ip = dst_ips[idx % len(dst_ips)]

        prediction, confidence, action = enforcer.classify_flow(features, src_ip, dst_ip)

        correct = prediction == true_label
        results.append({
            "flow_id": idx,
            "true_label": true_label,
            "prediction": prediction,
            "confidence": round(confidence, 4),
            "src_ip": src_ip,
            "dst_ip": dst_ip,
            "action": action,
            "correct": correct
        })

        # Print progress every 50 flows
        if (idx + 1) % 50 == 0:
            LOG.info("Processed %d/%d flows | blocked=%d",
                     idx + 1, len(sequence),
                     enforcer.stats["exploit_blocked"] + enforcer.stats["recon_blocked"])

    return pd.DataFrame(results)


def generate_timeline_plot(results_df):
    """Generate attack timeline visualization."""
    LOG.info("Generating attack timeline plot...")

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle("Integration Pipeline: Attack Detection Timeline", fontsize=16, fontweight="bold")

    colors = {"Normal": "#2ecc71", "Exploits": "#e74c3c", "Reconnaissance": "#f39c12"}

    # Plot 1: Flow classification over time
    ax = axes[0, 0]
    for label, color in colors.items():
        mask = results_df["true_label"] == label
        ax.scatter(results_df[mask].index, results_df[mask]["confidence"],
                   c=color, s=8, alpha=0.6, label=label)
    ax.set_title("Confidence by Flow (colored by true label)", fontweight="bold")
    ax.set_xlabel("Flow Index")
    ax.set_ylabel("Model Confidence")
    ax.legend(fontsize=10, markerscale=4)
    ax.grid(alpha=0.3)

    # Plot 2: Action distribution
    ax = axes[0, 1]
    action_counts = results_df["action"].value_counts()
    action_colors = {"ALLOW": "#2ecc71", "BLOCK_NEW": "#e74c3c",
                     "BLOCK_EXISTING": "#c0392b"}
    bars = ax.bar(action_counts.index, action_counts.values,
                  color=[action_colors.get(a, "#95a5a6") for a in action_counts.index])
    ax.set_title("Enforcement Actions", fontweight="bold")
    ax.set_ylabel("Count")
    for bar, val in zip(bars, action_counts.values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                str(val), ha="center", fontsize=10)
    ax.grid(alpha=0.3, axis="y")

    # Plot 3: Accuracy per class
    ax = axes[1, 0]
    class_accuracy = results_df.groupby("true_label")["correct"].mean() * 100
    bars = ax.bar(class_accuracy.index,
                  class_accuracy.values,
                  color=[colors.get(c, "#95a5a6") for c in class_accuracy.index])
    ax.axhline(y=85, color="red", linestyle="--", linewidth=2, label="85% target")
    ax.set_title("Per-Class Accuracy", fontweight="bold")
    ax.set_ylabel("Accuracy (%)")
    ax.set_ylim(0, 105)
    ax.legend(fontsize=10)
    for bar, val in zip(bars, class_accuracy.values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{val:.1f}%", ha="center", fontsize=10)
    ax.grid(alpha=0.3, axis="y")

    # Plot 4: Cumulative attacks blocked
    ax = axes[1, 1]
    attack_mask = results_df["true_label"].isin(["Exploits", "Reconnaissance"])
    blocked_mask = results_df["action"].isin(["BLOCK_NEW", "BLOCK_EXISTING"])
    cumulative_attacks = attack_mask.cumsum()
    cumulative_blocked = (attack_mask & blocked_mask).cumsum()
    ax.plot(results_df.index, cumulative_attacks, color="#e74c3c",
            linewidth=2, label="Attacks seen")
    ax.plot(results_df.index, cumulative_blocked, color="#2ecc71",
            linewidth=2, linestyle="--", label="Attacks blocked")
    ax.set_title("Cumulative Attacks vs Blocked", fontweight="bold")
    ax.set_xlabel("Flow Index")
    ax.set_ylabel("Count")
    ax.legend(fontsize=10)
    ax.grid(alpha=0.3)

    plt.tight_layout()
    fig.savefig("attack_timeline.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    LOG.info("Saved attack_timeline.png")


def main():
    LOG.info("=" * 60)
    LOG.info("AI-Powered Microsegmentation: Integration Pipeline")
    LOG.info("=" * 60)

    # Load enforcer
    enforcer = XGBoostEnforcer("xgboost_model.json")

    # Load test data
    LOG.info("Loading test data...")
    df_test = pd.read_csv("filtered_testing.csv")
    df_test = df_test[df_test["attack_cat"].isin(["Normal", "Exploits", "Reconnaissance"])]
    LOG.info("Test set: %d flows", len(df_test))

    # Run simulation
    results_df = simulate_pipeline(enforcer, df_test, n_flows=500)

    # Save results
    results_df.to_csv("integration_log.csv", index=False)
    LOG.info("Saved integration_log.csv")

    # Generate plots
    generate_timeline_plot(results_df)

    # Print final summary
    LOG.info("\n" + "=" * 60)
    LOG.info("PIPELINE SUMMARY")
    LOG.info("=" * 60)
    LOG.info("Total flows processed: %d", enforcer.stats["total"])
    LOG.info("Flows allowed:         %d", enforcer.stats["allowed"])
    LOG.info("Exploits blocked:      %d", enforcer.stats["exploit_blocked"])
    LOG.info("Recon blocked:         %d", enforcer.stats["recon_blocked"])
    LOG.info("Unique flows blocked:  %d", len(enforcer.blocked_flows))

    correct = results_df["correct"].mean() * 100
    LOG.info("Overall accuracy:      %.2f%%", correct)

    for label in ["Normal", "Exploits", "Reconnaissance"]:
        mask = results_df["true_label"] == label
        acc = results_df[mask]["correct"].mean() * 100 if mask.sum() > 0 else 0
        LOG.info("  %s accuracy: %.2f%%", label, acc)

    LOG.info("=" * 60)
    LOG.info("Done.")


if __name__ == "__main__":
    main()
