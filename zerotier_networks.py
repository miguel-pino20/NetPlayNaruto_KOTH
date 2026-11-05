"""Discover local ZeroTier memberships without changing network configuration."""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess


def _ipv4(value):
    try:
        address = ipaddress.ip_interface(value).ip
    except ValueError:
        return None
    if (address.version != 4 or address.is_loopback or address.is_unspecified
            or address.is_multicast or address.is_reserved):
        return None
    return str(address)


def parse_networks(payload):
    """One choice per assigned IPv4, preserving actual network names."""
    result, seen = [], set()
    if not isinstance(payload, list):
        return result
    for network in payload:
        if not isinstance(network, dict) or network.get('status') != 'OK':
            continue
        identity = str(network.get('nwid') or network.get('id') or '')
        name = str(network.get('name') or identity or 'ZeroTier')
        addresses = network.get('assignedAddresses', [])
        if not isinstance(addresses, list):
            continue
        for value in addresses:
            if not isinstance(value, str):
                continue
            address = _ipv4(value)
            if address is None or (identity, address) in seen:
                continue
            seen.add((identity, address))
            choice = {'name': name, 'address': address, 'id': identity}
            if isinstance(network.get('portDeviceName'), str) and network['portDeviceName']:
                choice['interface'] = network['portDeviceName']
            result.append(choice)
    return sorted(result, key=lambda item: (item['name'].casefold(), item['address'], item['id']))


def parse_interfaces(payload):
    """Linux fallback: ZeroTier interface names and their usable IPv4 addresses."""
    result, seen = [], set()
    if not isinstance(payload, list):
        return result
    for interface in payload:
        if not isinstance(interface, dict):
            continue
        name = interface.get('ifname', '')
        if not isinstance(name, str) or not name.startswith('zt'):
            continue
        for info in interface.get('addr_info', []):
            if not isinstance(info, dict) or info.get('family') != 'inet':
                continue
            address = _ipv4(str(info.get('local', '')))
            if address is None or (name, address) in seen:
                continue
            seen.add((name, address))
            result.append({'name': f'ZeroTier ({name})', 'address': address, 'id': ''})
    return sorted(result, key=lambda item: (item['name'], item['address']))


def _query(command, timeout=4):
    try:
        process = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                                 timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if process.returncode == 0:
            return json.loads(process.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def _cli_path():
    path = shutil.which('zerotier-cli')
    if path:
        return path
    if os.name == 'nt':
        for root in ('ProgramFiles(x86)', 'ProgramFiles', 'ProgramW6432'):
            base = os.environ.get(root)
            if base:
                candidate = Path(base) / 'ZeroTier' / 'One' / 'zerotier-cli.bat'
                if candidate.is_file():
                    return str(candidate)
    else:
        for path in ('/usr/sbin/zerotier-cli', '/usr/bin/zerotier-cli', '/usr/local/bin/zerotier-cli'):
            if Path(path).is_file():
                return path
    return None


def _save_names(path, choices):
    if path is None or not choices:
        return
    try:
        from appdata import write_json
        write_json(Path(path), choices, private=True)
    except OSError:
        pass


def _restore_names(path, interfaces):
    if path is None:
        return interfaces, False
    try:
        cached = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return interfaces, False
    if not isinstance(cached, list):
        return interfaces, False
    restored = False
    result = []
    for choice in interfaces:
        # Only restore names for interfaces/IPs that still exist on this PC.
        interface = choice['name'].removeprefix('ZeroTier (').removesuffix(')')
        match = next((entry for entry in cached if isinstance(entry, dict)
                      and isinstance(entry.get('name'), str) and entry['name']
                      and ((entry.get('interface') and entry['interface'] == interface)
                           or (not entry.get('interface') and entry.get('address') == choice['address']))), None)
        if match:
            choice = {**choice, 'name': match['name'], 'id': str(match.get('id', ''))}
            restored = True
        result.append(choice)
    return result, restored


def discover(allow_admin=False, cache_path=None):
    """Return choices and a UI status key. No sudo prompt during normal discovery.

    The explicit admin action only runs the fixed, read-only listnetworks command
    through polkit. Credentials and service auth tokens are never read or stored.
    """
    cli = _cli_path()
    if cli:
        payload = _query([cli, '-j', 'listnetworks'])
        if isinstance(payload, list):
            choices = parse_networks(payload)
            _save_names(cache_path, choices)
            return choices, 'hill.zt.found' if choices else 'hill.zt.empty'
        if allow_admin and os.name != 'nt':
            pkexec = shutil.which('pkexec')
            if pkexec:
                payload = _query([pkexec, cli, '-j', 'listnetworks'], timeout=60)
                if isinstance(payload, list):
                    choices = parse_networks(payload)
                    _save_names(cache_path, choices)
                    return choices, 'hill.zt.found' if choices else 'hill.zt.empty'
    ip = shutil.which('ip')
    if ip:
        choices = parse_interfaces(_query([ip, '-j', '-4', 'address', 'show']))
        if choices:
            choices, restored = _restore_names(cache_path, choices)
            return choices, 'hill.zt.cached' if restored else 'hill.zt.interfaces'
    return [], 'hill.zt.unavailable'
