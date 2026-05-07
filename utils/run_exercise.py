#!/usr/bin/env python3
# Copyright 2013-present Barefoot Networks, Inc.
# Licensed under the Apache License, Version 2.0
#
# Adapted for Python 3 and modern BMv2 / P4Runtime compatibility.

import os, sys, json, subprocess, re, argparse
from time import sleep

from p4_mininet import P4Switch, P4Host
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.cli import CLI
from p4runtime_switch import P4RuntimeSwitch
import p4runtime_lib.simple_controller


def configureP4Switch(**switch_args):
    """Helper for initializing virtual P4 switches with unique thrift ports."""
    if "sw_path" in switch_args and 'grpc' in switch_args['sw_path']:
        class ConfiguredP4RuntimeSwitch(P4RuntimeSwitch):
            def __init__(self, *opts, **kwargs):
                kwargs.update(switch_args)
                P4RuntimeSwitch.__init__(self, *opts, **kwargs)

            def describe(self):
                print(f"{self.name} -> gRPC port: {self.grpc_port}")

        return ConfiguredP4RuntimeSwitch
    else:
        class ConfiguredP4Switch(P4Switch):
            next_thrift_port = 9090

            def __init__(self, *opts, **kwargs):
                kwargs.update(switch_args)
                kwargs['thrift_port'] = ConfiguredP4Switch.next_thrift_port
                ConfiguredP4Switch.next_thrift_port += 1
                P4Switch.__init__(self, *opts, **kwargs)

            def describe(self):
                print(f"{self.name} -> Thrift port: {self.thrift_port}")

        return ConfiguredP4Switch


class ExerciseTopo(Topo):
    """Mininet topology used in the P4 tutorial exercises."""

    def __init__(self, hosts, switches, links, log_dir, **opts):
        Topo.__init__(self, **opts)
        host_links = []
        switch_links = []
        self.sw_port_mapping = {}

        for link in links:
            if link['node1'][0] == 'h':
                host_links.append(link)
            else:
                switch_links.append(link)

        link_sort_key = lambda x: x['node1'] + x['node2']
        host_links.sort(key=link_sort_key)
        switch_links.sort(key=link_sort_key)

        for sw in switches:
            self.addSwitch(sw, log_file=f"{log_dir}/{sw}.log")

        for link in host_links:
            host_name = link['node1']
            host_sw = link['node2']
            host_num = int(host_name[1:])
            sw_num = int(host_sw[1:])
            host_ip = f"10.0.{sw_num}.{host_num}"
            host_mac = f"00:00:00:00:{sw_num:02x}:{host_num:02x}"
            self.addHost(host_name, ip=f"{host_ip}/24", mac=host_mac)
            self.addLink(host_name, host_sw,
                         delay=link['latency'], bw=link['bandwidth'],
                         addr1=host_mac, addr2=host_mac)
            self.addSwitchPort(host_sw, host_name)

        for link in switch_links:
            self.addLink(link['node1'], link['node2'],
                         delay=link['latency'], bw=link['bandwidth'])
            self.addSwitchPort(link['node1'], link['node2'])
            self.addSwitchPort(link['node2'], link['node1'])

        self.printPortMapping()

    def addSwitchPort(self, sw, node2):
        if sw not in self.sw_port_mapping:
            self.sw_port_mapping[sw] = []
        portno = len(self.sw_port_mapping[sw]) + 1
        self.sw_port_mapping[sw].append((portno, node2))

    def printPortMapping(self):
        print("Switch port mapping:")
        for sw in sorted(self.sw_port_mapping.keys()):
            print(f"{sw}: ", end="")
            for portno, node2 in self.sw_port_mapping[sw]:
                print(f"{portno}:{node2}\t", end="")
            print()


def formatLatency(l):
    """Helper for formatting link latencies."""
    if isinstance(l, str):
        return l
    else:
        return str(l) + "ms"


def parse_links(unparsed_links):
    """Parse links from JSON into structured dictionaries."""
    links = []
    for link in unparsed_links:
        s, t = link[0], link[1]
        if s > t:
            s, t = t, s

        link_dict = {
            'node1': s,
            'node2': t,
            'latency': '0ms',
            'bandwidth': None
        }
        if len(link) > 2:
            link_dict['latency'] = formatLatency(link[2])
        if len(link) > 3:
            link_dict['bandwidth'] = link[3]
        if link_dict['node1'][0] == 'h':
            assert link_dict['node2'][0] == 's', \
                f"Hosts should connect to switches, not {link_dict['node2']}"
        links.append(link_dict)
    return links


