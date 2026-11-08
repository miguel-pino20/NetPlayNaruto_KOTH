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
import wire

from build_don import sha256_file
from discord_auth import AccountError, ssl_context
from don_core import HEADER, INPUTS, OUT, RING, ENTRY
from game_adapters import get_game, validate_metadata
from don_diagnostics import SessionLog
from don_profiles import select_profile, validate_state
from multiplayer_client import make_node
from node import now_ms
from pine import Pine, PineError, same_serial

MAX_PACKAGE = 128*1024*1024


def stalled_details(node, core, frame):
    """Separate a missing network input from a lost write in the PS2 ring.

    Read only: never invent neutral inputs or advance past a missing player.
    The numeric slot mask alone cannot identify the cause of a deadlock.
    """
    now = now_ms()
    peers = []
    for peer in node.peers.values():
        age = round(((now-peer.last_rx) & 0xffffffff)/1000, 1) if peer.last_rx else None
        peers.append({'puesto': peer.slot+1 if peer.slot is not None else peer.member,
                      'sin_paquetes_s': age, 'capturas_remotas': peer.frame,
                      'ack': peer.ack, 'hello': peer.hello, 'confirmado': peer.confirmed})
    detail = {'puesto_local': node.slot+1, 'fotograma': frame, 'captura_siguiente': node.cap_next,
              'entradas_contiguas': node.need, 'publicadas': node.published, 'pares': peers}
    keys = ('magic', 'version', 'active', 'abort', 'hold', 'status', 'frame', 'captures', 'missing', 'players')
    addresses = [core.base+HEADER[key] for key in keys]
    addresses += [core.base+INPUTS+s*RING*ENTRY+(frame % RING)*ENTRY+24 for s in range(4)]
    addresses += [core.base+OUT+(node.cap_next % RING)*ENTRY+24]
    try:
        values = core.pine.batch([('r', address, 4) for address in addresses])
        detail['barrera'] = dict(zip(keys, values[:len(keys)]))
        detail['tags_entradas'] = values[len(keys):len(keys)+4]
        detail['tag_captura_siguiente'] = values[-1]
        detail['tag_esperado'] = frame+1
    except (PineError, OSError) as error:
        detail['lectura_barrera'] = str(error)
    return json.dumps(detail, ensure_ascii=False, separators=(',', ':'))


def check_profile_identity(manifest, metadata):
    game = validate_metadata(metadata)
    if manifest['game'] != game.game or manifest['adapter'] != game.adapter or metadata['boot_crc'] != manifest['crc']:
        raise ValueError('El paquete no corresponde al adaptador del juego seleccionado.')
    if manifest['pads'] != game.pads(len(manifest['pads'])):
        raise ValueError('El mapa de mandos no coincide con este juego.')
    return game


def cache_state_name(manifest):
    game = get_game(manifest['game'])
    if game.slug == 'digimon':
        return f"DIGIMON-inicial-{manifest['state_sha256'][:16]}.p2s"
    prefix = 'DON' if game.slug == 'don' else 'DIGIMON'
    return f"{prefix}-inicial-{len(manifest['pads'])}p-{manifest['state_sha256'][:16]}.p2s"


def manifest_for(profiles, players):
    selected = select_profile(profiles, players)
    manifest = json.loads(Path(selected['manifest']).read_text())
    if manifest['adapter'] != get_game(manifest['game']).adapter:
        raise ValueError('Selecciona un perfil inicial de un juego compatible con este launcher.')
    return selected, manifest


def shared_profile_for(profiles, players):
    """Derive room descriptors from one unchanged Digimon four-seat state."""
    selected, manifest = manifest_for(profiles, 4)
    if manifest['game'] != 'digimon-rumble-arena-2':
        raise ValueError('El estado común debe pertenecer a Digimon.')
    manifest = {**manifest, 'pads': get_game('digimon').pads(players)}
    return selected, manifest


