"""Experimental D.O.N sessions: Django stores states; ZeroTier carries pads.

Input hashes detect transport faults, not gameplay divergence. This mode never
sets simulation_hashes or online_verified to True.
"""
import hashlib
import json
import queue
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from uuid import UUID

from build_don import sha256_file
from discord_auth import AccountError, ssl_context
from don_adapter import CRC, ELF_SHA256, SERIAL
from don_core import DonCore
from don_profiles import select_profile, validate_state
from multiplayer_client import make_node
from pine import Pine, same_serial

MAX_PACKAGE = 128*1024*1024


def manifest_for(profiles, players):
    selected = select_profile(profiles, players)
    manifest = json.loads(Path(selected['manifest']).read_text())
    if manifest['game'] != 'don' or manifest['adapter'] != DonCore.adapter_id:
        raise ValueError('Selecciona un perfil inicial de D.O.N compatible con este launcher.')
    return selected, manifest


def make_package(selected, destination):
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_STORED) as archive:
        for key, name in [('state', 'state.p2s'), ('symbols', 'symbols.json'), ('manifest', 'manifest.json')]:
            archive.write(selected[key], name)
    return Path(destination)


def unpack_package(package, manifest, destination):
    """Bound sizes and validate API-pinned hashes before using any game state."""
    destination = Path(destination)
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != 3 or set(names) != {'state.p2s', 'symbols.json', 'manifest.json'}:
            raise ValueError('El paquete del servidor no tiene el formato esperado.')
        for item in archive.infolist():
            if item.file_size > (MAX_PACKAGE if item.filename == 'state.p2s' else 65536) or item.flag_bits & 1:
                raise ValueError('El paquete contiene un archivo demasiado grande o cifrado.')
        if json.loads(archive.read('manifest.json')) != manifest:
            raise ValueError('El paquete pertenece a otra sala o cambió su manifest.')
        symbols = archive.read('symbols.json')
        if hashlib.sha256(symbols).hexdigest() != manifest['symbols_sha256']:
            raise ValueError('Los símbolos descargados no coinciden con Django.')
        metadata = json.loads(symbols)
        if (manifest['game'] != 'don' or manifest['adapter'] != DonCore.adapter_id or
                metadata['adapter'] != manifest['adapter'] or metadata['source_crc'] != CRC or
                metadata['source_elf_sha256'] != ELF_SHA256 or metadata['boot_crc'] != manifest['crc']):
            raise ValueError('Este paquete no corresponde al adaptador de D.O.N admitido.')
        destination.mkdir(parents=True, exist_ok=False)
        state = destination/'state.p2s'
        with archive.open('state.p2s') as source, state.open('xb') as output:
            shutil.copyfileobj(source, output, 1024*1024)
        if sha256_file(state) != manifest['state_sha256']:
            raise ValueError('El estado descargado no coincide con Django.')
        players = len(manifest['pads'])
        if manifest['pads'] != [{'port': 1, 'slot': s+1} for s in range(players)] or players not in (2, 3, 4):
            raise ValueError('Mapa de mandos incompatible.')
        validate_state(state, metadata, players)
        return state, metadata


def state_request(client, room_id, *, upload=None, destination=None, expected_sha=None, expected_size=None):
    """Use the fixed authenticated API route; never trust a remote download URL."""
    room_id = str(UUID(str(room_id)))
    return package_request(client, f'{client.base_path}{room_id}/state/', upload=upload,
                           destination=destination, expected_sha=expected_sha, expected_size=expected_size)


def publish_profile(client, players, package):
    if players not in (2, 3, 4) or not client.can_publish:
        raise ValueError('Solo un administrador puede publicar perfiles de 2, 3 o 4 jugadores.')
    return package_request(client, f'/api/netplay/don/profiles/{players}/state/', upload=package)


