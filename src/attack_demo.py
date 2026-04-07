"""
ZeroSeg Attack Demo Script
===========================
Run this INSIDE the Mininet CLI to simulate a realistic
Reconnaissance then Exploit attack sequence.

Usage (in Mininet CLI after topology is running):
    mininet> py exec(open('/home/mininet/attack_demo.py').read())

Or run individual commands manually:
    mininet> h5 nmap -sn --host-timeout 2s 10.0.0.1 10.0.0.2 10.0.1.1 10.0.1.2
    mininet> h5 ping -c 3 10.0.0.1
    mininet> h5 ping -c 3 10.0.1.1
    mininet> h1 ping -c 3 10.0.0.2
"""

import time

def run_demo(net):
    """Run the 5-step demo sequence (normal → recon → exploit → normal) against the live Mininet net."""
    h1 = net.get('h1')
    h3 = net.get('h3')
    h5 = net.get('h5')

    print("\n" + "="*60)
    print("  ZEROSEG ATTACK DEMO")
    print("="*60)

    print("\n[STEP 1] Normal traffic: h1 pings h2 (same segment)")
    print("         Expected: ALLOWED")
    result = h1.cmd('ping -c 3 10.0.0.2')
    print(result)
    time.sleep(1)

    print("\n[STEP 2] Reconnaissance: h5 scans Segment 0 and Segment 1")
    print("         Expected: 0 hosts up (all probes BLOCKED)")
    result = h5.cmd('nmap -sn --host-timeout 2s 10.0.0.1 10.0.0.2 10.0.1.1 10.0.1.2')
    print(result)
    time.sleep(1)

    print("\n[STEP 3] Exploit attempt: h5 tries to reach Segment 0")
    print("         Expected: 100% packet loss (BLOCKED)")
    result = h5.cmd('ping -c 5 10.0.0.1')
    print(result)
    time.sleep(1)

    print("\n[STEP 4] Exploit attempt: h5 tries to reach Segment 1")
    print("         Expected: 100% packet loss (BLOCKED)")
    result = h5.cmd('ping -c 5 10.0.1.1')
    print(result)
    time.sleep(1)

    print("\n[STEP 5] Normal traffic continues: h3 pings h4 (same segment)")
    print("         Expected: ALLOWED, microsegmentation does not affect normal traffic")
    result = h3.cmd('ping -c 3 10.0.1.2')
    print(result)

    print("\n" + "="*60)
    print("  DEMO COMPLETE")
    print("  Check dashboard for live detection events")
    print("="*60 + "\n")

# If running directly inside Mininet CLI:
# run_demo(net)