def make_package(selected, destination, manifest=None):
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_STORED) as archive:
        for key, name in [('state', 'state.p2s'), ('symbols', 'symbols.json'), ('manifest', 'manifest.json')]:
            if key == 'manifest' and manifest is not None:
                archive.writestr(name, json.dumps(manifest, indent=2)+'\n')
            else:
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
        game = check_profile_identity(manifest, metadata)
        destination.mkdir(parents=True, exist_ok=False)
        state = destination/'state.p2s'
        with archive.open('state.p2s') as source, state.open('xb') as output:
            shutil.copyfileobj(source, output, 1024*1024)
        if sha256_file(state) != manifest['state_sha256']:
            raise ValueError('El estado descargado no coincide con Django.')
        players = len(manifest['pads'])
        if manifest['pads'] != game.pads(players) or players not in (2, 3, 4):
            raise ValueError('Mapa de mandos incompatible.')
        validate_state(state, metadata, players)
        return state, metadata


def obtain_profile(client, room, state_dir, temporary, emit):
    """Reuse a hash-verified PCSX2 state; only fetch missing artifacts."""
    manifest = room['manifest']
    directory = Path(state_dir)
    cached = directory/cache_state_name(manifest)
    metadata_dir = directory/('DON-netplay' if get_game(manifest['game']).slug == 'don' else 'DIGIMON-netplay')
    symbols_file = metadata_dir/(manifest['symbols_sha256']+'.json')
    symbols = None
    try:
        if symbols_file.stat().st_size <= 65536:
            symbols = symbols_file.read_bytes()
    except OSError:
        pass
    if symbols is not None and hashlib.sha256(symbols).hexdigest() != manifest['symbols_sha256']:
        symbols = None
    cached_state = cached.is_file() and sha256_file(cached) == manifest['state_sha256']
    if cached_state and symbols is None:
        request = urllib.request.Request(client.url.rstrip('/')+client.base_path+room['id']+'/symbols/',
                    headers={'Authorization': 'Bearer '+client.ticket})
        try:
            with urllib.request.urlopen(request, timeout=30, context=ssl_context()) as response:
                symbols = response.read(65537)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise AccountError('No se pudieron obtener los símbolos del estado inicial.', error.code) from None
    if cached_state and symbols is not None:
        if len(symbols) > 65536 or hashlib.sha256(symbols).hexdigest() != manifest['symbols_sha256']:
            raise ValueError('Los símbolos del estado local no coinciden con Django.')
        metadata = json.loads(symbols)
        game = check_profile_identity(manifest, metadata)
        players = len(manifest['pads'])
        if players not in (2, 3, 4) or manifest['pads'] != game.pads(players):
            raise ValueError('Mapa de mandos incompatible.')
        validate_state(cached, metadata, players)
        emit('log', 'Reutilizando el estado inicial guardado en PCSX2; sin descargar el paquete.')
        state = cached
    else:
        emit('log', 'Descargando el estado inicial desde Django…')
        package = Path(temporary)/'initial.zip'
        state_request(client, room['id'], destination=package,
                      expected_sha=room['package_sha256'], expected_size=room['package_size'])
        state, metadata = unpack_package(package, manifest, Path(temporary)/'profile')
        with zipfile.ZipFile(package) as archive:
            symbols = archive.read('symbols.json')
    metadata_dir.mkdir(exist_ok=True)
    # Identical writes are harmless; replace avoids a partial metadata cache.
    with tempfile.NamedTemporaryFile(dir=metadata_dir, delete=False) as output:
        staged = Path(output.name)
        output.write(symbols)
    try:
        staged.replace(symbols_file)
    finally:
        staged.unlink(missing_ok=True)
    return state, metadata


def state_request(client, room_id, *, upload=None, destination=None, expected_sha=None, expected_size=None):
    """Use the fixed authenticated API route; never trust a remote download URL."""
    room_id = str(UUID(str(room_id)))
    return package_request(client, f'{client.base_path}{room_id}/state/', upload=upload,
                           destination=destination, expected_sha=expected_sha, expected_size=expected_size)


