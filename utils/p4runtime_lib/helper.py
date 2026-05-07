#!/usr/bin/env python3
"""
P4Runtime helper that loads ONLY local protobufs from build/
and provides a buildTableEntry(...) compatible with the controller.
Drop this file into utils/p4runtime_lib/helper.py (replace existing file).
"""

import os
import sys
import importlib.util
from google.protobuf import text_format

# --- locate build dir (where generated pb2 files live) ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
BUILD_DIR = os.path.join(BASE_DIR, "build")

if BUILD_DIR not in sys.path:
    sys.path.insert(0, BUILD_DIR)


def _load_module_from_file(name, filepath):
    """Load module by path (avoids importing system-installed packages)."""
    if not os.path.isfile(filepath):
        raise ImportError(f"Missing file: {filepath}")
    spec = importlib.util.spec_from_file_location(name, filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- load local generated protobuf modules ---
p4runtime_pb2 = _load_module_from_file("p4runtime_pb2", os.path.join(BUILD_DIR, "p4runtime_pb2.py"))
p4info_pb2 = _load_module_from_file("p4info_pb2", os.path.join(BUILD_DIR, "p4info_pb2.py"))

# --- local convert utility (encode/decode helpers) ---
_convert_path = os.path.join(os.path.dirname(__file__), "convert.py")
convert = _load_module_from_file("p4runtime_convert", _convert_path)


class P4InfoHelper(object):
    """
    Lightweight helper to read text-format p4info and build P4Runtime table entries.
    Compatible call used by controller:
        buildTableEntry(table_name="MyIngress.table", match_fields={...}, action_name="...", action_params={...})
    """

    def __init__(self, p4info_txt_path):
        if not os.path.isfile(p4info_txt_path):
            raise FileNotFoundError(f"p4info text file not found: {p4info_txt_path}")

        # load text-format P4Info into protobuf message
        self.p4info = p4info_pb2.P4Info()
        with open(p4info_txt_path, "r") as f:
            text_format.Merge(f.read(), self.p4info)

    # Generic lookup helpers ------------------------------------------------

    def get(self, entity, name=None, id=None):
        """Return the proto object of `entity` (e.g. 'tables', 'actions') by name or id."""
        for e in getattr(self.p4info, entity):
            pre = e.preamble
            if name and (pre.name == name or getattr(pre, "alias", None) == name):
                return e
            if id is not None and pre.id == id:
                return e
        raise KeyError(f"{entity} not found (name={name} id={id})")

    def get_id(self, entity, name):
        return self.get(entity, name=name).preamble.id

    def get_name(self, entity, id):
        return self.get(entity, id=id).preamble.name

    def __getattr__(self, attr):
        """
        Synthesize helpers like get_tables_id(name) or get_actions_id(name)
        if called as self.get_tables_id("MyIngress.table").
        """
        import re
        m = re.match(r"get_(\w+)_id$", attr)
        if m:
            entity = m.group(1)
            return lambda name: self.get_id(entity, name)
        m = re.match(r"get_(\w+)_name$", attr)
        if m:
            entity = m.group(1)
            return lambda id: self.get_name(entity, id)
        raise AttributeError(attr)

    # Match / action parameter helpers -------------------------------------

    def get_match_field(self, table_name, name=None, id=None):
        """Return the match field proto from table by name or id."""
        for t in self.p4info.tables:
            if t.preamble.name == table_name:
                for mf in t.match_fields:
                    if name and mf.name == name:
                        return mf
                    if id is not None and mf.id == id:
                        return mf
        raise KeyError(f"Table {table_name} match field not found (name={name} id={id})")

    def get_action_param(self, action_name, name=None, id=None):
        """Return the action param proto for action by name or id."""
        for a in self.p4info.actions:
            if a.preamble.name == action_name:
                for p in a.params:
                    if name and p.name == name:
                        return p
                    if id is not None and p.id == id:
                        return p
        raise KeyError(f"Action {action_name} param not found (name={name} id={id})")

    def get_action_param_pb(self, action_name, param_name, value):
        """Build a p4runtime Action.Param protobuf given the p4info param definition."""
        ap = self.get_action_param(action_name, name=param_name)
        p = p4runtime_pb2.Action.Param()
        p.param_id = ap.id
        p.value = convert.encode(value, ap.bitwidth)
        return p

    # Table entry builders -------------------------------------------------

    def build_match_field_pb(self, table_name, field_name, value):
        """Return a FieldMatch proto for a given table match field and value.
           (This implementation assumes EXACT matches for the common simple case.)
           If you need LPM/TERNARY/RANGE/VALID add branches using mf.match_type and mf.bitwidth.
        """
        mf = self.get_match_field(table_name, name=field_name)
        fm = p4runtime_pb2.FieldMatch()
        fm.field_id = mf.id
        # simple default: exact match
        fm.exact.value = convert.encode(value, mf.bitwidth)
        return fm

    def buildTableEntry(self,
                        table=None,
                        table_name=None,
                        match_fields=None,
                        action_name=None,
                        action_params=None,
                        priority=None,
                        default_action=False):
        """
        Build and return a p4runtime_pb2.TableEntry.

        Accepts either `table` (old style positional) or `table_name` (keyword used by controller).
        """
        if table_name is None:
            table_name = table
        if table_name is None:
            raise TypeError("buildTableEntry requires table_name= or table=")

        te = p4runtime_pb2.TableEntry()
        te.table_id = self.get_tables_id(table_name)

        # match fields
        if match_fields:
            for fname, val in match_fields.items():
                fm = self.build_match_field_pb(table_name, fname, val)
                te.match.append(fm)

        # action
        if action_name:
            act = te.action.action
            act.action_id = self.get_actions_id(action_name)
            if action_params:
                for pname, pval in action_params.items():
                    act.params.append(self.get_action_param_pb(action_name, pname, pval))

        # priority / default
        if priority is not None:
            te.priority = int(priority)
        if default_action:
            te.is_default_action = True

        return te

    def buildMulticastGroupEntry(self, mcast_grp_id, ports=None):
        """
        Build a PacketReplicationEngineEntry representing a multicast group.
        - mcast_grp_id: integer multicast group id (we used ingress port id earlier)
        - ports: iterable/list of egress port numbers
        Returns a p4runtime_pb2.PacketReplicationEngineEntry instance.
        """
        if ports is None:
            ports = []

        entry = p4runtime_pb2.PacketReplicationEngineEntry()
        entry.multicast_group_entry.multicast_group_id = int(mcast_grp_id)

        # add replicas. instance numbers must be unique per replica — enumerate from 1
        for idx, egress_port in enumerate(ports, start=1):
            replica = entry.multicast_group_entry.replicas.add()
            replica.egress_port = int(egress_port)
            replica.instance = idx

        return entry

