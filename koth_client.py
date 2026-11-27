"""Event discovery and enrollment with guest or verified Discord identity."""
import json
from pathlib import Path
from uuid import uuid4
from urllib.parse import urljoin, urlsplit, urlunsplit

from appdata import write_json
from discord_auth import AccountError, api_call
from hill import validate_url

DEFAULT_URL = 'https://narutimateonline.servegame.com'
LEGACY_HOST = 'narultimateonline.sytes.net'
LEGACY_HOSTS = (LEGACY_HOST, 'narutimateonline.sytes.net')


KOTH_STATES = {
    'un5': ('un5', 'standard'),
    'un6': ('un6', 'original'),
    'un6-transformed': ('un6', 'transformed'),
    'un6-audio20': ('un6', 'audio20'),
}


def site_url(url):
    """Migrate former public hosts; preserve custom ports, paths and servers."""
    url = validate_url(url)
    parts = urlsplit(url)
    if parts.hostname in LEGACY_HOSTS:
        authority = urlsplit(DEFAULT_URL).hostname
        if parts.port is not None:
            authority += f':{parts.port}'
        return urlunsplit(parts._replace(netloc=authority))
    return url


def game_downloads(url):
    server = site_url(url.strip() or DEFAULT_URL)
    games = api_call(server, 'GET', '/api/netplay/games/', timeout=5)['games']
    downloads = {}
    for entry in games:
        links = {}
        for key in ('rom_url', 'bios_url'):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                target = urljoin(server.rstrip('/') + '/', value.strip())
                parts = urlsplit(target)
                if parts.scheme in ('http', 'https') and parts.hostname:
                    links[key] = target
        downloads[entry['game']] = links
    return downloads


class MembershipStore:
    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def member(self, url, event_id):
        key = f'{site_url(url)}/events/{int(event_id)}'
        data = self._read()
        member = data.get(key)
        if not isinstance(member, dict):
            # Old releases stored credentials under either former domain.
            # Normalize the URL, including its trailing slash, before comparing.
            for old_key, old_member in data.items():
                old_url, separator, old_event = old_key.rpartition('/events/')
                if not separator or old_event != str(int(event_id)):
                    continue
                try:
                    matches = site_url(old_url) == site_url(url)
                except (ValueError, TypeError):
                    continue
                if matches and isinstance(old_member, dict):
                    member = old_member
                    break
        if not isinstance(member, dict) or not isinstance(member.get('key'), str):
            member = {'key': uuid4().hex, 'ticket': ''}
        if data.get(key) != member:
            data[key] = member
            # Persist before the HTTP request: a lost response can be retried
            # with the same key without creating a second participant.
            write_json(self.path, data, private=True)
        return dict(member)

    def save_ticket(self, url, event_id, ticket):
        key = f'{site_url(url)}/events/{int(event_id)}'
        self.member(url, event_id)
        data = self._read()
        data[key]['ticket'] = ticket
        write_json(self.path, data, private=True)

    def stored_ticket(self, url, event_id):
        key = f'{site_url(url)}/events/{int(event_id)}'
        member = self._read().get(key)
        return member.get('ticket', '') if isinstance(member, dict) else ''


def list_events(url):
    data = api_call(site_url(url), 'GET', '/api/netplay/events/', timeout=4)
    if not isinstance(data.get('events'), list):
        raise AccountError('Actualiza Django para consultar los eventos KOTH desde el launcher.')
    return data['events']


def get_event(url, event_id):
    return api_call(site_url(url), 'GET', f'/api/netplay/events/{int(event_id)}/', timeout=4)


def leave_casual(url, event_id, session, ticket=''):
    return api_call(site_url(url), 'POST', f'/api/netplay/events/{int(event_id)}/leave/', {},
                    token=ticket if not session else '',
                    extra_headers={'X-Netplay-Session': session} if session else None,
                    follow_redirects=False)


TOURNAMENT_FORMATS = {'round_robin': 'Round Robin', 'single_elimination': 'Single Elimination',
                      'double_elimination': 'Double Elimination'}


def scheduled_tournaments(url, *, all_statuses=False, session=None):
    path = '/api/netplay/tournaments/' + ('?scope=all' if all_statuses else '')
    url = site_url(url)
    if session and urlsplit(url).scheme == 'https':
        result = api_call(url, 'GET', path, timeout=8, extra_headers={'X-Netplay-Session': session},
                          follow_redirects=False)
    else:
        result = api_call(url, 'GET', path, timeout=8)
    if not isinstance(result, dict) or not isinstance(result.get('events'), list):
        raise AccountError('El servidor no devolvió la lista de torneos.')
    return [event for event in result['events'] if event.get('format') in TOURNAMENT_FORMATS]


def tournament_bracket(url, event_id):
    return api_call(site_url(url), 'GET', f'/api/netplay/tournaments/{int(event_id)}/bracket/', timeout=8)


