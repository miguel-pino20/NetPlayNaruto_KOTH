"""Read-only replay stream, isolated from the players' UDP lockstep.

The host only enqueues immutable records. TCP accept/send, slow readers and
history retention run in background threads and never enter Node.peers.
"""
from __future__ import annotations

import hmac
import json
import queue
import socket
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor

FRAME = struct.Struct('<I24sI24sI14I')
MAX_HISTORY = 64 * 1024 * 1024
MAX_VIEWERS = 16
SELECTION_EVENT = 0x80000000


def read_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size-len(data))
        if not chunk:
            raise EOFError('La transmisión del combate terminó.')
        data.extend(chunk)
    return bytes(data)


def read_json(sock):
    size = struct.unpack('<I', read_exact(sock, 4))[0]
    if size > 2048:
        raise ValueError('Cabecera de espectador demasiado grande.')
    return json.loads(read_exact(sock, size))


def send_json(sock, data):
    payload = json.dumps(data).encode()
    sock.sendall(struct.pack('<I', len(payload)) + payload)


class ReplayServer:
    def __init__(self, port, key, tag, symbols, delay, bind='0.0.0.0'):
        self.key, self.tag, self.symbols, self.delay = key, tag, symbols, delay
        self.pending = queue.Queue(maxsize=4096)
        self.history = []
        self.cursor = 0
        self.last_selection, self.last_event = None, 0.0
        self.done = threading.Event()
        self.changed = threading.Condition()
        self.viewers = threading.BoundedSemaphore(MAX_VIEWERS)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind((bind, port))
            self.sock.listen(MAX_VIEWERS)
            self.sock.settimeout(0.2)
        except BaseException:
            self.sock.close()
            raise
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._archive, daemon=True).start()
        threading.Thread(target=self._accept, daemon=True).start()

    def capture(self, node):
        """Bounded, no socket operations or waiting on spectators in the game loop."""
        if self.done.is_set():
            return
        end = min(node.need[0], node.need[1], node.cap_next)
        # Limit work even after a long pause; Node normally advances 1 frame.
        if end-self.cursor > 128:
            self.done.set()
            return
        selection = tuple(node.sel_words or [0]*14)
        now = time.monotonic()
        if selection != self.last_selection or now-self.last_event >= 1:
            # Selection/heartbeat events also travel while the game's logical
            # frame counter is paused in menus and scene transitions.
            record = FRAME.pack(SELECTION_EVENT | self.cursor, bytes(24), 0, bytes(24), 0, *selection)
            if not self._enqueue(record):
                return
            self.last_selection, self.last_event = selection, now
        for frame in range(self.cursor, end):
            a, b = node.known[0].get(frame), node.known[1].get(frame)
            if a is None or b is None:
                self.done.set()
                return
            record = FRAME.pack(frame, a[0], a[1], b[0], b[1], *selection)
            if not self._enqueue(record):
                return
            self.cursor = frame+1

    def _enqueue(self, record):
        try:
            self.pending.put_nowait(record)
            return True
        except queue.Full:
            self.done.set()  # Disable viewing rather than slow down the fight.
            return False

    def _archive(self):
        while not self.done.is_set():
            try:
                record = self.pending.get(timeout=0.2)
            except queue.Empty:
                continue
            with self.changed:
                if len(self.history)*FRAME.size >= MAX_HISTORY:
                    self.done.set()
                else:
                    self.history.append(record)
                self.changed.notify_all()

    def _accept(self):
        while not self.done.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            if not self.viewers.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            conn.settimeout(2)
            hello = read_json(conn)
            if (not isinstance(hello, dict) or not isinstance(hello.get('key'), str)
                    or not hmac.compare_digest(hello['key'], self.key)
                    or hello.get('tag') != self.tag or hello.get('symbols') != self.symbols):
                return
            send_json(conn, {'version': 1, 'tag': self.tag, 'symbols': self.symbols, 'delay': self.delay})
            index = 0
            while not self.done.is_set():
                with self.changed:
                    # Condition.wait releases the lock while an idle viewer waits.
                    if index >= len(self.history):
                        self.changed.wait(timeout=0.2)
                        continue
                    records = self.history[index:index+32]
                conn.sendall(b''.join(records))
                index += len(records)
        except (OSError, EOFError, ValueError, TypeError):
            pass
        finally:
            conn.close()
            self.viewers.release()

    def close(self):
        self.done.set()
        self.sock.close()
        with self.changed:
            self.changed.notify_all()