def package_request(client, path, *, upload=None, destination=None, expected_sha=None, expected_size=None):
    url = client.url.rstrip('/')+path
    data = Path(upload).read_bytes() if upload else None
    if data is not None and len(data) > MAX_PACKAGE:
        raise ValueError('El paquete supera 128 MiB.')
    headers = {'Authorization': 'Bearer '+client.ticket, 'User-Agent': 'UN5-Netplay-DON'}
    if data is not None:
        headers.update({'Content-Type': 'application/octet-stream',
                        'Content-Disposition': 'attachment; filename="DON-inicial.zip"'})
    request = urllib.request.Request(url, data=data, headers=headers, method='POST' if data is not None else 'GET')
    try:
        with urllib.request.urlopen(request, timeout=60, context=ssl_context()) as response:
            if upload:
                return json.loads(response.read(1024*1024))
            if not expected_sha or not isinstance(expected_size, int) or not 0 < expected_size <= MAX_PACKAGE:
                raise ValueError('Django no publicó un paquete válido para esta sala.')
            digest, size = hashlib.sha256(), 0
            with Path(destination).open('xb') as output:
                while block := response.read(1024*1024):
                    size += len(block)
                    if size > expected_size:
                        raise ValueError('La descarga excede el tamaño anunciado por Django.')
                    digest.update(block)
                    output.write(block)
            if size != expected_size or digest.hexdigest() != expected_sha:
                raise ValueError('La descarga del estado inicial está incompleta o cambió su hash.')
            return destination
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read(65536))
        except (ValueError, OSError):
            detail = 'Comprueba que Django tenga instalada la API de estados de salas.'
        raise AccountError(str(detail), error.code) from None


def load_initial(pine, metadata, manifest, state, state_dir, timeout=25):
    """Load a shared snapshot into stock PCSX2; the snapshot carries the hook.

    Validate identity before loading, validate installed code before any write.
    Does not require the host's ELF file or a MIPS compiler on guest PCs.
    """
    if (pine.version() != manifest['emulator'] or not same_serial(pine.game_id(), metadata['source_serial']) or
            pine.game_crc() not in (metadata['source_crc'], metadata['boot_crc'])):
        raise ValueError('Abre la ISO de D.O.N en la misma versión de PCSX2 que el host.')
    if pine.status() != 0:
        raise ValueError('Reanuda PCSX2 antes de conectar la partida.')
    directory = Path(state_dir)
    if not directory.is_dir():
        raise ValueError('Selecciona la carpeta de estados de la instancia de PCSX2 abierta.')
    # Keep a reusable initial state in PCSX2's state directory, just as the
    # Naruto flow does. Numbered slots are only temporary loading handles.
    cached = directory/f"DON-inicial-{len(manifest['pads'])}p-{manifest['state_sha256'][:16]}.p2s"
    if not cached.exists():
        with Path(state).open('rb') as source, cached.open('xb') as output:
            shutil.copyfileobj(source, output)
    if sha256_file(cached) != manifest['state_sha256']:
        raise ValueError('El estado inicial guardado localmente cambió; no se sobrescribe.')
    slot = next((s for s in range(9, -1, -1) if not any(directory.glob(f'*.{s:02}.p2s'))), None)
    if slot is None:
        raise ValueError('PCSX2 no tiene una ranura libre para cargar sin sobrescribir tus estados.')
    target = directory/f"{metadata['source_serial']} ({pine.game_crc()}).{slot:02}.p2s"
    with cached.open('rb') as source, target.open('xb') as output:
        shutil.copyfileobj(source, output)
    try:
        pine.load_state(slot)
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            try:
                core = DonCore(pine, metadata)
                if core.frozen(len(manifest['pads'])) and pine.status() == 0:
                    return core
            except ValueError:
                pass
            time.sleep(0.05)
        raise ValueError('PCSX2 no cargó el estado. Comprueba su carpeta de estados y la ranura PINE.')
    except BaseException:
        try:
            DonCore(pine, metadata).stop()
        except Exception:
            pass
        raise
    finally:
        if target.is_file() and sha256_file(target) == manifest['state_sha256']:
            target.unlink()


