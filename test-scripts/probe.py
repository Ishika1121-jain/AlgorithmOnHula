#!/usr/bin/env python3
import argparse
import sys
import socket
import random
import struct
import time
import csv

from scapy.all import sendp, send, get_if_list, get_if_hwaddr, bind_layers
from scapy.all import Packet, BitField, Raw
from scapy.all import Ether, IP, UDP, TCP
INTERVAL_FILE = "/tmp/hula_interval"
DEFAULT_INTERVAL = 0.2
# Logging variables
probe_count = 0
start_time = time.time()
last_log_time = start_time
last_probe_count = 0

# Change filename depending on version
CSV_FILE = "modified_hula_result.csv"   

def get_if():
    ifs=get_if_list()
    iface=None # "h1-eth0"
    for i in get_if_list():
        if "eth0" in i:
            iface=i
            break;
    if not iface:
        print ("Cannot find eth0 interface")
        exit(1)
    return iface

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

bind_layers(IP, Hula, proto=0x42)

def main():

    iface = get_if()
    hw_if = get_if_hwaddr(iface)

    print ("sending probe on interface %s." % (iface))
    pkt =  Ether(src=hw_if, dst='ff:ff:ff:ff:ff:ff')
    pkt = pkt / IP(dst="224.0.0.1", proto=66)

    dt = int(pkt[IP].src.split(".")[2])

    pkt = pkt / Hula(
        dst_tor0=dt, path_util0=0,
        dst_tor1=dt+1, path_util1=0,
        dst_tor2=dt+2, path_util2=0,
        dst_tor3=dt+3, path_util3=0,
        queue_depth=0,  # Initialize (populated by switch)
        flow_start_time=0,  # NEW: FCT field (populated by switch)
        flow_current_time=0  # NEW: FCT field (populated by switch)
    )

    pkt = pkt / Raw("probe packet")
    # Create CSV file and write header
    with open(CSV_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["time", "probes_per_sec", "total_probes", "overhead"])
    # Keep sending probes
    while True:
        global probe_count, last_log_time, last_probe_count

        sendp(pkt, iface=iface, verbose=False)
        probe_count += 1

        current_time = time.time()
        elapsed = current_time - start_time

        # Log every 1 second
        if current_time - last_log_time >= 1:

            probes_this_sec = probe_count - last_probe_count

            # Calculate overhead
            PROBE_SIZE = 64  # bytes
            LINK_BW = 100 * 10**6 / 8  # 100 Mbps in bytes/sec

            overhead = (PROBE_SIZE * probes_this_sec) / LINK_BW

            with open(CSV_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    round(elapsed, 2),
                    probes_this_sec,
                    probe_count,
                    round(overhead, 6)
                ])

            last_log_time = current_time
            last_probe_count = probe_count

        try:
            with open(INTERVAL_FILE, "r") as f:
                interval = float(f.read().strip())
        except:
            interval = DEFAULT_INTERVAL

        time.sleep(interval)

if __name__ == '__main__':
    main()