def assigned_fixture(url, session, event_id, *, fixture_id=None, exclude=()):
    """Return the account's first ready match in this tournament, in Django's fixture order."""
    url = site_url(url)
    if not session or urlsplit(url).scheme != 'https':
        raise AccountError('Conectar al cruce requiere HTTPS y una sesión de Discord.')
    result = api_call(url, 'GET', '/api/netplay/fixtures/', timeout=8,
                      extra_headers={'X-Netplay-Session': session}, follow_redirects=False)
    return next((fixture for fixture in result['fixtures']
                 if fixture['event_id'] == event_id and fixture['role'] in ('p1', 'p2') and fixture['session']
                 and fixture['fixture_id'] not in exclude
                 and (fixture_id is None or fixture['fixture_id'] == fixture_id)), None)


def fixture_result_grant(args, login):
    event, fixture = args.tournament_fixture
    url = site_url(args.api_url)
    if urlsplit(url).scheme != 'https' or not login:
        raise AccountError('El marcador del torneo requiere una sesión verificada por HTTPS.')
    grant = api_call(url, 'POST', f'/api/netplay/events/{event}/fixtures/{fixture}/result-ticket/', {},
                     extra_headers={'X-Netplay-Session': login}, follow_redirects=False)
    if grant.get('fixture_id') != fixture or not grant.get('ticket') or not grant.get('session'):
        raise AccountError('Django no confirmó el permiso de marcador para este cruce.')
    return grant


def wait_fixture(args, is_host, login, stopped):
    import ipaddress
    import time
    from hill import file_tag
    url = site_url(args.api_url)
    if urlsplit(url).scheme != 'https' or not login:
        raise AccountError('Conectar al cruce requiere HTTPS y una sesión de Discord.')
    event, fixture = args.tournament_fixture
    path = f'/api/netplay/events/{event}/fixtures/{fixture}/sync/'
    body = {'address': args.bind_address, 'game': args.fixture_game, 'state_tag': file_tag(args.state),
            'symbols_tag': file_tag(args.symbols), 'attempt': uuid4().hex, 'peer_attempt': '', 'dual_report': True}
    preference = getattr(args, 'fixture_transport', 'direct-only')
    if preference != 'direct-only':
        body['transport'] = preference

    def heartbeat(payload):
        return api_call(url, 'POST', path, payload, timeout=6,
                        extra_headers={'X-Netplay-Session': login}, follow_redirects=False)

    print('Torneo: esperando al otro jugador del cruce…', flush=True)
    while not stopped():
        try:
            result = heartbeat(body)
        except AccountError as error:
            if error.code and error.code < 500:
                raise
            print(f'ZeroTier: reintentando coordinación ({error}).', flush=True)
        else:
            if result['role'] != ('p1' if is_host else 'p2'):
                raise AccountError('El rol del cruce cambió. Actualiza la lista.')
            body['peer_attempt'] = result['peer_attempt']
            if result['ready'] and result['session_epoch'] != getattr(args, 'previous_fixture_epoch', None):
                args.session_epoch = result['session_epoch']
                args.fixture_result_grant = result.get('result_grant')
                transport = result.get('transport', 'zerotier')
                if transport == 'relay':
                    if preference == 'direct-only' or not args.fixture_result_grant:
                        raise AccountError('El cruce por Netplay requiere dos launchers actualizados.')
                    args.fixture_relay = True
                    if is_host:
                        def publish_room(room_id):
                            ack = heartbeat({**body, 'room_id': room_id, 'room_epoch': args.session_epoch})
                            if not ack['ready'] or ack.get('session_epoch') != args.session_epoch or ack.get('relay_room') != room_id:
                                raise AccountError('Django no confirmó la sala de Netplay para esta pelea.')
                        args.publish_fixture_room = publish_room
                    else:
                        args.room = result['relay_room']
                    print(f'Netplay: cruce {fixture} · {"P1" if is_host else "P2"}.', flush=True)
                    return not stopped()
                if transport != 'zerotier' or preference == 'relay':
                    raise AccountError('Django no confirmó el transporte solicitado para este cruce.')
                peer = str(ipaddress.IPv4Address(result['address']))
                if peer == args.bind_address:
                    raise AccountError('Ambos jugadores registraron la misma IPv4 de ZeroTier. Revisen la red elegida.')
                if is_host:
                    args.expect_guest_ip = peer
                else:
                    port = int(result['port'])
                    if not 1 <= port <= 65535:
                        raise AccountError('Django devolvió un puerto UDP inválido para P1.')
                    args.connect = f'{peer}:{port}'
                endpoint = peer if is_host else args.connect
                print(f'ZeroTier: cruce {fixture} · {"P1" if is_host else "P2"} · '
                      f'local {args.bind_address} · rival {endpoint} · sesión {args.session_epoch}.', flush=True)
                return not stopped()
        for _ in range(10):
            if stopped():
                return False
            time.sleep(0.2)
    return False


