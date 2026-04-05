"""
Ryu OpenFlow Controller: Zero Trust Deny-by-Default
======================================================
Implements microsegmentation policy:
  - Default: BLOCK all inter-segment traffic
  - Allowed: intra-segment traffic (same /24 subnet)
  - Blocked: any cross-segment traffic flagged by XGBoost

When XGBoost detects Exploit or Reconnaissance traffic,
it calls block_flow() to install a drop rule on the switch.

Usage (run in WSL2 Ubuntu before mininet_topology.py):
    ryu-manager ryu_controller.py --ofp-tcp-listen-port 6653

Requirements:
    pip3 install ryu
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4
import logging
import json

LOG = logging.getLogger("MicrosegController")

# ── Segment definitions (must match mininet_topology.py) ─────────
SEGMENTS = {
    0: {"name": "Normal",   "subnet": "10.0.0", "hosts": ["10.0.0.1", "10.0.0.2"]},
    1: {"name": "App",      "subnet": "10.0.1", "hosts": ["10.0.1.1", "10.0.1.2"]},
    2: {"name": "Attacker", "subnet": "10.0.2", "hosts": ["10.0.2.1", "10.0.2.2"]},
}

# ── Allowed inter-segment flows (whitelist) ───────────────────────
# Format: (src_segment, dst_segment) = reason
ALLOWED_FLOWS = {
    (0, 1): "Web to App: legitimate service communication",
    (1, 0): "App to Web: response traffic",
}

# ── Denied flows (attacker segments) ─────────────────────────────
# Segment 2 cannot initiate to any other segment
DENIED_SEGMENTS = {2}


def get_segment(ip):
    """Return segment ID for a given IP address."""
    if ip is None:
        return None
    for seg_id, seg_info in SEGMENTS.items():
        if ip.startswith(seg_info["subnet"]):
            return seg_id
    return None


class MicrosegController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.mac_to_port = {}
        self.blocked_flows = set()  # Set of (src_ip, dst_ip) tuples blocked by XGBoost
        self.stats = {
            "allowed": 0,
            "blocked_policy": 0,
            "blocked_xgboost": 0,
            "total": 0
        }
        LOG.info("MicrosegController initialized")
        LOG.info("Segments: %s", json.dumps({k: v["name"] for k, v in SEGMENTS.items()}))
        LOG.info("Allowed flows: %s", list(ALLOWED_FLOWS.keys()))

    # ── Switch handshake ──────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Register the switch and install a table-miss rule so unmatched packets reach the controller."""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        self.datapaths[datapath.id] = datapath

        LOG.info("Switch connected: dpid=%s", datapath.id)

        # Install table-miss: send all unmatched packets to controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, priority=0, match=match, actions=actions)
        LOG.info("  Table-miss flow installed (send to controller)")

    # ── Packet-in handler ─────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """Evaluate each unmatched packet against the Zero Trust policy: forward, or install a drop rule."""
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return

        dst_mac = eth.dst
        src_mac = eth.src
        dpid = datapath.id

        # Learn MAC to port mapping
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src_mac] = in_port

        # Extract IP layer
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        src_ip = ip_pkt.src if ip_pkt else None
        dst_ip = ip_pkt.dst if ip_pkt else None

        self.stats["total"] += 1

        # ── Policy decision ───────────────────────────────────────
        action = self._policy_decision(src_ip, dst_ip, src_mac, dst_mac)

        if action == "BLOCK":
            # Install drop rule for this flow
            if src_ip and dst_ip:
                match = parser.OFPMatch(
                    eth_type=0x0800,
                    ipv4_src=src_ip,
                    ipv4_dst=dst_ip
                )
                self._add_flow(datapath, priority=10, match=match, actions=[],
                               idle_timeout=60)
                self.stats["blocked_policy"] += 1
                LOG.warning("BLOCKED [POLICY] %s -> %s (cross-segment)", src_ip, dst_ip)
            return  # Drop packet

        elif action == "BLOCK_XGBOOST":
            if src_ip and dst_ip:
                match = parser.OFPMatch(
                    eth_type=0x0800,
                    ipv4_src=src_ip,
                    ipv4_dst=dst_ip
                )
                self._add_flow(datapath, priority=20, match=match, actions=[],
                               idle_timeout=300)
                self.stats["blocked_xgboost"] += 1
                LOG.warning("BLOCKED [XGBOOST] %s -> %s (attack detected)", src_ip, dst_ip)
            return

        else:  # ALLOW
            # Forward packet
            out_port = self.mac_to_port[dpid].get(dst_mac, ofproto.OFPP_FLOOD)
            actions = [parser.OFPActionOutput(out_port)]

            # Install flow rule to avoid hitting controller for future packets
            if out_port != ofproto.OFPP_FLOOD and src_ip and dst_ip:
                match = parser.OFPMatch(
                    in_port=in_port,
                    eth_dst=dst_mac,
                    eth_src=src_mac
                )
                self._add_flow(datapath, priority=1, match=match, actions=actions,
                               idle_timeout=30)

            self.stats["allowed"] += 1
            if src_ip and dst_ip:
                LOG.info("ALLOWED %s -> %s", src_ip, dst_ip)

            # Send packet
            data = msg.data if msg.buffer_id == datapath.ofproto.OFP_NO_BUFFER else None
            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=data
            )
            datapath.send_msg(out)

    def _policy_decision(self, src_ip, dst_ip, src_mac, dst_mac):
        """
        Zero Trust policy engine.
        Returns: 'ALLOW', 'BLOCK', or 'BLOCK_XGBOOST'
        """
        # Non-IP traffic: allow ARP etc.
        if src_ip is None or dst_ip is None:
            return "ALLOW"

        # Broadcast/multicast: allow
        if dst_ip.endswith(".255") or dst_ip == "255.255.255.255":
            return "ALLOW"

        src_seg = get_segment(src_ip)
        dst_seg = get_segment(dst_ip)

        # Unknown segments: allow (not our managed hosts)
        if src_seg is None or dst_seg is None:
            return "ALLOW"

        # Intra-segment: always allow
        if src_seg == dst_seg:
            return "ALLOW"

        # XGBoost-flagged flows: always block regardless of policy
        if (src_ip, dst_ip) in self.blocked_flows:
            return "BLOCK_XGBOOST"

        # Attacker segment: deny all outbound
        if src_seg in DENIED_SEGMENTS:
            return "BLOCK"

        # Whitelist check
        if (src_seg, dst_seg) in ALLOWED_FLOWS:
            return "ALLOW"

        # Default: deny all cross-segment traffic
        return "BLOCK"

    def _add_flow(self, datapath, priority, match, actions,
                  idle_timeout=0, hard_timeout=0):
        """Install a flow rule on the switch."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions
        )]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)

    def block_flow(self, src_ip, dst_ip):
        """
        Called by integration.py when XGBoost flags a flow as attack.
        Installs drop rules on all switches for this src->dst pair.
        """
        self.blocked_flows.add((src_ip, dst_ip))
        LOG.warning("XGBoost flagged flow: %s -> %s, installing block rules", src_ip, dst_ip)

        for dpid, datapath in self.datapaths.items():
            parser = datapath.ofproto_parser
            match = parser.OFPMatch(
                eth_type=0x0800,
                ipv4_src=src_ip,
                ipv4_dst=dst_ip
            )
            # Priority 20: overrides whitelist rules
            self._add_flow(datapath, priority=20, match=match, actions=[],
                           idle_timeout=300)
            LOG.info("  Block rule installed on switch dpid=%s", dpid)

    def print_stats(self):
        """Print current flow statistics."""
        LOG.info("Flow Stats: allowed=%d | blocked_policy=%d | blocked_xgboost=%d | total=%d",
                 self.stats["allowed"], self.stats["blocked_policy"],
                 self.stats["blocked_xgboost"], self.stats["total"])
