#!/usr/bin/env python3
import sys
import struct
import os
import argparse

from scapy.all import sniff, sendp, hexdump, get_if_list, get_if_hwaddr, bind_layers
from scapy.all import Packet, IPOption
from scapy.all import ShortField, IntField, LongField, BitField, FieldListField, FieldLenField
from scapy.all import IP, TCP, UDP, Raw
from scapy.layers.inet import _IPOption_HDR

def get_if():
    ifs = get_if_list()
    iface = None
    for i in ifs:
        if "eth0" in i:
            iface = i
            break
    if not iface:
        print("Cannot find eth0 interface")
        sys.exit(1)
    return iface


class IPOption_MRI(IPOption):
    name = "MRI"
    option = 31
    fields_desc = [
        _IPOption_HDR,
        FieldLenField("length", None, fmt="B",
                      length_of="swids",
                      adjust=lambda pkt, l: l + 4),
        ShortField("count", 0),
        FieldListField("swids",
                       [],
                       IntField("", 0),
                       length_from=lambda pkt: pkt.count * 4)
    ]


class Hula(Packet):
    fields_desc = [
        BitField("dst_tor0", 0, 24),
        BitField("path_util0", 0, 8),

        BitField("dst_tor1", 0, 24),
        BitField("path_util1", 0, 8),

        BitField("dst_tor2", 0, 24),
        BitField("path_util2", 0, 8),

        BitField("dst_tor3", 0, 24),
        BitField("path_util3", 0, 8),
        
        BitField("queue_depth", 0, 8),  # Queue depth telemetry
        
        BitField("flow_start_time", 0, 48),  # NEW: FCT - Flow start timestamp
        BitField("flow_current_time", 0, 48),  # NEW: FCT - Current packet timestamp
    ]


def handle_pkt(pkt, show_probes):
    if pkt.haslayer(Hula) and not show_probes:
        return
    else:
        pkt.show2()
        sys.stdout.flush()


bind_layers(IP, Hula, proto=66)


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--show-probes',
                        help='Parse and show probe packets',
                        action='store_true',
                        required=False,
                        default=False)
    return parser.parse_args()


def main():
    args = get_args()

    # FIX: convert filter → list
    ifaces = list(filter(lambda i: 'eth' in i, os.listdir('/sys/class/net/')))
    if not ifaces:
        print("❌ No eth interfaces found!")
        sys.exit(1)

    iface = ifaces[0]
    print(f"Sniffing on {iface}")
    sys.stdout.flush()

    sniff(
        iface=iface,
        prn=lambda x: handle_pkt(x, args.show_probes)
    )


if __name__ == '__main__':
    main()

