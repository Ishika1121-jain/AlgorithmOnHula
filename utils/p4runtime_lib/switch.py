#!/usr/bin/env python3
# Copyright 2017-present Open Networking Foundation
# Cleaned, Python3-friendly version of utils/p4runtime_lib/switch.py
#
# - Loads local generated protobuf modules from build/ explicitly (avoids
#   colliding with any system-installed 'p4' package).
# - Uses p4runtime_pb2_grpc.P4RuntimeStub for gRPC client stub.
# - Accepts BMv2 device config as raw bytes (assigns bytes directly to
#   request.config.p4_device_config).
#
import os
import sys
import importlib.util
from abc import abstractmethod
from datetime import datetime
import grpc
import queue  # Python 3
from typing import Optional

MSG_LOG_MAX_LEN = 1024

# --- Helper: import a module from a specific path (filename) ---
def _import_module_from_file(module_name: str, file_path: str):
    """Load Python module from file_path and return the module object."""
    if not os.path.isfile(file_path):
        raise ImportError(f"Module file not found: {file_path}")
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {module_name} from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore
    return module

# --- Ensure local build/ is used for generated protobufs ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
BUILD_DIR = os.path.join(BASE_DIR, "build")
if BUILD_DIR not in sys.path:
    sys.path.insert(0, BUILD_DIR)

# Paths to expected generated files
_p4runtime_pb2_path = os.path.join(BUILD_DIR, "p4runtime_pb2.py")
_p4runtime_pb2_grpc_path = os.path.join(BUILD_DIR, "p4runtime_pb2_grpc.py")

try:
    p4runtime_pb2 = _import_module_from_file("p4runtime_pb2", _p4runtime_pb2_path)
    p4runtime_pb2_grpc = _import_module_from_file("p4runtime_pb2_grpc", _p4runtime_pb2_grpc_path)
except Exception as e:
    raise ImportError(
        f"❌ Could not import generated p4runtime protobuf modules from {BUILD_DIR}: {e}\n"
        "Make sure you generated them with protoc (and grpc tools) into the build/ directory."
    ) from e

# Keep global list of active connections for graceful shutdown
connections = []

def ShutdownAllSwitchConnections():
    for c in list(connections):
        try:
            c.shutdown()
        except Exception:
            pass

# IterableQueue used to feed StreamChannel (acts like an iterator)
class IterableQueue(queue.Queue):
    _sentinel = object()

    def __iter__(self):
        # iter(self.get, self._sentinel)
        return iter(self.get, self._sentinel)

    def close(self):
        self.put(self._sentinel)

