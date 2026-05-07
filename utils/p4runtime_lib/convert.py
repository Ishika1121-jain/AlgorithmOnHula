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

import re
import socket
import math

"""
This package contains helper functions for encoding to / decoding from byte strings:
- integers
- IPv4 address strings
- Ethernet address strings
"""

# ==========================================================
# MAC ENCODE / DECODE
# ==========================================================

mac_pattern = re.compile(r'^([\da-fA-F]{2}:){5}([\da-fA-F]{2})$')

def matchesMac(mac_addr_string):
    return mac_pattern.match(mac_addr_string) is not None


def encodeMac(mac_addr_string):
    """Converts aa:bb:cc:dd:ee:ff → b'\xaa\xbb\xcc\xdd\xee\xff'"""
    hex_str = mac_addr_string.replace(':', '')
    return bytes.fromhex(hex_str)


def decodeMac(encoded_mac_addr):
    """Converts b'\xaa\xbb\xcc\xdd\xee\xff' → aa:bb:cc:dd:ee:ff"""
    return ':'.join(f'{b:02x}' for b in encoded_mac_addr)


# ==========================================================
# IPv4 ENCODE / DECODE
# ==========================================================

ip_pattern = re.compile(r'^(\d{1,3}\.){3}(\d{1,3})$')

def matchesIPv4(ip_addr_string):
    return ip_pattern.match(ip_addr_string) is not None


def encodeIPv4(ip_addr_string):
    return socket.inet_aton(ip_addr_string)


def decodeIPv4(encoded_ip_addr):
    return socket.inet_ntoa(encoded_ip_addr)


# ==========================================================
# INTEGER ENCODE / DECODE
# ==========================================================

def bitwidthToBytes(bitwidth):
    return int(math.ceil(bitwidth / 8.0))


def encodeNum(number, bitwidth):
    """
    Encode number into byte string of correct width.
    Example: number=1337, bitwidth=32 → b'\x00\x00\x05\x39'
    """
    byte_len = bitwidthToBytes(bitwidth)

    if number >= 2 ** bitwidth:
        raise Exception(f"Number {number} does not fit in {bitwidth} bits")

    # Convert number to hex string without '0x'
    hex_str = f'{number:0{byte_len * 2}x}'

    return bytes.fromhex(hex_str)


def decodeNum(encoded_bytes):
    """Convert b'\x00\x00\x05\x39' → 1337"""
    return int.from_bytes(encoded_bytes, byteorder='big')


# ==========================================================
# MAIN ENCODER
# ==========================================================

def encode(x, bitwidth):
    """
    Automatically detect type and encode:
    - MAC
    - IPv4
    - Integer
    """
    byte_len = bitwidthToBytes(bitwidth)

    if isinstance(x, (list, tuple)) and len(x) == 1:
        x = x[0]

    if isinstance(x, str):
        if matchesMac(x):
            encoded = encodeMac(x)
        elif matchesIPv4(x):
            encoded = encodeIPv4(x)
        else:
            # Assume already encoded string of bytes → convert to bytes
            encoded = bytes.fromhex(x)
    elif isinstance(x, int):
        encoded = encodeNum(x, bitwidth)
    else:
        raise Exception(f"Unsupported type {type(x)}: {x}")

    if len(encoded) != byte_len:
        raise Exception(f"Encoded length {len(encoded)} != expected {byte_len}")

    return encoded


# ==========================================================
# TESTS (optional)
# ==========================================================

if __name__ == '__main__':
    # MAC Test
    mac = "aa:bb:cc:dd:ee:ff"
    enc_mac = encodeMac(mac)
    assert enc_mac == b'\xaa\xbb\xcc\xdd\xee\xff'
    assert decodeMac(enc_mac) == mac

    # IPv4 Test
    ip = "10.0.0.1"
    enc_ip = encodeIPv4(ip)
    assert enc_ip == b'\x0a\x00\x00\x01'
    assert decodeIPv4(enc_ip) == ip

    # Integer test
    num = 1337
    enc_num = encodeNum(num, 40)  # 5 bytes
    assert enc_num == b'\x00\x00\x00\x05\x39'
    assert decodeNum(enc_num) == num

    # Type detection test
    assert encode(mac, 48) == enc_mac
    assert encode(ip, 32) == enc_ip
    assert encode(num, 40) == enc_num
    assert encode((num,), 40) == enc_num
    assert encode([num], 40) == enc_num

    print("All tests passed!")

