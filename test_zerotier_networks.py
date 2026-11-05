import subprocess
import tempfile
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import zerotier_networks as zt


class ZeroTierNetworksTests(unittest.TestCase):
    def test_memberships_show_names_and_each_assigned_ipv4(self):
        choices = zt.parse_networks([
            {'id': 'network-a', 'name': 'Naruto Netplay', 'status': 'OK',
             'assignedAddresses': ['192.168.195.14/24', 'fd00::1/64', '192.168.195.14/24', '10.1.2.3/8']},
            {'nwid': 'network-b', 'name': 'Another network', 'status': 'ACCESS_DENIED',
             'assignedAddresses': ['10.2.3.4/8']},
            {'nwid': 'network-c', 'status': 'OK', 'assignedAddresses': ['172.22.0.1/16']},
        ])
        self.assertEqual(len(choices), 3)
        self.assertIn({'name': 'Naruto Netplay', 'address': '192.168.195.14', 'id': 'network-a'}, choices)
        self.assertIn({'name': 'network-c', 'address': '172.22.0.1', 'id': 'network-c'}, choices)

    def test_interface_fallback_ignores_physical_network_and_ipv6(self):
        choices = zt.parse_interfaces([
            {'ifname': 'wlan0', 'addr_info': [{'family': 'inet', 'local': '192.168.1.5'}]},
            {'ifname': 'ztabc123', 'addr_info': [{'family': 'inet', 'local': '192.168.195.14'},
                                              {'family': 'inet6', 'local': 'fd00::1'}]},
        ])
        self.assertEqual(choices, [{'name': 'ZeroTier (ztabc123)', 'address': '192.168.195.14', 'id': ''}])

    def test_malformed_results_do_not_offer_invalid_addresses(self):
        for payload in (None, {}, 'error', [None, 3], [{'status': 'OK', 'assignedAddresses': [None, 'bad', '0.0.0.0', '::1']}]):
            self.assertEqual(zt.parse_networks(payload), [])
        self.assertEqual(zt.parse_interfaces(None), [])

    @patch('zerotier_networks._cli_path', return_value='/usr/bin/zerotier-cli')
    @patch('zerotier_networks._query')
    def test_discovery_does_not_prompt_for_privileges_automatically(self, query, cli):
        query.return_value = [{'name': 'Netplay', 'id': 'abc', 'status': 'OK', 'assignedAddresses': ['10.1.2.3/24']}]
        choices, status = zt.discover()
        self.assertEqual(choices[0]['address'], '10.1.2.3')
        self.assertEqual(status, 'hill.zt.found')
        query.assert_called_once_with(['/usr/bin/zerotier-cli', '-j', 'listnetworks'])

    @patch('zerotier_networks._cli_path', return_value='/usr/bin/zerotier-cli')
    @patch('zerotier_networks.shutil.which', side_effect=lambda name: '/usr/bin/'+name)
    @patch('zerotier_networks._query')
    def test_permission_failure_falls_back_to_interfaces_without_sudo(self, query, which, cli):
        query.side_effect = [None, [{'ifname': 'ztabc', 'addr_info': [{'family': 'inet', 'local': '10.1.2.3'}]}]]
        choices, status = zt.discover()
        self.assertEqual(choices[0]['address'], '10.1.2.3')
        self.assertEqual(status, 'hill.zt.interfaces')
        self.assertEqual(query.call_args.args[0], ['/usr/bin/ip', '-j', '-4', 'address', 'show'])

    @patch('zerotier_networks.os.name', 'posix')
    @patch('zerotier_networks._cli_path', return_value='/usr/bin/zerotier-cli')
    @patch('zerotier_networks.shutil.which', return_value='/usr/bin/pkexec')
    @patch('zerotier_networks._query')
    def test_explicit_authorization_only_runs_readonly_network_listing(self, query, which, cli):
        query.side_effect = [None, [{'name': 'Netplay', 'id': 'abc', 'status': 'OK', 'assignedAddresses': ['10.1.2.3/24']}]]
        choices, status = zt.discover(allow_admin=True)
        self.assertEqual(status, 'hill.zt.found')
        self.assertEqual(choices[0]['name'], 'Netplay')
        query.assert_called_with(['/usr/bin/pkexec', '/usr/bin/zerotier-cli', '-j', 'listnetworks'], timeout=60)

    @patch('zerotier_networks.subprocess.run', side_effect=subprocess.TimeoutExpired('zerotier-cli', 4))
    def test_unresponsive_service_returns_control(self, run):
        self.assertIsNone(zt._query(['zerotier-cli', '-j', 'listnetworks']))

    @patch('zerotier_networks._cli_path', return_value='/usr/bin/zerotier-cli')
    @patch('zerotier_networks.shutil.which', side_effect=lambda name: '/usr/bin/'+name)
    @patch('zerotier_networks._query')
    def test_real_name_is_remembered_and_paired_with_current_interface_ip(self, query, which, cli):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)/'networks.json'
            query.return_value = [{'id': 'abc', 'name': 'SSSS Online', 'status': 'OK',
                                   'portDeviceName': 'ztabc', 'assignedAddresses': ['192.168.195.14/24']}]
            choices, _ = zt.discover(cache_path=cache)
            self.assertEqual(choices[0]['name'], 'SSSS Online')
            query.side_effect = [None, [{'ifname': 'ztabc', 'addr_info': [{'family': 'inet', 'local': '192.168.195.15'}]}]]
            choices, status = zt.discover(cache_path=cache)
            self.assertEqual(choices[0]['name'], 'SSSS Online')
            self.assertEqual(choices[0]['address'], '192.168.195.15')
            self.assertEqual(status, 'hill.zt.cached')
            self.assertNotIn('secret', cache.read_text())

    def test_cache_does_not_offer_disconnected_networks_or_rename_another_interface(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)/'networks.json'
            cache.write_text(json.dumps([{'name': 'SSSS Online', 'id': 'abc',
                                         'address': '10.1.2.3', 'interface': 'ztoriginal'}]))
            current = [{'name': 'ZeroTier (ztdifferent)', 'address': '10.1.2.3', 'id': ''}]
            choices, restored = zt._restore_names(cache, current)
            self.assertEqual(choices, current)
            self.assertFalse(restored)
            self.assertEqual(zt._restore_names(cache, []), ([], False))


if __name__ == '__main__':
    unittest.main()