class OnlineSession:
    """One PINE owner, asynchronous API presence, and an explicit experimental node."""
    def __init__(self, client, config, events):
        self.client, self.config, self.events = client, dict(config), events
        self.cancel = threading.Event()
        self.commands = queue.Queue()
        self.room_id, self.snapshot = None, None
        self.last_success = time.monotonic()
        self.api_error = None

    def emit(self, kind, value):
        self.events.put((kind, value))

    def stop(self):
        self.cancel.set()

    def start_match(self):
        self.commands.put('start')

    def sync(self, manifest, ready):
        result = self.client.request(self.room_id, 'sync', {'manifest': manifest,
                    'address': self.config['address'], 'port': self.config.get('port', 47400), 'ready': ready})
        self.snapshot = result
        self.last_success = time.monotonic()
        self.emit('room', result)
        return result

    def heartbeat(self, manifest):
        while not self.cancel.is_set():
            try:
                try:
                    command = self.commands.get_nowait()
                except queue.Empty:
                    command = None
                if command == 'start':
                    try:
                        self.client.request(self.room_id, 'start')
                    except AccountError as error:
                        self.emit('log', str(error))
                self.sync(manifest, True)
            except Exception as error:
                self.emit('log', f'API: {error}')
                if isinstance(error, AccountError) and error.code in (400, 401, 403, 404, 409):
                    self.api_error = str(error)
                    self.cancel.set()
                    break
            self.cancel.wait(2)

    def run(self):
        pine, core, node, heartbeat = None, None, None, None
        manifest = None
        owner = self.config['role'] == 'host'
        try:
            if self.cancel.is_set():
                return
            with tempfile.TemporaryDirectory(prefix='don-online-', dir=self.config['cache_dir']) as folder:
                folder = Path(folder)
                package = folder/'initial.zip'
                pine = Pine(self.config['pine_slot'], timeout=3).connect()
                if not same_serial(pine.game_id(), SERIAL) or pine.status() != 0:
                    raise ValueError('Abre D.O.N en PCSX2 y reanúdalo antes de conectar.')
                if owner:
                    room = self.client.create(None, self.config['players'], self.config.get('delay', 3))
                else:
                    room = self.client.request(self.config['room_id'], 'join')
                self.room_id, manifest = room['id'], room['manifest']
                self.emit('room', room)
                self.emit('log', 'Descargando el estado inicial desde Django…')
                state_request(self.client, self.room_id, destination=package,
                              expected_sha=room['package_sha256'], expected_size=room['package_size'])
                if self.cancel.is_set():
                    return
                state, metadata = unpack_package(package, manifest, folder/'profile')
                self.sync(manifest, False)
                self.emit('log', 'Cargando el estado compartido en PCSX2…')
                core = load_initial(pine, metadata, manifest, state, self.config['state_dir'])
                self.sync(manifest, True)
                heartbeat = threading.Thread(target=self.heartbeat, args=(manifest,), daemon=True)
                heartbeat.start()
                expected_epoch = self.snapshot['session_epoch']
                released, last_progress, previous_frame, next_log = False, time.monotonic(), 0, 0
                while not self.cancel.is_set():
                    room = self.snapshot
                    if time.monotonic()-self.last_success > 15:
                        raise ValueError('Se perdió la API durante 15 segundos; partida detenida.')
                    if (room['session_epoch'] != expected_epoch or room['manifest'] != manifest or
                            room['status'] == 'closed'):
                        raise ValueError('La sala se cerró o cambió su identidad.')
                    if room['status'] == 'running':
                        if not room['ready']:
                            raise ValueError('Un participante dejó de estar conectado o listo.')
                        if node is None:
                            node = make_node(room, core, experimental_don=True)
                            last_progress = time.monotonic()
                            self.emit('log', 'Conectando los mandos por ZeroTier…')
                        node.pump()
                        if node.started and not released and min(node.published.values()) >= 1:
                            core.release()
                            released = True
                            self.emit('playing', 'Online experimental · hashes de entradas; sincronía de combate no certificada.')
                        if node.closed_reason is not None:
                            raise ValueError('Otro jugador cerró la conexión de mandos.')
                        if node.desync is not None:
                            raise ValueError(f'Las entradas dejaron de coincidir en el fotograma {node.desync}.')
                        if core.get('abort'):
                            raise ValueError('El juego abortó el puente de mandos; comprueba el mando físico 1A.')
                        frame = core.get('frame')
                        if frame != previous_frame:
                            previous_frame, last_progress = frame, time.monotonic()
                        if time.monotonic()-last_progress > 30:
                            raise ValueError('No hubo avance de mandos durante 30 segundos; partida detenida.')
                        if time.monotonic() >= next_log:
                            self.emit('progress', {'frame': frame, 'checked': node.checked, 'rtt': node.rtt_ms()})
                            next_log = time.monotonic()+2
                    self.cancel.wait(0.002 if node else 0.05)
                if self.api_error:
                    raise ValueError(self.api_error)
        except Exception as error:
            self.emit('error', str(error))
        finally:
            self.cancel.set()
            if core is not None:
                try:
                    core.stop()
                except Exception:
                    pass
            if node is not None:
                node.close()
            if pine is not None:
                pine.close()
            if heartbeat is not None:
                heartbeat.join(timeout=10)
            if self.room_id:
                try:
                    if owner:
                        self.client.request(self.room_id, 'close')
                    elif manifest:
                        self.sync(manifest, False)
                        if self.snapshot['status'] == 'lobby':
                            self.client.request(self.room_id, 'leave')
                except Exception:
                    pass
            self.emit('done', 'Sesión terminada; controles locales restaurados.')
