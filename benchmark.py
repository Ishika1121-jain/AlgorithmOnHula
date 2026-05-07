#!/usr/bin/env python3

import argparse
import sys
import os
import grpc
import re
import json
from time import sleep

# Add utils path
sys.path.append(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'utils/')
)

import p4runtime_lib.helper
from p4runtime_lib.switch import ShutdownAllSwitchConnections
from p4runtime_lib.convert import decodeMac, decodeIPv4
from switch_utils import printGrpcError, load_topology, run_ssc_cmd


switch_reg = re.compile(r"^s(\d+)$")


def generate_register_reads(register_name, indices):
    cmd = ""
    for idx in indices:
        cmd += f"register_read MyIngress.{register_name} {idx}\n"
    return cmd


snapshot_best_hop_cmd = generate_register_reads(
    'best_hop',
    [100, 101, 102, 103, 104, 105, 106, 107]
)

snapshot_port_util_cmd = generate_register_reads(
    'port_util',
    [0, 1, 2, 3, 4, 5, 6]
)

process_best_hop_regex = re.compile(r".*hop\[(\d+)\]\s*=\s*(\d+)")
process_port_util_regex = re.compile(r".*util\[(\d+)\]\s*=\s*(\d+)")


def process_and_output(output, reg):
    best_hops = {}

    for line in output.split("\n"):
        match = reg.search(line)
        if match:
            best_hops[match.group(1)] = match.group(2)

    return best_hops


def benchmark(mn_topo, switches, bench_switches, interval, count):
    data = []
    c = count

    while c > 0:
        snapshot = {
            'count': count - c,
            'best_hops': {},
            'port_util': {}
        }

        for switch in bench_switches:
            out = run_ssc_cmd(switch, snapshot_best_hop_cmd, False)
            best_hops = process_and_output(out, process_best_hop_regex)
            snapshot['best_hops'][switch] = best_hops

            out = run_ssc_cmd(switch, snapshot_port_util_cmd, False)
            port_util = process_and_output(out, process_port_util_regex)
            snapshot['port_util'][switch] = port_util

        c -= 1
        data.append(snapshot.copy())
        sleep(interval)

    return data


def main(p4info_file_path, bmv2_file_path, topo_file_path,
         bench_switches, interval, count):

    # Instantiate P4Runtime helper
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    try:
        # Load topology
        switches, mn_topo = load_topology(topo_file_path)

        # Establish P4Runtime connection
        for bmv2_switch in switches.values():
            bmv2_switch.MasterArbitrationUpdate()
            print(f"Established as controller for {bmv2_switch.name}")

        bs = bench_switches
        if len(bs) == 0:
            bs = mn_topo.switches()

        data = benchmark(mn_topo, switches, bs, interval, count)

        print(json.dumps(
            data,
            sort_keys=True,
            indent=2,
            separators=(',', ': ')
        ))

    except KeyboardInterrupt:
        print("Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)
    finally:
        ShutdownAllSwitchConnections()


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        '-s', '--switches',
        help='List of switches to snapshot',
        nargs='+',
        required=False,
        default=[]
    )

    parser.add_argument(
        '-t', '--snap-interval',
        help='Snapshot interval in seconds',
        type=float,
        required=False,
        default=1
    )

    parser.add_argument(
        '-n', '--snap-count',
        help='Number of snapshots to take',
        type=int,
        required=True
    )

    parser.add_argument(
        '--p4info',
        help='p4info proto in text format from p4c',
        type=str,
        default='./build/switch.p4info'
    )

    parser.add_argument(
        '--bmv2-json',
        help='BMv2 JSON file from p4c',
        type=str,
        default='./build/switch.json'
    )

    parser.add_argument(
        '--topo',
        help='Topology file',
        type=str,
        default='topology.json'
    )

    return parser, parser.parse_args()


if __name__ == '__main__':
    parser, args = get_args()

    if not os.path.exists(args.p4info):
        parser.print_help()
        print(f"\np4info file not found: {args.p4info}\nHave you run 'make'?")
        parser.exit(1)

    if not os.path.exists(args.bmv2_json):
        parser.print_help()
        print(f"\nBMv2 JSON file not found: {args.bmv2_json}\nHave you run 'make'?")
        parser.exit(1)

    if not os.path.exists(args.topo):
        parser.print_help()
        print(f"\nTopology file not found: {args.topo}")
        parser.exit(1)

    main(
        args.p4info,
        args.bmv2_json,
        args.topo,
        args.switches,
        args.snap_interval,
        args.snap_count
    )
