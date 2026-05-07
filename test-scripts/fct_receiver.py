#!/usr/bin/env python3
"""
HULA Flow Completion Time (FCT) Telemetry Receiver

This script captures HULA packets and extracts Flow Completion Time (FCT) data.
FCT = flow_current_time - flow_start_time (in nanoseconds)

The receiver groups packets by flow and computes both per-packet FCT estimates
and aggregated flow-level FCT metrics.

Usage:
    python3 fct_receiver.py [-o output_file.csv] [--show-probes]

Output CSV contains:
    - timestamp: Time in seconds since receiver start
    - src_ip: Source IP address
    - dst_ip: Destination IP address
    - flow_id: 5-tuple flow identifier
    - flow_start_time_ns: First packet timestamp (nanoseconds)
    - flow_current_time_ns: Current packet timestamp (nanoseconds)
    - fct_ns: Flow Completion Time in nanoseconds
    - fct_us: Flow Completion Time in microseconds
    - fct_ms: Flow Completion Time in milliseconds
"""

import sys
import os
import argparse
import time
import csv
from collections import defaultdict
from datetime import datetime

from scapy.all import sniff, get_if_list, IP, TCP, UDP, Raw, Packet, BitField
from scapy.all import hexdump, bind_layers

# Configuration
DEFAULT_OUTPUT_FILE = "fct_telemetry.csv"
START_TIME = time.time()
NS_TO_US = 1000.0  # Convert nanoseconds to microseconds
NS_TO_MS = 1000000.0  # Convert nanoseconds to milliseconds


class Hula(Packet):
    """HULA telemetry header with queue_depth and FCT fields."""
    fields_desc = [
        BitField("dst_tor0", 0, 24),
        BitField("path_util0", 0, 8),
        BitField("dst_tor1", 0, 24),
        BitField("path_util1", 0, 8),
        BitField("dst_tor2", 0, 24),
        BitField("path_util2", 0, 8),
        BitField("dst_tor3", 0, 24),
        BitField("path_util3", 0, 8),
        BitField("queue_depth", 0, 8),
        BitField("flow_start_time", 0, 48),  # Flow start timestamp (ns)
        BitField("flow_current_time", 0, 48),  # Current packet timestamp (ns)
    ]


# Bind HULA header to IP protocol 0x42
bind_layers(IP, Hula, proto=0x42)


def get_interface():
    """Auto-detect ethernet interface for sniffing."""
    ifs = list(filter(lambda i: 'eth' in i, os.listdir('/sys/class/net/')))
    if not ifs:
        print("❌ No eth interfaces found!")
        sys.exit(1)
    return ifs[0]


def compute_flow_id(src_ip, dst_ip, src_port, dst_port, protocol):
    """Create a flow identifier from 5-tuple."""
    return f"{src_ip}:{src_port}->{dst_ip}:{dst_port}/{protocol}"


def ns_to_us(ns):
    """Convert nanoseconds to microseconds."""
    return ns / NS_TO_US


def ns_to_ms(ns):
    """Convert nanoseconds to milliseconds."""
    return ns / NS_TO_MS


def handle_pkt(pkt, csv_writer, csv_file, show_probes, output_file):
    """
    Process a captured packet and extract FCT telemetry.
    """
    try:
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
            
            flow_id = compute_flow_id(src_ip, dst_ip, src_port, dst_port, protocol)
            
            # Extract FCT telemetry
            flow_start_ns = hula.flow_start_time
            flow_current_ns = hula.flow_current_time
            fct_ns = flow_current_ns - flow_start_ns if flow_current_ns >= flow_start_ns else 0
            fct_us = ns_to_us(fct_ns)
            fct_ms = ns_to_ms(fct_ns)
            
            # Extract queue depth
            queue_depth = hula.queue_depth
            
            # Print to console
            print(f"[{elapsed:.2f}s] {flow_id:50s} | "
                  f"FCT: {fct_ms:8.3f}ms ({fct_us:12.1f}µs) | "
                  f"Queue: {queue_depth:3d}B | "
                  f"Start: {flow_start_ns:12d}ns")
            
            # Write to CSV
            csv_writer.writerow([
                round(elapsed, 3),
                src_ip,
                dst_ip,
                src_port,
                dst_port,
                protocol,
                flow_id,
                flow_start_ns,
                flow_current_ns,
                fct_ns,
                round(fct_us, 3),
                round(fct_ms, 6),
                queue_depth,
                datetime.now().isoformat()
            ])
            csv_file.flush()
            
        elif show_probes:
            # Handle probe packets if requested
            if pkt.haslayer(Hula):
                hula = pkt[Hula]
                print(f"[{elapsed:.2f}s] PROBE: dst_tor0={hula.dst_tor0} "
                      f"fct_start={hula.flow_start_time} fct_current={hula.flow_current_time}")
        
    except Exception as e:
        print(f"⚠️ Error processing packet: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Capture HULA FCT telemetry and store to CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Capture FCT telemetry to default file
  python3 fct_receiver.py

  # Custom output file
  python3 fct_receiver.py -o fct_data.csv

  # Show probe packets
  python3 fct_receiver.py --show-probes
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
    print(f"📡 Starting FCT telemetry receiver on interface: {iface}")
    print(f"📝 Output file: {output_file}")
    print(f"⏱️  Timestamp reference: {datetime.now().isoformat()}")
    print("-" * 120)
    
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
            "flow_id",
            "flow_start_time_ns",
            "flow_current_time_ns",
            "fct_ns",
            "fct_us",
            "fct_ms",
            "queue_depth_bytes",
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
            print("\n\n✅ FCT telemetry collection complete!")
            print(f"📊 Data saved to: {output_file}")
        except Exception as e:
            print(f"❌ Error during sniffing: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
