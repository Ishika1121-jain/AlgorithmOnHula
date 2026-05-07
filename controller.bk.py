

#!/usr/bin/env python3
import argparse
import re
import grpc
import os
import sys
import json
import subprocess
import networkx as nx
import time
import threading


# Prevent any installed 'p4' package from interfering
sys.modules.pop('p4', None)

# Use __file__ to compute utils path reliably
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'utils/'))
import p4runtime_lib.helper

from p4runtime_lib.switch import ShutdownAllSwitchConnections
from p4runtime_lib.convert import decodeMac, decodeIPv4
from switch_utils import printGrpcError, load_topology, run_ssc_cmd

# Turn on dry run mode for debugging if you want
debug = False
BASE_INTERVAL = 0.2
MAX_INTERVAL = 5.0
CHECK_INTERVAL = 1
STABLE_THRESHOLD = 3
INTERVAL_FILE = "/tmp/hula_interval"



def host_to_dst_id(hosts):
    """Generate a simple UID for dst_id of each host."""
    return dict(zip(hosts, range(1, len(hosts) + 1)))


def install_smart_mcast(mn_topo, switches, p4info_helper):
    """
    Install multicast groups using P4Runtime (preferred):
      - For each switch, for each ingress port (we use ingress port as group id here),
        create a multicast group whose replicas are the desired egress ports.
    Notes:
      - This avoids parsing CLI output and avoids using non-existent PRE handles.
      - Uses p4info_helper.buildMulticastGroupEntry + Switch.WriteMCastEntry.
    """
    def is_upstream(x, y):
        return x[0] == y[0] and int(x[1:]) < int(y[1:])  # use [1:] for multi-digit safety

    # build topology graph
    G = nx.Graph()
    G.add_edges_from(mn_topo.links())

    for sw in mn_topo.switches():
        # collect adjacency list for this switch (list, not iterator)
        adjacents = [edge[1] if edge[0] == sw else edge[0] for edge in G.edges(sw)]
        for adj in adjacents:
            # determine downstream set depending on upstream/downstream relation
            if is_upstream(sw, adj):
                mcast_adjs = [a for a in adjacents if not is_upstream(sw, a)]
            else:
                mcast_adjs = [a for a in adjacents if a != adj]

            # convert adjacency nodes to ports on the switch
            egress_ports = [mn_topo.port(sw, a)[0] for a in mcast_adjs]
            ingress_port = mn_topo.port(sw, adj)[0]

            # use ingress_port as multicast group id (this pattern was used previously)
            mcast_grp_id = int(ingress_port)

            # Build P4Runtime PacketReplicationEngineEntry and program it via P4Runtime
            entry = p4info_helper.buildMulticastGroupEntry(mcast_grp_id, ports=egress_ports)
            # Write to the switch using the switch wrapper's WriteMCastEntry
            switches[sw].WriteMCastEntry(entry, dry_run=debug)


def install_hula_logic(mn_topo, switches, p4info_helper):
    """Install HULA packet processing table entries."""
    for sw in mn_topo.switches():
        # buildTableEntry signature in your helper is: buildTableEntry(table, match_fields=..., action_name=..., action_params=..., ...)
        add_hula_handle_probe = p4info_helper.buildTableEntry(
            "MyIngress.hula_logic",
            match_fields={"hdr.ipv4.protocol": 0x42},
            action_name="MyIngress.hula_handle_probe",
            action_params={}
        )

        add_hula_handle_data_packet = p4info_helper.buildTableEntry(
            "MyIngress.hula_logic",
            match_fields={"hdr.ipv4.protocol": 0x06},
            action_name="MyIngress.hula_handle_data_packet",
            action_params={}
        )

        switches[sw].WriteTableEntry(add_hula_handle_probe, dry_run=debug)
        switches[sw].WriteTableEntry(add_hula_handle_data_packet, dry_run=debug)


