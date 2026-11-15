import unittest
from unittest.mock import patch
from mobile.downloads import download_state


class DownloadExportTests(unittest.TestCase):
    def test_explicit_export_uses_selected_game_and_reports_location(self):
        with patch('mobile.host.prepare_files', return_value=('/private/state', '/private/symbols')) as prepare, \
                patch('mobile.downloads.publish_state', return_value=('/storage/emulated/0/Download/NarutoNetplay', True)) as publish:
            message = download_state('/private', 'un6')
        prepare.assert_called_once_with('/private', 'un6')
        publish.assert_called_once_with('/private/state', 'UN6-Netplay.p2s')
        self.assertIn('/Download/NarutoNetplay/UN6-Netplay.p2s', message)
        self.assertIn('no modifica el emulador', message)

    def test_cached_export_is_reported_as_verified(self):
        with patch('mobile.host.prepare_files', return_value=('/state', '/symbols')), \
                patch('mobile.downloads.publish_state', return_value=('/Downloads', False)) as publish:
            message = download_state('/private', 'un5')
        self.assertIn('existente verificado', message)
        publish.assert_called_once_with('/state', 'UN5-Netplay.p2s')

    def test_download_failure_never_exports_unverified_state(self):
        with patch('mobile.host.prepare_files', side_effect=ValueError('hash incorrecto')), \
                patch('mobile.downloads.publish_state') as publish:
            with self.assertRaisesRegex(ValueError, 'hash incorrecto'):
                download_state('/private', 'un6')
        publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