class ReplayClient:
    def __init__(self, address, key, tag, symbols, delay):
        self.records = queue.Queue(maxsize=256)
        self.done = threading.Event()
        self.error = None
        self.sock = socket.create_connection(address, timeout=3)
        try:
            send_json(self.sock, {'key': key, 'tag': tag, 'symbols': symbols})
            hello = read_json(self.sock)
            if hello != {'version': 1, 'tag': tag, 'symbols': symbols, 'delay': delay}:
                raise ValueError('La transmisión usa otro juego, estado o delay.')
            self.sock.settimeout(1)
        except BaseException:
            self.sock.close()
            raise
        threading.Thread(target=self._receive, daemon=True).start()

    def _receive(self):
        try:
            # Preserve partially received frames across socket timeouts.
            data = bytearray()
            last = time.monotonic()
            while not self.done.is_set():
                try:
                    chunk = self.sock.recv(FRAME.size-len(data))
                except socket.timeout:
                    if time.monotonic()-last > 15:
                        raise EOFError('El host dejó de transmitir.')
                    continue
                if not chunk:
                    raise EOFError('El host cerró la transmisión.')
                last = time.monotonic()
                data.extend(chunk)
                if len(data) == FRAME.size:
                    record = FRAME.unpack(data)
                    data.clear()
                    while not self.done.is_set():
                        try:
                            self.records.put(record, timeout=0.2)
                            break
                        except queue.Full:
                            continue
        except (OSError, EOFError, ValueError) as error:
            if not self.done.is_set():
                self.error = str(error)

    def close(self):
        self.done.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class ReplayPlayer:
    """Feed both pad slots from the stream; local captured inputs are never read."""
    def __init__(self, core, records):
        self.core, self.records = core, records
        self.next = 0
        self.pending = None

    def step(self):
        # Only feed the frame the game is waiting for, to keep selections timed
        # and avoid overwriting PCSX2's 128-entry input rings during catch-up.
        if self.pending is None:
            try:
                self.pending = self.records.get_nowait()
            except queue.Empty:
                return False
        frame, raw0, aux0, raw1, aux1, *selection = self.pending
        current = self.core.get('frame')
        if frame & SELECTION_EVENT:
            if (frame & ~SELECTION_EVENT) > current:
                return False
            if selection[0]:
                self.core.follow_selection(selection)
            self.pending = None
            return True
        if current <= frame:
            return False
        if frame != self.next:
            raise ValueError('La transmisión perdió el orden de los frames.')
        if selection[0]:
            self.core.follow_selection(selection)
        self.core.publish(0, {frame: (raw0, aux0)})
        self.core.publish(1, {frame: (raw1, aux1)})
        self.next += 1
        self.pending = None
        return True


def connect_best_source(sources, key, tag, symbols, delay):
    """Measure authenticated TCP setup concurrently, outside either player's loop.

    Keep the fastest connection; closing unused probes never enters UDP lockstep.
    Sources offer the same round and complete input history, not live video.
    """
    def probe(source):
        start = time.monotonic()
        try:
            client = ReplayClient((source['address'], int(source['port'])), key, tag, symbols, delay)
            return time.monotonic()-start, client, source
        except (OSError, EOFError, ValueError):
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(probe, sources[:2]))
    results = sorted((r for r in results if r is not None), key=lambda r: r[0])
    if not results:
        raise OSError('No se pudo abrir ninguna transmisión de la pareja.')
    for _, client, _ in results[1:]:
        client.close()
    return results[0]


def cmd_watch(args):
    from hill import file_tag
    from netplay import apply_config, connect, load_match_state, stop_requested
    import os

    key = os.environ.get('UN5_SPECTATOR_KEY', '')
    if not key:
        print('Falta la autorización de espectador.', flush=True)
        return 1
    if not load_match_state(args):
        return 1
    pine, core = connect(args)
    client = None
    try:
        if not core.frozen():
            raise ValueError('El save state del espectador no está congelado.')
        tag = file_tag(args.state)
        apply_config(args, core, tag)
        ip, _, port = args.connect.rpartition(':')
        sources = json.loads(os.environ.get('UN5_SPECTATOR_SOURCES', '[]'))
        if not sources:
            sources = [{'address': ip, 'port': int(port), 'name': 'P1'}]
        # The host may still be loading its state when Django announces ready.
        deadline = time.monotonic()+45
        while not stop_requested(args):
            try:
                latency, client, selected = connect_best_source(sources, key, tag, file_tag(args.symbols), args.delay)
                print(f"Espectador: fuente {selected.get('name', selected['address'])} "
                      f"({selected['address']}:{selected['port']}), respuesta TCP {latency*1000:.0f} ms.", flush=True)
                break
            except (OSError, EOFError):
                if time.monotonic() >= deadline:
                    raise OSError('No se pudo abrir la transmisión de ningún jugador.') from None
                time.sleep(0.2)
        if client is None:
            return 0
        print('ESPECTADOR: reproduciendo desde el inicio. Tu mando no participa en el combate.', flush=True)
        player = ReplayPlayer(core, client.records)
        last_progress = time.monotonic()
        # Keep HOLD=1: missing spectator data may freeze this PC indefinitely,
        # but cannot abort the match or send anything to its UDP participants.
        while not stop_requested(args):
            if player.step():
                last_progress = time.monotonic()
            if client.error and client.records.empty() and (player.pending is None or time.monotonic()-last_progress > 2):
                raise EOFError(client.error)
            time.sleep(0.001)
        return 0
    except (OSError, EOFError, ValueError) as error:
        print(f'Espectador: {error}', flush=True)
        return 1
    finally:
        if client:
            client.close()
        try:
            core.put('hold', 0)
            core.stop()
        finally:
            pine.close()
