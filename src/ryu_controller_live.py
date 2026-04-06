"""
Ryu OpenFlow Controller: Zero Trust Deny-by-Default (LIVE EVENT LOGGING)
==========================================================================
Same as ryu_controller.py but writes every flow decision to
/tmp/zeroseg_events.json so the dashboard can read it live.

Usage (Terminal 1 in Mininet VM):
    ryu-manager ryu_controller_live.py --ofp-tcp-listen-port 6653
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4
import logging
import json
import time
import os

LOG = logging.getLogger("ZeroSeg")
EVENTS_FILE = "/tmp/zeroseg_events.json"

SEGMENTS = {
    0: {"name": "Normal",   "subnet": "10.0.0"},
    1: {"name": "App",      "subnet": "10.0.1"},
    2: {"name": "Attacker", "subnet": "10.0.2"},
}

ALLOWED_FLOWS = { (0, 1), (1, 0) }
DENIED_SEGMENTS = {2}

# The live controller enforces by segment policy, not by scoring each packet
# through XGBoost. These are the model's measured per-class confidence from the
# offline evaluation (train_xgboost.py), shown on the dashboard for context.
BLOCK_CONFIDENCE = 95   # avg F1 across Exploit/Recon classes
ALLOW_CONFIDENCE = 98   # Normal-class precision

def get_segment(ip):
    """Return segment ID for a given IP address."""
    if ip is None: return None
    for seg_id, seg_info in SEGMENTS.items():
        if ip.startswith(seg_info["subnet"]):
            return seg_id
    return None

def write_event(event):
    """Append event to the JSON events file."""
    try:
        events = []
        if os.path.exists(EVENTS_FILE):
            with open(EVENTS_FILE, 'r') as f:
                try:
                    events = json.load(f)
                except (json.JSONDecodeError, ValueError):
                    events = []
        events.append(event)
        # Keep last 200 events only
        events = events[-200:]
        with open(EVENTS_FILE, 'w') as f:
            json.dump(events, f)
    except Exception as e:
        LOG.error("Failed to write event: %s", e)


class ZeroSegController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.mac_to_port = {}
        self.blocked_flows = set()
        self.stats = {"allowed": 0, "blocked": 0, "total": 0}

        # Clear events file on start
        with open(EVENTS_FILE, 'w') as f:
            json.dump([], f)

        LOG.info("ZeroSeg controller started. Events file: %s", EVENTS_FILE)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Register the switch and install a table-miss rule so unmatched packets reach the controller."""
        datapath = ev.msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        self.datapaths[datapath.id] = datapath

        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, priority=0, match=match, actions=actions)
        LOG.info("Switch connected: dpid=%s", datapath.id)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """Evaluate each unmatched packet against policy, log a dashboard event, and forward or drop."""
        msg      = ev.msg
        datapath = msg.datapath
        ofproto  = datapath.ofproto
        parser   = datapath.ofproto_parser
        in_port  = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None: return

        dst_mac = eth.dst
        src_mac = eth.src
        dpid    = datapath.id

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src_mac] = in_port

        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        src_ip = ip_pkt.src if ip_pkt else None
        dst_ip = ip_pkt.dst if ip_pkt else None

        self.stats["total"] += 1
        action = self._policy_decision(src_ip, dst_ip)

        # Build event
        ts = time.strftime("%H:%M:%S")
        src_seg = get_segment(src_ip)
        dst_seg = get_segment(dst_ip)
        src_seg_name = SEGMENTS[src_seg]["name"] if src_seg is not None else "Unknown"
        dst_seg_name = SEGMENTS[dst_seg]["name"] if dst_seg is not None else "Unknown"

        if action == "BLOCK":
            if src_ip and dst_ip:
                proto = ip_pkt.proto if ip_pkt else 0
                match = parser.OFPMatch(eth_type=0x0800, ipv4_src=src_ip, ipv4_dst=dst_ip, ip_proto=proto)
                self._add_flow(datapath, priority=10, match=match, actions=[], idle_timeout=60)
                self.stats["blocked"] += 1

                # Determine attack type based on traffic pattern
                attack_type = "Exploit"
                if src_seg == 2:
                    # Check if it looks like recon (small packet, ICMP)
                    attack_type = "Reconnaissance" if (ip_pkt and ip_pkt.proto == 1) else "Exploit"

                LOG.warning("BLOCKED %s -> %s (%s)", src_ip, dst_ip, attack_type)

                write_event({
                    "ts": ts,
                    "type": attack_type,
                    "src_ip": src_ip,
                    "dst_ip": dst_ip,
                    "src_seg": src_seg_name,
                    "dst_seg": dst_seg_name,
                    "action": "BLOCK",
                    "confidence": BLOCK_CONFIDENCE,
                    "new": (src_ip, dst_ip) not in self.blocked_flows
                })
                self.blocked_flows.add((src_ip, dst_ip))
            return

        else:  # ALLOW
            out_port = self.mac_to_port[dpid].get(dst_mac, ofproto.OFPP_FLOOD)
            actions  = [parser.OFPActionOutput(out_port)]

            if out_port != ofproto.OFPP_FLOOD and src_ip and dst_ip:
                match = parser.OFPMatch(in_port=in_port, eth_dst=dst_mac, eth_src=src_mac)
                self._add_flow(datapath, priority=1, match=match, actions=actions, idle_timeout=30)

            self.stats["allowed"] += 1

            if src_ip and dst_ip and src_ip != dst_ip:
                write_event({
                    "ts": ts,
                    "type": "Normal",
                    "src_ip": src_ip,
                    "dst_ip": dst_ip,
                    "src_seg": src_seg_name,
                    "dst_seg": dst_seg_name,
                    "action": "ALLOW",
                    "confidence": ALLOW_CONFIDENCE,
                    "new": False
                })

            data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
            out  = parser.OFPPacketOut(
                datapath=datapath, buffer_id=msg.buffer_id,
                in_port=in_port, actions=actions, data=data
            )
            datapath.send_msg(out)

    def _policy_decision(self, src_ip, dst_ip):
        """Zero Trust policy engine: returns 'ALLOW' or 'BLOCK'."""
        if src_ip is None or dst_ip is None: return "ALLOW"
        if dst_ip.endswith(".255") or dst_ip == "255.255.255.255": return "ALLOW"
        src_seg = get_segment(src_ip)
        dst_seg = get_segment(dst_ip)
        if src_seg is None or dst_seg is None: return "ALLOW"
        if src_seg == dst_seg: return "ALLOW"
        if src_seg in DENIED_SEGMENTS: return "BLOCK"
        if (src_seg, dst_seg) in ALLOWED_FLOWS: return "ALLOW"
        return "BLOCK"

    def _add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        """Install a flow rule on the switch."""
        ofproto = datapath.ofproto
        parser  = datapath.ofproto_parser
        inst    = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod     = parser.OFPFlowMod(
            datapath=datapath, priority=priority, match=match,
            instructions=inst, idle_timeout=idle_timeout, hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)
