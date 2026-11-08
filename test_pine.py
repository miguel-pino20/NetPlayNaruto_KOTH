import unittest
from unittest.mock import MagicMock, patch

from pine import Pine


@unittest.skipIf(__import__('os').name == 'nt', 'Unix socket discovery')
class PineSocketDiscoveryTests(unittest.TestCase):
    def test_default_flatpak_runtime_and_custom_slot(self):
        for slot, suffix in ((28011, ''), (28012, '.28012')):
            expected = '/run/user/1000/.flatpak/net.pcsx2.PCSX2/xdg-run/pcsx2.sock'+suffix
            connected = []

            def make_socket(*args):
                sock = MagicMock()

                def connect(path):
                    connected.append(path)
                    if path != expected:
                        raise FileNotFoundError(2, 'No such file or directory')

                sock.connect.side_effect = connect
                return sock

            with patch.dict('os.environ', {'XDG_RUNTIME_DIR': '/run/user/1000'}), \
                    patch('pine.socket.socket', side_effect=make_socket):
                client = Pine(slot)
                self.assertIs(client.connect(), client)
                self.assertEqual(connected[-1], expected)
                self.assertEqual(len(connected), 3)
                client.close()


if __name__ == '__main__':
    unittest.main()
