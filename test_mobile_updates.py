import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import release_info
import updater
from mobile.updates import download_update


def apk_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('AndroidManifest.xml', b'test manifest')
        archive.writestr('classes.dex', b'test dex')
    return buffer.getvalue()


class AndroidUpdateTests(unittest.TestCase):
    def release(self, payload):
        name = release_info.ASSET_NAMES['android']
        url = f'https://github.com/{release_info.REPOSITORY}/releases/download/v0.1.9A/{name}'
        return updater.Release('v0.1.9A', url, url + '.sha256', len(payload), name)

    def test_select_android_asset_from_shared_release(self):
        release = self.release(apk_bytes())
        entries = [{'tag_name': release.version, 'assets': [
            {'name': release.asset_name, 'browser_download_url': release.asset_url, 'size': release.size},
            {'name': release.asset_name + '.sha256', 'browser_download_url': release.checksum_url}]}]
        result = updater.select_release(entries, '0.1.8A', 'android', release_info.REPOSITORY)
        self.assertEqual(result.asset_name, release.asset_name)
        self.assertIsNone(updater.select_release(entries, '0.1.9A', 'android', release_info.REPOSITORY))

    def test_download_verifies_and_publishes_apk(self):
        data = apk_bytes()
        release = self.release(data)
        checksum = (hashlib.sha256(data).hexdigest() + '  ' + release.asset_name + '\n').encode()
        with tempfile.TemporaryDirectory() as root, patch('updater._response', side_effect=[io.BytesIO(checksum), io.BytesIO(data)]):
            result = download_update(root, release)
            self.assertEqual(result, Path(root) / 'updates/latest.apk')
            self.assertEqual(result.read_bytes(), data)

    def test_failed_hash_preserves_previous_download(self):
        data = apk_bytes()
        release = self.release(data)
        checksum = ('0' * 64 + '  ' + release.asset_name + '\n').encode()
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'updates/latest.apk'
            target.parent.mkdir(); target.write_bytes(b'previous')
            with patch('updater._response', side_effect=[io.BytesIO(checksum), io.BytesIO(data)]):
                with self.assertRaises(updater.UpdateError):
                    download_update(root, release)
            self.assertEqual(target.read_bytes(), b'previous')
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_non_apk_is_rejected_even_when_hash_matches(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'fake.apk'; target.write_bytes(b'not an APK')
            with self.assertRaisesRegex(updater.UpdateError, 'APK'):
                updater.verify_payload(target, hashlib.sha256(target.read_bytes()).hexdigest(), 'android')