def tournament_label(event):
    parts = [event['name'], TOURNAMENT_FORMATS[event['format']], event.get('event_date'),
             f"{event['enrolled']}/{event['max_participants']}"]
    return ' · '.join(part for part in parts if part)


def join_tournament(url, session, event_id):
    url = site_url(url)
    if urlsplit(url).scheme != 'https' or not session:
        raise AccountError('La inscripción requiere HTTPS y una sesión de Discord en Netplay.')
    result = api_call(url, 'POST', f'/api/netplay/tournaments/{int(event_id)}/join/', {}, timeout=12,
                      extra_headers={'X-Netplay-Session': session}, follow_redirects=False)
    if not isinstance(result, dict) or type(result.get('participant_id')) is not int or result['participant_id'] < 1:
        raise AccountError('El servidor no confirmó la inscripción.')
    return result['participant_id']


def manage_casual_tournament(url, session, body=None, *, event_id=None):
    url = site_url(url)
    if urlsplit(url).scheme != 'https' or not session:
        raise AccountError('La gestión del torneo requiere HTTPS y una sesión de Discord.')
    action = 'casual/' if event_id is None else f'{int(event_id)}/start/'
    return api_call(url, 'POST', '/api/netplay/tournaments/' + action, body or {}, timeout=12,
                    extra_headers={'X-Netplay-Session': session}, follow_redirects=False)


def _management_request(url, session, method, path, body=None):
    url = site_url(url)
    if urlsplit(url).scheme != 'https':
        raise AccountError('La administración de eventos requiere una URL HTTPS.')
    if not session:
        raise AccountError('Inicia sesión con Discord en Netplay.')
    return api_call(url, method, '/api/netplay/events/' + path, body, timeout=10,
                    extra_headers={'X-Netplay-Session': session}, follow_redirects=False)


def management_access(url, session):
    return _management_request(url, session, 'GET', 'management/')


def management_command(url, session, body, event=None):
    if event is None:
        path = 'casual/'
    else:
        kind = 'casual' if event.get('casual') else 'official'
        path = f"{int(event['id'])}/{kind}/"
    return _management_request(url, session, 'POST', path, body)


def watch_ticket(url, session, event_id):
    return _management_request(url, session, 'POST', f'{int(event_id)}/watch/')


def event_for_ticket(url, ticket):
    try:
        return api_call(site_url(url), 'GET', '/api/netplay/events/current/', token=ticket, timeout=5,
                        follow_redirects=False)
    except AccountError as error:
        if error.code != 404:
            raise
        raise AccountError(
            'No se pudo obtener el evento de este código KOTH. Selecciona el evento en Rey de la Colina '
            'o solicita un código vigente para cargar su estado.', 404,
        ) from None


def enroll(url, event, name, store, fallback_ticket='', netplay_session='', *, address=''):
    url = site_url(url)
    require_address_session(address, netplay_session)
    event_id = int(event['id'])
    member = store.member(url, event_id)
    body = {'version': event['version'], 'name': name, 'registration_key': member['key']}
    if address:
        body['zerotier_address'] = address
    ticket = member.get('ticket') or fallback_ticket
    for attempt in range(2):
        try:
            result = api_call(url, 'POST', f'/api/netplay/events/{event_id}/join/', body,
                              token=ticket, timeout=12,
                              extra_headers={'X-Netplay-Session': netplay_session} if netplay_session else None)
            if netplay_session and not result.get('account_linked'):
                raise AccountError('Actualiza Django para vincular tu cuenta de Discord con el participante del netplay.')
            if not result.get('ticket') or not isinstance(result.get('event'), dict):
                raise AccountError('Django no devolvió la inscripción KOTH esperada.')
            check_address_result(result, address)
            store.save_ticket(url, event_id, result['ticket'])
            return result
        except AccountError as error:
            if error.code != 409 or attempt:
                raise
            body['version'] = get_event(url, event_id)['version']


def require_address_session(address, session):
    if address and not session:
        raise AccountError('Inicia sesión con Discord para conectar a KOTH.')


def check_address_result(result, address):
    if address and result.get('zerotier_address') != address:
        raise AccountError('Django no confirmó la IP de ZeroTier. Actualiza el servidor KOTH.')


def link_account(url, ticket, netplay_session, *, address=''):
    require_address_session(address, netplay_session)
    body = {'zerotier_address': address} if address else {}
    try:
        result = api_call(site_url(url), 'POST', '/api/netplay/link-account/', body, token=ticket, timeout=12,
                          extra_headers={'X-Netplay-Session': netplay_session})
    except AccountError as error:
        if error.code == 404:
            raise AccountError('Actualiza Django para vincular las cuentas de Discord del launcher y de la web.', 404) from None
        raise
    if not result.get('account_linked') or not result.get('ticket'):
        raise AccountError('Django no confirmó la vinculación de tu cuenta de Discord.')
    check_address_result(result, address)
    return result