class GrpcRequestLogger(grpc.UnaryUnaryClientInterceptor,
                        grpc.UnaryStreamClientInterceptor):
    """gRPC interceptor that logs requests to a file (simple)."""

    def __init__(self, log_file: str):
        self.log_file = log_file
        # ensure directory exists
        log_dir = os.path.dirname(self.log_file) or "."
        if log_dir and not os.path.isdir(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except Exception:
                # ignore; permission errors will surface when opening file
                pass
        # clear/overwrite file
        try:
            with open(self.log_file, "w") as f:
                f.write("")  # clear
        except Exception:
            # permission errors will be raised later when writing; just don't crash here
            pass

    def log_message(self, method_name: str, body):
        try:
            with open(self.log_file, "a") as f:
                ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                msg = str(body)
                f.write("\n[%s] %s\n---\n" % (ts, method_name))
                if len(msg) < MSG_LOG_MAX_LEN:
                    f.write(msg)
                else:
                    f.write("Message too long (%d bytes)! Skipping log...\n" % len(msg))
                f.write("\n---\n")
        except Exception:
            # don't raise logging errors to avoid breaking runtime flows
            pass

    # interceptor methods
    def intercept_unary_unary(self, continuation, client_call_details, request):
        self.log_message(client_call_details.method, request)
        return continuation(client_call_details, request)

    def intercept_unary_stream(self, continuation, client_call_details, request):
        self.log_message(client_call_details.method, request)
        return continuation(client_call_details, request)

class SwitchConnection(object):
    """Represents a controller connection to a P4Runtime switch."""

    def __init__(self, name: Optional[str]=None,
                 address: str='127.0.0.1:50051',
                 device_id: int=0,
                 proto_dump_file: Optional[str]=None):
        self.name = name
        self.address = address
        self.device_id = int(device_id)
        self.p4info = None  # will be set by caller
        # create insecure channel (example uses insecure)
        self.channel = grpc.insecure_channel(self.address)
        if proto_dump_file:
            interceptor = GrpcRequestLogger(proto_dump_file)
            # wrap the channel with interceptor
            self.channel = grpc.intercept_channel(self.channel, interceptor)

        # Use GRPC stub from generated _grpc module
        try:
            self.client_stub = p4runtime_pb2_grpc.P4RuntimeStub(self.channel)
        except Exception as e:
            raise RuntimeError(f"Failed to create P4RuntimeStub: {e}") from e

        # stream API helper
        self.requests_stream = IterableQueue()
        # Create stream response generator by calling StreamChannel RPC
        try:
            # StreamChannel is a bidi streaming RPC: stub.StreamChannel(request_iterator)
            self.stream_msg_resp = self.client_stub.StreamChannel(iter(self.requests_stream))
        except Exception:
            # if StreamChannel isn't available or fails, set to None and continue;
            # callers should handle None appropriately.
            self.stream_msg_resp = None

        self.proto_dump_file = proto_dump_file
        self.current_handle_id = 0
        connections.append(self)

    def getAndUpdateHandleId(self) -> int:
        self.current_handle_id += 1
        return self.current_handle_id - 1

    @abstractmethod
    def buildDeviceConfig(self, **kwargs):
        """
        Should return the device config for SetForwardingPipelineConfig.
        For BMv2 this is typically raw JSON bytes; other platforms may return
        a protobuf message. Implementations should return either bytes or a
        protobuf-like object depending on platform.
        """
        return b""

    def shutdown(self):
        try:
            self.requests_stream.close()
        except Exception:
            pass
        try:
            if self.stream_msg_resp is not None:
                # Attempt to cancel generator / close stream
                try:
                    self.stream_msg_resp.cancel()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            connections.remove(self)
        except ValueError:
            pass

    def MasterArbitrationUpdate(self, dry_run: bool=False, **kwargs):
        req = p4runtime_pb2.StreamMessageRequest()
        req.arbitration.device_id = int(self.device_id)
        req.arbitration.election_id.high = 0
        req.arbitration.election_id.low = 1

        if dry_run:
            print("P4Runtime MasterArbitrationUpdate:", req)
            return None
        else:
            # push into the request queue for the stream
            self.requests_stream.put(req)
            # wait for the corresponding response on the stream
            if self.stream_msg_resp is None:
                raise RuntimeError("StreamChannel not available")
            for item in self.stream_msg_resp:
                return item  # return the first item

    def SetForwardingPipelineConfig(self, p4info, dry_run: bool=False, **kwargs):
        """
        p4info: a p4info protobuf message (text->parsed) - should be assigned to config.p4info
        buildDeviceConfig should return bytes for bmv2, or a protobuf P4DeviceConfig for other hw.
        """
        device_config = self.buildDeviceConfig(**kwargs)

        request = p4runtime_pb2.SetForwardingPipelineConfigRequest()
        request.election_id.low = 1
        request.device_id = int(self.device_id)
        config = request.config

        # copy p4info proto into request
        config.p4info.CopyFrom(p4info)

        # BMv2 expects raw JSON bytes: set directly if bytes
        # For other platforms, device_config may be a proto message; attempt SerializeToString if so.
        if isinstance(device_config, (bytes, bytearray)):
            config.p4_device_config = bytes(device_config)
        else:
            # try protobuf serialization fallback
            try:
                config.p4_device_config = device_config.SerializeToString()
            except Exception:
                # As a last resort, try to accept whatever the buildDeviceConfig returned
                # (this will likely fail server-side if invalid)
                config.p4_device_config = device_config

        request.action = p4runtime_pb2.SetForwardingPipelineConfigRequest.VERIFY_AND_COMMIT

        if dry_run:
            print("P4Runtime SetForwardingPipelineConfig:", request)
        else:
            self.client_stub.SetForwardingPipelineConfig(request)

    def WriteMCastEntry(self, mcast_entry, dry_run: bool=False):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = int(self.device_id)
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.INSERT
        update.entity.packet_replication_engine_entry.CopyFrom(mcast_entry)
        if dry_run:
            print("P4Runtime Write (MCast):", request)
        else:
            self.client_stub.Write(request)

    def WriteTableEntry(self, table_entry, dry_run: bool=False):
        request = p4runtime_pb2.WriteRequest()
        request.device_id = int(self.device_id)
        request.election_id.low = 1
        update = request.updates.add()
        update.type = p4runtime_pb2.Update.INSERT
        update.entity.table_entry.CopyFrom(table_entry)
        if dry_run:
            print("P4Runtime Write (Table):", request)
        else:
            self.client_stub.Write(request)

    def ReadMCastEntries(self, mcast_grp_id: Optional[int]=None, dry_run: bool=False):
        req = p4runtime_pb2.ReadRequest()
        req.device_id = int(self.device_id)
        entity = req.entities.add()
        mcast_entry = entity.packet_replication_engine_entry.multicast_group_entry
        if mcast_grp_id is not None:
            mcast_entry.multicast_group_id = int(mcast_grp_id)
        else:
            mcast_entry.multicast_group_id = 0

        if dry_run:
            print("P4Runtime Read (MCast):", req)
            return
        else:
            for response in self.client_stub.Read(req):
                yield response

    def ReadTableEntries(self, table_id: Optional[int]=None, dry_run: bool=False):
        req = p4runtime_pb2.ReadRequest()
        req.device_id = int(self.device_id)
        entity = req.entities.add()
        table_entry = entity.table_entry
        if table_id is not None:
            table_entry.table_id = int(table_id)
        else:
            table_entry.table_id = 0
        if dry_run:
            print("P4Runtime Read (Table):", req)
            return
        else:
            for response in self.client_stub.Read(req):
                yield response

    def ReadCounters(self, counter_id: Optional[int]=None, index: Optional[int]=None, dry_run: bool=False):
        req = p4runtime_pb2.ReadRequest()
        req.device_id = int(self.device_id)
        entity = req.entities.add()
        counter_entry = entity.counter_entry
        if counter_id is not None:
            counter_entry.counter_id = int(counter_id)
        else:
            counter_entry.counter_id = 0
        if index is not None:
            counter_entry.index.index = int(index)
        if dry_run:
            print("P4Runtime Read (Counter):", req)
            return
        else:
            for response in self.client_stub.Read(req):
                yield response

    def ReadRegisters(self, register_id: Optional[int]=None, index: Optional[int]=None, dry_run: bool=False):
        req = p4runtime_pb2.ReadRequest()
        req.device_id = int(self.device_id)
        entity = req.entities.add()
        register_entry = entity.register_entry
        if register_id is not None:
            register_entry.register_id = int(register_id)
        else:
            register_entry.register_id = 0
        if index is not None:
            register_entry.index.index = int(index)
        if dry_run:
            print("P4Runtime Read (Register):", req)
            return
        else:
            for response in self.client_stub.Read(req):
                yield response

