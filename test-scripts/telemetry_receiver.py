#!/usr/bin/env python3
"""
HULA Queue Depth & TX Link Utilization Telemetry Receiver

This script captures HULA packets from the network and extracts telemetry
data including queue_depth and TX link utilization. It stores the telemetry
in a CSV file for analysis.

Usage:
    python3 telemetry_receiver.py [-o output_file.csv] [--show-probes]

The output CSV contains:
    - timestamp: Time in seconds since script start
    - src_ip: Source IP address
    - dst_ip: Destination IP address  
    - src_port: TCP source port
    - dst_port: TCP destination port
    - protocol: Transport protocol (TCP/UDP/OTHER)
    - queue_depth: Egress queue depth at packet departure (0-255 bytes)
    - tx_link_util: TX Link Utilization (0-255 scale, 255 = 100% bandwidth)
    - flow_hash: Hash of flow 5-tuple (for grouping)
"""

import sys
import os
import argparse
import time
import csv
from datetime import datetime

from scapy.all import sniff, get_if_list, IP, TCP, UDP, Raw, Packet, BitField
from scapy.all import hexdump, bind_layers

# Configuration
DEFAULT_OUTPUT_FILE = "queue_depth_telemetry.csv"
START_TIME = time.time()


class Hula(Packet):
    """HULA telemetry header with queue_depth and tx_link_util fields."""
    fields_desc = [
        BitField("dst_tor0", 0, 24),
        BitField("path_util0", 0, 8),
        BitField("dst_tor1", 0, 24),
        BitField("path_util1", 0, 8),
        BitField("dst_tor2", 0, 24),
        BitField("path_util2", 0, 8),
        BitField("dst_tor3", 0, 24),
        BitField("path_util3", 0, 8),
        BitField("queue_depth", 0, 8),  # Queue depth in bytes (0-255)
        BitField("tx_link_util", 0, 8),  # TX Link Utilization (INT spec: 0-255 scale, 255 = 100%)
    ]


# Bind HULA header to IP protocol 0x42 (66 decimal)
bind_layers(IP, Hula, proto=0x42)


def get_interface():
    """Auto-detect ethernet interface for sniffing."""
    ifs = list(filter(lambda i: 'eth' in i, os.listdir('/sys/class/net/')))
    if not ifs:
        print("❌ No eth interfaces found!")
        sys.exit(1)
    return ifs[0]


def compute_flow_hash(src_ip, dst_ip, src_port, dst_port, protocol):
    """
    Compute a simple hash of the 5-tuple for flow identification.
    """
    import hashlib
    flow_tuple = f"{src_ip}:{dst_ip}:{src_port}:{dst_port}:{protocol}"
    flow_hash = hashlib.md5(flow_tuple.encode()).hexdigest()[:8]
    return flow_hash


def handle_pkt(pkt, csv_writer, csv_file, show_probes, output_file):
    """
    Process a captured packet and extract telemetry if it has HULA header.
    """
    try:
        # Access timestamp
        elapsed = time.time() - START_TIME
        
        if pkt.haslayer(Hula):
            hula = pkt[Hula]
            
            # Extract IP and transport layer info
            src_ip = "0.0.0.0"
            dst_ip = "0.0.0.0"
            src_port = 0
            dst_port = 0
            protocol = "UNKNOWN"
            
            if pkt.haslayer(IP):
                src_ip = pkt[IP].src
                dst_ip = pkt[IP].dst
                
                if pkt.haslayer(TCP):
                    src_port = pkt[TCP].sport
                    dst_port = pkt[TCP].dport
                    protocol = "TCP"
                elif pkt.haslayer(UDP):
                    src_port = pkt[UDP].sport
                    dst_port = pkt[UDP].dport
                    protocol = "UDP"
                else:
                    protocol = "OTHER"
            
            # Compute flow hash for grouping
            flow_hash = compute_flow_hash(src_ip, dst_ip, src_port, dst_port, protocol)
            
            # Extract queue_depth telemetry
            queue_depth = hula.queue_depth
            tx_link_util = hula.tx_link_util
            
            # Print to console
            print(f"[{elapsed:.2f}s] Flow: {src_ip}:{src_port} -> {dst_ip}:{dst_port} | "
                  f"Protocol: {protocol} | Queue Depth: {queue_depth} bytes | "
                  f"TX Link Util: {tx_link_util}/255 ({tx_link_util*100//255}%) | "
                  f"Flow Hash: {flow_hash}")
            
            # Write to CSV
            csv_writer.writerow([
                round(elapsed, 3),
                src_ip,
                dst_ip,
                src_port,
                dst_port,
                protocol,
                queue_depth,
                tx_link_util,
                flow_hash,
                datetime.now().isoformat()
            ])
            csv_file.flush()
            
        elif not show_probes and hula:
            # If showing probes, print probe-specific info
            if show_probes:
                print(f"[{elapsed:.2f}s] PROBE PACKET: dst_tor0={hula.dst_tor0} "
                      f"path_util0={hula.path_util0} queue_depth={hula.queue_depth} "
                      f"tx_link_util={hula.tx_link_util}")
                csv_writer.writerow([
                    round(elapsed, 3),
                    "0.0.0.0",
                    "224.0.0.1",  # Multicast probe address
                    0,
                    0,
                    "PROBE",
                    hula.queue_depth,
                    hula.tx_link_util,
                    "PROBE",
                    datetime.now().isoformat()
                ])
                csv_file.flush()
        
    except Exception as e:
        print(f"⚠️ Error processing packet: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Capture HULA queue_depth telemetry and store to CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Default output to queue_depth_telemetry.csv
  python3 telemetry_receiver.py

  # Custom output file
  python3 telemetry_receiver.py -o my_telemetry.csv

  # Show probe packets too
  python3 telemetry_receiver.py --show-probes
        """
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        default=DEFAULT_OUTPUT_FILE,
        help=f'Output CSV file (default: {DEFAULT_OUTPUT_FILE})'
    )
    parser.add_argument(
        '-p', '--show-probes',
        action='store_true',
        default=False,
        help='Include probe packets in output'
    )
    
    args = parser.parse_args()
    output_file = args.output
    show_probes = args.show_probes
    
    # Get interface
    iface = get_interface()
    print(f"📡 Starting telemetry receiver on interface: {iface}")
    print(f"📝 Output file: {output_file}")
    print(f"⏱️  Timestamp reference: {datetime.now().isoformat()}")
    print("-" * 100)
    
    # Initialize CSV file
    with open(output_file, 'w', newline='') as csv_file:
        csv_writer = csv.writer(csv_file)
        
        # Write header
        csv_writer.writerow([
            "timestamp_s",
            "src_ip",
            "dst_ip",
            "src_port",
            "dst_port",
            "protocol",
            "queue_depth_bytes",
            "tx_link_util_0_255",
            "flow_hash",
            "datetime_iso"
        ])
        csv_file.flush()
        
        # Start sniffing
        try:
            sniff(
                iface=iface,
                prn=lambda pkt: handle_pkt(pkt, csv_writer, csv_file, show_probes, output_file),
                store=False
            )
        except KeyboardInterrupt:
            print("\n\n✅ Telemetry collection complete!")
            print(f"📊 Data saved to: {output_file}")
        except Exception as e:
            print(f"❌ Error during sniffing: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
