"""Event discovery and enrollment with guest or verified Discord identity."""
import json
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit

from appdata import write_json
from discord_auth import AccountError, api_call
from hill import validate_url

DEFAULT_URL = 'https://narutimateonline.sytes.net'
LEGACY_HOST = 'narultimateonline.sytes.net'


def site_url(url):
    """Repair the misspelled default shipped previously; preserve custom sites."""
    url = validate_url(url)
    parts = urlsplit(url)
    if parts.hostname == LEGACY_HOST:
        authority = 'narutimateonline.sytes.net'
        if parts.port is not None:
            authority += f':{parts.port}'
        return urlunsplit(parts._replace(netloc=authority))
    return url


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
        if not isinstance(member, dict) and key.startswith(DEFAULT_URL+'/'):
            member = data.get(key.replace('narutimateonline.sytes.net', LEGACY_HOST, 1))
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


def list_events(url):
    data = api_call(site_url(url), 'GET', '/api/netplay/events/', timeout=4)
    if not isinstance(data.get('events'), list):
        raise AccountError('Actualiza Django para consultar los eventos KOTH desde el launcher.')
    return data['events']


def get_event(url, event_id):
    return api_call(site_url(url), 'GET', f'/api/netplay/events/{int(event_id)}/', timeout=4)


def enroll(url, event, name, store, fallback_ticket='', netplay_session=''):
    url = site_url(url)
    event_id = int(event['id'])
    member = store.member(url, event_id)
    body = {'version': event['version'], 'name': name, 'registration_key': member['key']}
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
            store.save_ticket(url, event_id, result['ticket'])
            return result
        except AccountError as error:
            if error.code != 409 or attempt:
                raise
            body['version'] = get_event(url, event_id)['version']


def link_account(url, ticket, netplay_session):
    try:
        result = api_call(site_url(url), 'POST', '/api/netplay/link-account/', {}, token=ticket, timeout=12,
                          extra_headers={'X-Netplay-Session': netplay_session})
    except AccountError as error:
        if error.code == 404:
            raise AccountError('Actualiza Django para vincular las cuentas de Discord del launcher y de la web.', 404) from None
        raise
    if not result.get('account_linked') or not result.get('ticket'):
        raise AccountError('Django no confirmó la vinculación de tu cuenta de Discord.')
    return result