def publish_profile(client, players, package):
    if players not in (2, 3, 4) or not client.can_publish:
        raise ValueError('Solo un administrador puede publicar perfiles de 2, 3 o 4 jugadores.')
    return package_request(client, f'{client.api_prefix}profiles/{players}/state/', upload=package)


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


def _remove_loading_copy(target, expected_sha):
    """An open PCSX2 file can be locked on Windows; cleanup is never fatal."""
    try:
        if not target.is_file() or sha256_file(target) != expected_sha:
            return True  # Gone or changed: never delete somebody else's state.
        target.unlink()
        return True
    except OSError:
        return False  # PCSX2, antivirus or a sync service may still hold it.


def _cleanup_loading_copy(core):
    pending = getattr(core, 'loading_copy', None)
    if isinstance(pending, tuple) and len(pending) == 2:
        if _remove_loading_copy(*pending):
            core.loading_copy = None


def load_initial(pine, metadata, manifest, state, state_dir, timeout=25):
    """Load a shared snapshot into stock PCSX2; the snapshot carries the hook.

    Validate identity before loading, validate installed code before any write.
    Does not require the host's ELF file or a MIPS compiler on guest PCs.
    """
    game = check_profile_identity(manifest, metadata)
    if (pine.version() != manifest['emulator'] or not same_serial(pine.game_id(), metadata['source_serial']) or
            pine.game_crc() not in (metadata['source_crc'], metadata['boot_crc'])):
        raise ValueError('Abre '+game.title+' en la misma versión de PCSX2 que el perfil compartido.')
    if pine.status() != 0:
        raise ValueError('Reanuda PCSX2 antes de conectar la partida.')
    directory = Path(state_dir)
    if not directory.is_dir():
        raise ValueError('Selecciona la carpeta de estados de la instancia de PCSX2 abierta.')
    # Keep a reusable initial state in PCSX2's state directory, just as the
    # Naruto flow does. Numbered slots are only temporary loading handles.
    cached = directory/cache_state_name(manifest)
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
    loaded = None
    try:
        # A previous failed attempt can have left this exact hook frozen at
        # frame 0. Release it so only a newly loaded snapshot can pass frozen().
        try:
            previous = game.core(pine, metadata)
        except ValueError:
            previous = None  # Ordinary PCSX2 has no hook until the state loads.
        if previous is not None and previous.get('active'):
            previous.stop()
        pine.load_state(slot)
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            try:
                core = game.core(pine, metadata)
                count = len(manifest['pads'])
                common = game.slug == 'digimon' and core.frozen(4)
                if (common or core.frozen(count)) and pine.status() == 0:
                    if game.slug == 'digimon':
                        core.configure_players(count)
                    loaded = core
                    core.loading_copy = (target, manifest['state_sha256'])
                    return core
            except ValueError:
                pass
            time.sleep(0.05)
        raise ValueError('PCSX2 no cargó el estado. Comprueba su carpeta de estados y la ranura PINE.')
    except BaseException:
        try:
            game.core(pine, metadata).stop()
        except Exception:
            pass
        raise
    finally:
        removed = _remove_loading_copy(target, manifest['state_sha256'])
        if removed and loaded is not None:
            loaded.loading_copy = None


