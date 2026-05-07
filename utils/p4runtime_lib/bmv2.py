# Copyright 2017-present Open Networking Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from switch import SwitchConnection

# NOTE:
# BMv2 does NOT use any protobuf device_config wrapper.
# It expects raw JSON bytes in SetForwardingPipelineConfig.config.p4_device_config

def buildDeviceConfig(bmv2_json_file_path=None):
    """Return the raw BMv2 JSON config as bytes."""
    if bmv2_json_file_path is None:
        return b""   # empty config (safe fallback)

    with open(bmv2_json_file_path, "rb") as f:
        return f.read()   # return raw binary JSON

class Bmv2SwitchConnection(SwitchConnection):
    """BMv2-specific switch connection."""
    
    def buildDeviceConfig(self, **kwargs):
        # kwargs should contain 'bmv2_json_file_path'
        return buildDeviceConfig(**kwargs)

