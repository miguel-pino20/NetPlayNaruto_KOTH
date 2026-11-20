"""GitHub downloads share PC verification; installation belongs to Android."""
from pathlib import Path
import os
import tempfile
import threading


if __package__:
    from .mobile_locale import tr
else:
    from mobile_locale import tr


def download_update(directory, release):
    from updater import download_release, asset_url_allowed, UpdateError
    from release_info import REPOSITORY, ASSET_NAMES
    if (release.asset_name != ASSET_NAMES['android'] or
            not asset_url_allowed(release.asset_url, REPOSITORY) or
            not asset_url_allowed(release.checksum_url, REPOSITORY)):
        raise UpdateError(tr('La actualización no corresponde al APK del repositorio configurado.'))
    folder = Path(directory) / 'updates'
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as temporary:
        payload, _ = download_release(release, Path(temporary), 'android', lambda *_: None, threading.Event())
        target = folder / 'latest.apk'
        os.replace(payload, target)
    return target


def install_update(directory):
    from jnius import autoclass
    if not (Path(directory) / 'updates/latest.apk').is_file():
        raise ValueError(tr('Descarga primero la actualización.'))
    activity = autoclass('org.kivy.android.PythonActivity').mActivity
    Intent, Uri = autoclass('android.content.Intent'), autoclass('android.net.Uri')
    if not activity.getPackageManager().canRequestPackageInstalls():
        Settings = autoclass('android.provider.Settings')
        activity.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                      Uri.parse('package:' + activity.getPackageName())))
        return tr('Permite instalar desde Naruto Netplay, vuelve y pulsa Instalar actualización.')
    uri = Uri.parse('content://org.un5.narutonetplay.updates/update.apk')
    intent = Intent(Intent.ACTION_VIEW)
    intent.setDataAndType(uri, 'application/vnd.android.package-archive')
    intent.setClipData(autoclass('android.content.ClipData').newRawUri(tr('Actualización'), uri))
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    activity.startActivity(intent)
    return tr('Confirma la actualización en el instalador de Android.')
