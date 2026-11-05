"""Discover local ZeroTier memberships without changing network configuration."""
from __future__ import annotations

import ipaddress
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import re


def _is_windows():
    return os.name == 'nt'


def _ipv4(value):
    try:
        address = ipaddress.ip_interface(value).ip
    except ValueError:
        return None
    if (address.version != 4 or address.is_loopback or address.is_unspecified
            or address.is_multicast or address.is_reserved or address.is_link_local):
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
            return json.loads(process.stdout.lstrip('\ufeff'))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def _cli_path():
    path = shutil.which('zerotier-cli')
    if path and (not _is_windows() or Path(path).suffix.lower() not in ('.bat', '.cmd')):
        return path
    if _is_windows():
        # Invoke the executable directly; Windows batch wrappers are unreliable
        # with CreateProcess and often look for the service's admin-only token.
        for root in ('ProgramData', 'PROGRAMDATA', 'ProgramFiles(x86)', 'ProgramFiles', 'ProgramW6432'):
            base = os.environ.get(root)
            if base:
                for name in ('zerotier-one_x64.exe', 'zerotier-one_x86.exe', 'zerotier-cli.exe'):
                    candidate = Path(base) / 'ZeroTier' / 'One' / name
                    if candidate.is_file():
                        return str(candidate)
    else:
        for path in ('/usr/sbin/zerotier-cli', '/usr/bin/zerotier-cli', '/usr/local/bin/zerotier-cli'):
            if Path(path).is_file():
                return path
    return None


def _cli_command(cli):
    prefix = ['-q'] if Path(cli).name.lower().startswith('zerotier-one') and cli.lower().endswith('.exe') else []
    return [cli, *prefix, '-j', 'listnetworks']


def _windows_service_networks():
    """Use ZeroTier's per-user API token only for GET /network on localhost.

    This avoids elevating the launcher and does not put the token in a process
    command line, return it to callers, cache it, or send it to a proxy/server.
    """
    local = Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData'/'Local')/'ZeroTier'
    shared = Path(os.environ.get('PROGRAMDATA') or os.environ.get('ProgramData') or 'C:/ProgramData')/'ZeroTier'/'One'
    directories = (local, local/'One', shared)
    port = 9993
    for directory in (shared, local, local/'One'):
        try:
            candidate = (directory/'zerotier-one.port').read_text(encoding='ascii').strip()
            if candidate.isdecimal() and 0 < int(candidate) <= 65535:
                port = int(candidate)
                break
        except (OSError, UnicodeError):
            pass
    for directory in directories:
        try:
            with (directory/'authtoken.secret').open(encoding='ascii') as source:
                token = source.read(4097).strip()
            if not token or len(token) > 4096 or '\r' in token or '\n' in token:
                continue
        except (OSError, UnicodeError):
            continue
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
        try:
            connection.request('GET', '/network', headers={'X-ZT1-Auth': token})
            response = connection.getresponse()
            if response.status != 200:
                continue
            raw = response.read(1024*1024+1)
            if len(raw) > 1024*1024:
                continue
            payload = json.loads(raw)
            if isinstance(payload, list):
                return payload
        except (OSError, ValueError, http.client.HTTPException):
            pass
        finally:
            connection.close()
    return None


WINDOWS_INTERFACES_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
@(Get-NetAdapter -IncludeHidden | Where-Object {
    $_.InterfaceDescription -like '*ZeroTier*' -or $_.Name -like '*ZeroTier*'
} | ForEach-Object {
    $ztAdapter = $_
    Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $ztAdapter.ifIndex -ErrorAction SilentlyContinue |
    ForEach-Object { [PSCustomObject]@{
        name = $ztAdapter.Name
        address = $_.IPAddress
    }}
}) | ConvertTo-Json -Compress
"""


def parse_windows_interfaces(payload):
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return []
    choices, seen = [], set()
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            continue
        address = _ipv4(str(item.get('address', '')))
        if address is None or (item['name'], address) in seen:
            continue
        seen.add((item['name'], address))
        identity = re.search(r'\[([0-9a-fA-F]{16})\]', item['name'])
        choices.append({'name': item['name'], 'address': address,
                        'id': identity[1].lower() if identity else '', 'interface': item['name']})
    return sorted(choices, key=lambda item: (item['name'].casefold(), item['address']))


def _windows_interfaces():
    executable = shutil.which('powershell.exe') or shutil.which('pwsh.exe')
    if not executable:
        candidate = Path(os.environ.get('SystemRoot', 'C:/Windows'))/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
        if candidate.is_file():
            executable = str(candidate)
    if not executable:
        return []
    return parse_windows_interfaces(_query([executable, '-NoLogo', '-NoProfile', '-NonInteractive',
                                            '-Command', WINDOWS_INTERFACES_SCRIPT], timeout=6))


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
        interface = choice.get('interface') or choice['name'].removeprefix('ZeroTier (').removesuffix(')')
        match = next((entry for entry in cached if isinstance(entry, dict)
                      and isinstance(entry.get('name'), str) and entry['name']
                      and ((choice.get('id') and entry.get('id') == choice['id'])
                           or (entry.get('interface') and entry['interface'] == interface)
                           or (not entry.get('interface') and entry.get('address') == choice['address']))), None)
        if match:
            choice = {**choice, 'name': match['name'], 'id': str(match.get('id', ''))}
            restored = True
        result.append(choice)
    return result, restored


def discover(allow_admin=False, cache_path=None):
    """Return choices and a UI status key. No sudo prompt during normal discovery.

    The explicit admin action only runs the fixed, read-only listnetworks command
    through polkit. On Windows, the installer-provided per-user API token is
    used only against the local service; it is never returned or cached.
    """
    if _is_windows():
        payload = _windows_service_networks()
        if isinstance(payload, list):
            choices = parse_networks(payload)
            _save_names(cache_path, choices)
            return choices, 'hill.zt.found' if choices else 'hill.zt.empty'
    cli = _cli_path()
    if cli:
        command = _cli_command(cli)
        payload = _query(command)
        if isinstance(payload, list):
            choices = parse_networks(payload)
            _save_names(cache_path, choices)
            return choices, 'hill.zt.found' if choices else 'hill.zt.empty'
        if allow_admin and not _is_windows():
            pkexec = shutil.which('pkexec')
            if pkexec:
                payload = _query([pkexec, *command], timeout=60)
                if isinstance(payload, list):
                    choices = parse_networks(payload)
                    _save_names(cache_path, choices)
                    return choices, 'hill.zt.found' if choices else 'hill.zt.empty'
    if _is_windows():
        choices = _windows_interfaces()
        if choices:
            choices, restored = _restore_names(cache_path, choices)
            return choices, 'hill.zt.cached' if restored else 'hill.zt.windows_interfaces'
        return [], 'hill.zt.unavailable'
    ip = shutil.which('ip')
    if ip:
        choices = parse_interfaces(_query([ip, '-j', '-4', 'address', 'show']))
        if choices:
            choices, restored = _restore_names(cache_path, choices)
            return choices, 'hill.zt.cached' if restored else 'hill.zt.interfaces'
    return [], 'hill.zt.unavailable'