class OnlineSession:
    """One PINE owner, asynchronous API presence, and an explicit experimental node."""
    def __init__(self, client, config, events, diagnostics=None):
        self.client, self.config, self.events = client, dict(config), events
        self.diagnostics = diagnostics
        self.game = get_game(config.get("game", "don"))
        self.cancel = threading.Event()
        self.commands = queue.Queue()
        self.room_id, self.snapshot = None, None
        self.last_success = time.monotonic()
        self.api_error = None

    def emit(self, kind, value):
        if self.diagnostics is not None:
            self.diagnostics.write(kind, value)
        self.events.put((kind, value))

    def stop(self):
        if self.diagnostics is not None:
            self.diagnostics.write('stop_requested', {})
        self.cancel.set()

    def start_match(self):
        if self.diagnostics is not None:
            self.diagnostics.write('start_requested', {})
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
                        if self.diagnostics is not None:
                            self.diagnostics.exception('start_match_api')
                        self.emit('log', str(error))
                self.sync(manifest, True)
            except Exception as error:
                if self.diagnostics is not None:
                    self.diagnostics.exception('heartbeat')
                self.emit('log', f'API: {error}')
                if isinstance(error, AccountError) and error.code in (400, 401, 403, 404, 409):
                    self.api_error = str(error)
                    self.cancel.set()
                    break
            self.cancel.wait(2)

    def run(self):
        pine, core, node, heartbeat = None, None, None, None
        manifest = None
        failed = False
        owner = self.config['role'] == 'host'
        try:
            if self.cancel.is_set():
                return
            if self.diagnostics is None:
                self.diagnostics = SessionLog(self.config['cache_dir'], self.config)
                self.diagnostics.protect(self.client.ticket)
                self.emit('log', f'Archivo de diagnóstico: {self.diagnostics.path}')
            with tempfile.TemporaryDirectory(prefix='don-online-', dir=self.config['cache_dir']) as folder:
                folder = Path(folder)
                pine = Pine(self.config['pine_slot'], timeout=3).connect()
                self.diagnostics.write('pine_connected', {'endpoint': pine.endpoint, 'timeout_s': pine.timeout})
                if not same_serial(pine.game_id(), self.game.serial) or pine.status() != 0:
                    raise ValueError('Abre '+self.game.title+' en PCSX2 y reanúdalo antes de conectar.')
                if owner:
                    room = self.client.create(None, self.config['players'], self.config.get('delay', 3))
                else:
                    resolved = self.client.resolve_room(self.config['room_id'])
                    room = self.client.request(resolved['id'], 'join')
                self.room_id, manifest = room['id'], room['manifest']
                self.emit('room', room)
                if manifest['game'] != self.game.game:
                    raise ValueError('La sala corresponde a otro juego.')
                if room.get('network_protocol') != 'don-bridge-v1':
                    raise ValueError('Actualiza Django y todos los launchers para crear una sala con puentes.')
                state, metadata = obtain_profile(self.client, room, self.config['state_dir'], folder, self.emit)
                if self.cancel.is_set():
                    return
                self.sync(manifest, False)
                self.emit('log', 'Cargando el estado compartido en PCSX2…')
                core = load_initial(pine, metadata, manifest, state, self.config['state_dir'])
                self.sync(manifest, True)
                heartbeat = threading.Thread(target=self.heartbeat, args=(manifest,), daemon=True)
                heartbeat.start()
                expected_epoch = self.snapshot['session_epoch']
                released, last_progress, previous_frame, next_log = False, time.monotonic(), 0, 0
                stall_reported = False
                next_cleanup = time.monotonic()+1
                while not self.cancel.is_set():
                    if time.monotonic() >= next_cleanup:
                        _cleanup_loading_copy(core)
                        next_cleanup = time.monotonic()+2
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
                            locked_roster = [(p['player_id'], p['slot'], p['address'], p['port']) for p in room['players']]
                            node = make_node(room, core, experimental_don=True)
                            last_progress = time.monotonic()
                            self.emit('log', 'Conectando los mandos por ZeroTier…')
                        if locked_roster != [(p['player_id'], p['slot'], p['address'], p['port']) for p in room['players']]:
                            raise ValueError('Cambió la dirección de un mando; crea una sala nueva.')
                        if node.bridge is not None:
                            node.bridge.tick()
                        node.pump()
                        if node.started and not released and min(node.published.values()) >= 1:
                            core.release()
                            released = True
                            self.emit('playing', 'Online experimental · hashes de entradas; sincronía de combate no certificada.')
                        if node.closed_reason is not None:
                            member = getattr(node, 'closed_member', None)
                            who = f'P{member}' if member is not None else 'otro jugador'
                            reason = {wire.BYE_DONE: 'salida', wire.BYE_ABORTED: 'cancelación',
                                      wire.BYE_DESYNC: 'entradas diferentes', wire.BYE_ERROR: 'error local'}.get(
                                          node.closed_reason, str(node.closed_reason))
                            raise ValueError(f'{who} envió el cierre de mandos ({reason}). Revisa su consola para ver la causa original.')
                        if node.desync is not None:
                            raise ValueError(f'Las entradas dejaron de coincidir en el fotograma {node.desync}.')
                        if core.get('abort'):
                            raise ValueError('El juego abortó el puente de mandos; comprueba el mando físico 1A.')
                        frame = core.get('frame')
                        if frame != previous_frame:
                            previous_frame, last_progress = frame, time.monotonic()
                            stall_reported = False
                        if released and not stall_reported and time.monotonic()-last_progress > 5:
                            self.emit('log', 'Esperando entradas durante 5 s · '+stalled_details(node, core, frame))
                            stall_reported = True
                        if time.monotonic()-last_progress > 30:
                            if not node.started or any(not p.hello or not p.confirmed for p in node.peers.values()):
                                missing = [f'P{p.slot+1} ({p.addr[0]}:{p.addr[1]})'
                                           for p in node.peers.values() if not p.hello or not p.confirmed]
                                raise ValueError('No se completó la conexión UDP de mandos: '+
                                    (', '.join(missing) or 'esperando confirmación de inicio')+
                                    '. Comprueba ZeroTier y el acceso UDP en los equipos indicados.')
                            raise ValueError(f'Sin avance durante 30 s: PCSX2 estado {pine.status()}, '
                                f"hold={core.get('hold')}, mandos pendientes={core.get('missing'):04b}, "
                                f'fotograma={frame}.')
                        if time.monotonic() >= next_log:
                            self.diagnostics.write('transport', {'captura_siguiente': node.cap_next,
                                'entradas_contiguas': node.need, 'publicadas': node.published,
                                'pares': [{'puesto': p.slot+1 if p.slot is not None else p.member,
                                    'capturas_remotas': p.frame, 'ack': p.ack,
                                    'sin_paquetes_s': round(((now_ms()-p.last_rx) & 0xffffffff)/1000, 3) if p.last_rx else None}
                                    for p in node.peers.values()]})
                            self.emit('progress', {'frame': frame, 'checked': node.checked, 'rtt': node.rtt_ms(),
                                'routes': node.bridge.route_stats() if node.bridge else {}, 'connected': node.started})
                            next_log = time.monotonic()+2
                    self.cancel.wait(0.002 if node else 0.05)
                if self.api_error:
                    raise ValueError(self.api_error)
        except PineError as error:
            failed = True
            if self.diagnostics is not None:
                self.diagnostics.exception('PINE')
            slot = (self.snapshot or {}).get('slot')
            who = f'P{slot+1}' if slot is not None else 'este equipo'
            self.emit('error', f'PINE local de {who}: {error}')
        except Exception as error:
            failed = True
            if self.diagnostics is not None:
                self.diagnostics.exception('session')
            self.emit('error', str(error))
        finally:
            self.cancel.set()
            if core is not None:
                try:
                    core.stop()
                    if self.diagnostics is not None:
                        self.diagnostics.write('controls_restored', {'confirmed': True})
                except Exception as error:
                    if self.diagnostics is not None:
                        self.diagnostics.exception('restore_controls')
                    self.emit('log', 'No se pudo confirmar la restauración de controles por PINE. '
                              'Si PCSX2 sigue congelado, detén la emulación y vuelve a abrir D.O.N. '+str(error))
            if node is not None:
                try:
                    node.close(wire.BYE_ERROR if failed else wire.BYE_DONE)
                except Exception as error:
                    self.emit('log', f'Error al cerrar el transporte: {error}')
                    node.sock.close()
            if pine is not None:
                pine.close()
            if heartbeat is not None:
                heartbeat.join(timeout=10)
            if core is not None:
                _cleanup_loading_copy(core)
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
            self.emit('done', 'Sesión terminada.')
            if self.diagnostics is not None:
                self.diagnostics.close()
