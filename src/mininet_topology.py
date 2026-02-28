"""
Mininet Multi-Host Topology: Zero Trust Microsegmentation
============================================================
Testbed for the Ryu controller: 6 hosts across 3 segments
(Normal 10.0.0.x, App 10.0.1.x, Attacker 10.0.2.x), each on its own
edge switch behind a core switch. Drops into the Mininet CLI for
interactive demo commands (see the banner printed at startup).

Usage (requires root):
    sudo python3 mininet_topology.py

NOTE: Start ryu_controller_live.py in Terminal 1 BEFORE running this.
      ryu-manager ryu_controller_live.py --ofp-tcp-listen-port 6653
"""

from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.topo import Topo
from mininet.log import setLogLevel, info
from mininet.cli import CLI
from mininet.link import TCLink
import time


class MicrosegmentationTopo(Topo):
    def build(self):
        """Build a core switch with three segment switches, two hosts per segment."""
        s_core = self.addSwitch("s0", protocols="OpenFlow13")
        s1 = self.addSwitch("s1", protocols="OpenFlow13")
        s2 = self.addSwitch("s2", protocols="OpenFlow13")
        s3 = self.addSwitch("s3", protocols="OpenFlow13")

        self.addLink(s1, s_core, bw=100, delay="2ms")
        self.addLink(s2, s_core, bw=100, delay="2ms")
        self.addLink(s3, s_core, bw=100, delay="2ms")

        h1 = self.addHost("h1", ip="10.0.0.1/8", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", ip="10.0.0.2/8", mac="00:00:00:00:00:02")
        self.addLink(h1, s1, bw=100)
        self.addLink(h2, s1, bw=100)

        h3 = self.addHost("h3", ip="10.0.1.1/8", mac="00:00:00:01:00:01")
        h4 = self.addHost("h4", ip="10.0.1.2/8", mac="00:00:00:01:00:02")
        self.addLink(h3, s2, bw=100)
        self.addLink(h4, s2, bw=100)

        h5 = self.addHost("h5", ip="10.0.2.1/8", mac="00:00:00:02:00:01")
        h6 = self.addHost("h6", ip="10.0.2.2/8", mac="00:00:00:02:00:02")
        self.addLink(h5, s3, bw=100)
        self.addLink(h6, s3, bw=100)


def run():
    setLogLevel("info")

    topo = MicrosegmentationTopo()
    net = Mininet(
        topo=topo,
        controller=None,
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=False,
        autoStaticArp=True
    )

    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)

    info("*** Starting network\n")
    net.start()
    time.sleep(2)

    for sw in net.switches:
        sw.cmd(f"ovs-vsctl set bridge {sw.name} protocols=OpenFlow13")

    info("\n*** Topology ready:\n")
    info("  Segment 0 (Normal):   h1=10.0.0.1, h2=10.0.0.2\n")
    info("  Segment 1 (App):      h3=10.0.1.1, h4=10.0.1.2\n")
    info("  Segment 2 (Attacker): h5=10.0.2.1, h6=10.0.2.2\n")
    info("\n*** Demo commands:\n")
    info("    h1 ping -c 3 10.0.0.2        (normal - ALLOWED)\n")
    info("    h5 ping -c 5 10.0.0.1        (exploit - BLOCKED)\n")
    info("    h5 ping -c 5 10.0.1.1        (exploit - BLOCKED)\n")
    info("    h5 nmap -sn --host-timeout 2s 10.0.0.1 10.0.0.2 10.0.1.1 10.0.1.2\n")
    info("\n*** Opening CLI:\n")
    CLI(net)

    net.stop()


if __name__ == "__main__":
    run()