class ExerciseRunner:
    """Main class to run the P4 Mininet exercises."""

    def logger(self, *items):
        if not self.quiet:
            print(' '.join(items))

    def __init__(self, topo_file, log_dir, pcap_dir,
                 switch_json, bmv2_exe='simple_switch', quiet=False):
        self.quiet = quiet
        self.logger('Reading topology file.')
        with open(topo_file, 'r') as f:
            topo = json.load(f)
        self.hosts = topo['hosts']
        self.switches = topo['switches']
        self.links = parse_links(topo['links'])

        for dir_name in [log_dir, pcap_dir]:
            if not os.path.isdir(dir_name):
                os.makedirs(dir_name, exist_ok=True)

        self.log_dir = log_dir
        self.pcap_dir = pcap_dir
        self.switch_json = switch_json
        self.bmv2_exe = bmv2_exe

    def run_exercise(self):
        """Main entrypoint: create, start, and configure Mininet."""
        self.create_network()
        self.net.start()
        sleep(1)

        self.program_hosts()
        self.program_switches()

        sleep(1)
        self.do_net_cli()
        self.net.stop()

    def create_network(self):
        self.logger("Building Mininet topology.")
        self.topo = ExerciseTopo(self.hosts, self.switches.keys(),
                                 self.links, self.log_dir)

        switchClass = configureP4Switch(
            sw_path=self.bmv2_exe,
            json_path=self.switch_json,
            log_console=True,
            pcap_dump=self.pcap_dir)

        self.net = Mininet(topo=self.topo,
                           link=TCLink,
                           host=P4Host,
                           switch=switchClass,
                           controller=None)

    def program_switch_p4runtime(self, sw_name, sw_dict):
        sw_obj = self.net.get(sw_name)
        grpc_port = sw_obj.grpc_port
        device_id = sw_obj.device_id
        runtime_json = sw_dict['runtime_json']
        self.logger(f'Configuring switch {sw_name} with {runtime_json}')
        with open(runtime_json, 'r') as sw_conf_file:
            outfile = f'{self.log_dir}/{sw_name}-p4runtime-requests.txt'
            p4runtime_lib.simple_controller.program_switch(
                addr=f'127.0.0.1:{grpc_port}',
                device_id=device_id,
                sw_conf_file=sw_conf_file,
                workdir=os.getcwd(),
                proto_dump_fpath=outfile)

    def program_switch_cli(self, sw_name, sw_dict):
        cli = 'simple_switch_CLI'
        sw_obj = self.net.get(sw_name)
        thrift_port = sw_obj.thrift_port

        cli_input_commands = sw_dict['cli_input']
        self.logger(f'Configuring switch {sw_name} with file {cli_input_commands}')
        with open(cli_input_commands, 'r') as fin, \
             open(f'{self.log_dir}/{sw_name}_cli_output.log', 'w') as fout:
            subprocess.Popen([cli, '--thrift-port', str(thrift_port)],
                             stdin=fin, stdout=fout)

    def program_switches(self):
        for sw_name, sw_dict in self.switches.items():
            if 'cli_input' in sw_dict:
                self.program_switch_cli(sw_name, sw_dict)
            if 'runtime_json' in sw_dict:
                self.program_switch_p4runtime(sw_name, sw_dict)

    def program_hosts(self):
        """Adds static ARP entries and default routes to hosts."""
        for host_name in self.topo.hosts():
            h = self.net.get(host_name)
            # FIXED for Python 3
            h_iface = list(h.intfs.values())[0]

            link = h_iface.link
            sw_iface = link.intf1 if link.intf1 != h_iface else link.intf2
            host_id = int(host_name[1:])
            sw_ip = f'10.0.{host_id}.254'

            h.defaultIntf().rename(f'{host_name}-eth0')
            h.cmd(f'arp -i {h_iface.name} -s {sw_ip} {sw_iface.mac}')
            h.cmd(f'ethtool --offload {h_iface.name} rx off tx off')
            h.cmd(f'ip route add {sw_ip} dev {h_iface.name}')
            h.setDefaultRoute(f"via {sw_ip}")

    def do_net_cli(self):
        """Starts the Mininet CLI."""
        for s in self.net.switches:
            s.describe()
        for h in self.net.hosts:
            h.describe()
        print("\n=== Mininet CLI ===")
        CLI(self.net)


def get_args():
    cwd = os.getcwd()
    default_logs = os.path.join(cwd, 'logs')
    default_pcaps = os.path.join(cwd, 'pcaps')
    parser = argparse.ArgumentParser()
    parser.add_argument('-q', '--quiet', action='store_true', default=False)
    parser.add_argument('-t', '--topo', type=str, default='./topology.json')
    parser.add_argument('-l', '--log-dir', type=str, default=default_logs)
    parser.add_argument('-p', '--pcap-dir', type=str, default=default_pcaps)
    parser.add_argument('-j', '--switch_json', type=str)
    parser.add_argument('-b', '--behavioral-exe', type=str, default='simple_switch')
    return parser.parse_args()


if __name__ == '__main__':
    args = get_args()
    exercise = ExerciseRunner(args.topo, args.log_dir, args.pcap_dir,
                              args.switch_json, args.behavioral_exe, args.quiet)
    exercise.run_exercise()

