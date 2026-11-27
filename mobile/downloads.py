"""Explicit export to shared Downloads. Does not alter the emulator."""
import hashlib
import os

if __package__:
    from .mobile_locale import tr
else:
    from mobile_locale import tr


RELATIVE_PATH = 'Download/NarutoNetplay/'

def stream_tag(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    return digest.hexdigest()[:16]


def publish_state(source, filename):
    """Return (shared directory, changed); no emulator permissions are required."""
    from jnius import autoclass
    Build = autoclass('android.os.Build$VERSION')
    if Build.SDK_INT < 29:
        raise RuntimeError(tr('Guardar en Descargas requiere Android 10 o posterior.'))
    Downloads = autoclass('android.provider.MediaStore$Downloads')
    Values = autoclass('android.content.ContentValues')
    String = autoclass('java.lang.String')
    ContentUris = autoclass('android.content.ContentUris')
    Environment = autoclass('android.os.Environment')
    Activity = autoclass('org.kivy.android.PythonActivity')
    Service = autoclass('org.kivy.android.PythonService')
    context = Service.mService or Activity.mActivity
    resolver = context.getContentResolver()
    collection = Downloads.EXTERNAL_CONTENT_URI
    cursor = resolver.query(collection, ['_id'], '_display_name=? AND relative_path=?',
                            [filename, RELATIVE_PATH], None)
    uri = None
    try:
        if cursor is not None and cursor.moveToFirst():
            uri = ContentUris.withAppendedId(collection, cursor.getLong(0))
    finally:
        if cursor is not None:
            cursor.close()
    with open(source, 'rb') as incoming:
        expected = stream_tag(incoming)

    def tag_uri(target):
        descriptor = resolver.openFileDescriptor(target, 'r')
        if descriptor is None:
            raise OSError(tr('No se pudo leer el estado compartido.'))
        try:
            fd = descriptor.detachFd()
            with os.fdopen(fd, 'rb') as exported:
                return stream_tag(exported)
        finally:
            descriptor.close()

    shared = str(Environment.getExternalStorageDirectory().getAbsolutePath()) + '/' + RELATIVE_PATH.rstrip('/')
    if uri is not None and tag_uri(uri) == expected:
        return shared, False
    created = uri is None
    if created:
        values = Values()
        values.put('_display_name', String(filename))
        values.put('mime_type', String('application/octet-stream'))
        values.put('relative_path', String(RELATIVE_PATH))
        values.put('is_pending', autoclass('java.lang.Integer')(1))
        uri = resolver.insert(collection, values)
        if uri is None:
            raise OSError(tr('Android no permitió guardar el estado en Descargas.'))
    try:
        descriptor = resolver.openFileDescriptor(uri, 'rwt')
        if descriptor is None:
            raise OSError(tr('No se pudo abrir el destino del estado.'))
        try:
            with os.fdopen(descriptor.detachFd(), 'wb') as target, open(source, 'rb') as incoming:
                for chunk in iter(lambda: incoming.read(1024 * 1024), b''):
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
        finally:
            descriptor.close()
        if tag_uri(uri) != expected:
            raise OSError(tr('El estado guardado en Descargas no pasó la verificación.'))
        values = Values()
        values.put('is_pending', autoclass('java.lang.Integer')(0))
        resolver.update(uri, values, None, None)
    except BaseException:
        # Never leave a partial file that the emulator could mistake for a state.
        resolver.delete(uri, None, None)
        raise
    return shared, True


def download_state(directory, game, *, variant=None):
    if __package__:
        from .host import prepare_files
    else:
        from host import prepare_files
    if game == 'un6' and variant:
        from pathlib import Path
        state, _ = prepare_files(Path(directory) / 'export', game, variant=variant)
        name = f'UN6-Netplay-{variant}.p2s'
    else:
        state, _ = prepare_files(directory, game)
        name = game.upper() + '-Netplay.p2s'
    folder, changed = publish_state(state, name)
    message = tr('Estado guardado: {path}') if changed else tr('Estado existente verificado: {path}')
    return tr(message, path=folder + '/' + name) + tr(
        '\nCárgalo o cópialo en ARMSX2 por tu cuenta. Netplay usa el slot 1; '
        'este botón no modifica el emulador.')