def install_tables(mn_topo, switches, p4info_helper):
    """Install forwarding and host->ToR mapping tables."""
    install_hula_logic(mn_topo, switches, p4info_helper)

    for (x, y) in mn_topo.links():
        switch = None
        host = None

        if x.startswith("h") and y.startswith("s"):
            switch = y
            host = x
        elif y.startswith("h") and x.startswith("s"):
            switch = x
            host = y
        else:
            continue

        host_ip = mn_topo.nodeInfo(host)['ip'].split('/')[0]
        dst_tor_num = int(switch[1:])
        port = mn_topo.port(switch, host)[0]

        # Edge forwarding rule
        add_edge_forward = p4info_helper.buildTableEntry(
            "MyIngress.edge_forward",
            match_fields={"hdr.ipv4.dstAddr": host_ip},
            action_name="MyIngress.simple_forward",
            action_params={"port": port}
        )
        switches[switch].WriteTableEntry(add_edge_forward, dry_run=debug)

        # Install host -> ToR mapping for every switch
        for sw in mn_topo.switches():
            self_id = int(sw[1:])  # switch name like "s100" -> 100
            add_host_dst_tor = p4info_helper.buildTableEntry(
                "MyIngress.get_dst_tor",
                match_fields={"hdr.ipv4.dstAddr": host_ip},
                action_name="MyIngress.set_dst_tor",
                action_params={"dst_tor": dst_tor_num, "self_id": self_id}
            )
            switches[sw].WriteTableEntry(add_host_dst_tor, dry_run=debug)

def monitor_stability(switches):

    current_interval = BASE_INTERVAL
    stable_counter = 0
    last_best_hop_state = {}

    while True:
        state_changed = False
        

        for sw_name, sw in switches.items():
            try:
                for tor in range(512):
                    entry = sw.ReadRegister("MyIngress.best_hop", tor)

                    key = (sw_name, tor)

                    if key not in last_best_hop_state:
                        last_best_hop_state[key] = entry
                    else:
                        if last_best_hop_state[key] != entry:
                            state_changed = True
                            last_best_hop_state[key] = entry

            except:
                continue

        if state_changed:
            current_interval = BASE_INTERVAL
            stable_counter = 0
        else:
            stable_counter += 1
            if stable_counter >= STABLE_THRESHOLD:
                current_interval = min(current_interval * 2, MAX_INTERVAL)

        with open(INTERVAL_FILE, "w") as f:
            f.write(str(current_interval))

        time.sleep(CHECK_INTERVAL)


def main(p4info_file_path, bmv2_file_path, topo_file_path):
    """Main controller function."""
    # load p4info text file
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(p4info_file_path)

    try:
        switches, mn_topo = load_topology(topo_file_path)

        # master arbitration
        for bmv2_switch in switches.values():
            bmv2_switch.MasterArbitrationUpdate()
            print(f"Established as controller for {bmv2_switch.name}")

        # install pipeline
        for bmv2_switch in switches.values():
            bmv2_switch.SetForwardingPipelineConfig(
                p4info=p4info_helper.p4info,
                bmv2_json_file_path=bmv2_file_path
            )
            print(f"Installed P4 Program using SetForwardingPipelineConfig on {bmv2_switch.name}")

        # program multicast and tables via P4Runtime
        install_smart_mcast(mn_topo, switches, p4info_helper)
        install_tables(mn_topo, switches, p4info_helper)
        # Start adaptive probe monitoring thread
        monitor_thread = threading.Thread(
            target=monitor_stability,
            args=(switches,),
            daemon=True
        )
        monitor_thread.start()


        # Keep controller alive
        while True:
            time.sleep(10)

    except KeyboardInterrupt:
        print(" Shutting down.")
    except grpc.RpcError as e:
        printGrpcError(e)
    finally:
        ShutdownAllSwitchConnections()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P4Runtime Controller")
    parser.add_argument('--p4info', help='p4info proto in text format from p4c',
                        type=str, required=False, default='./build/switch.p4info')
    parser.add_argument('--bmv2-json', help='BMv2 JSON file from p4c',
                        type=str, required=False, default='./build/switch.json')
    parser.add_argument('--topo', help='Topology file',
                        type=str, required=False, default='topology.json')
    args = parser.parse_args()

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

    main(args.p4info, args.bmv2_json, args.topo)
