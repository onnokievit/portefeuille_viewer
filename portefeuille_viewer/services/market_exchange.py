"""Resumable Wyse → STOCKDATA synchronization; network never holds DB locks."""
import ipaddress
import json
from pathlib import Path
import threading
import urllib.error
import urllib.parse
import urllib.request


def remote_collection_enabled():
    """Configured remote ownership; failures do not silently enable a second writer."""
    from portefeuille_viewer.config.local_runtime import runtime_root
    path = runtime_root() / 'market-exchange-v1' / 'connection.json'
    if not path.exists():
        return False
    return json.loads(path.read_text(encoding='utf-8-sig')).get('enabled', False) is True


def validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('Gebruik een serveradres zonder pad, credentials of query')
    if not parsed.hostname or parsed.scheme not in ('http', 'https'):
        raise ValueError('Serveradres moet HTTP of HTTPS gebruiken')
    if parsed.scheme == 'http':
        # HTTP only for explicit local addresses; public endpoints must use TLS.
        try:
            address = ipaddress.ip_address(parsed.hostname)
            local = address.is_private and not address.is_unspecified
        except ValueError:
            local = parsed.hostname.lower() in ('homeserver1', 'localhost') or parsed.hostname.endswith('.local')
        if not local:
            raise ValueError('Buitenshuis is HTTPS verplicht')
    return url.rstrip('/')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('API-redirect geweigerd; configureer het definitieve serveradres')


class ExchangeHTTP:
    def __init__(self, url, token, timeout=15, *, cloudflare_client_id='', cloudflare_client_secret=''):
        self.url = validate_url(url)
        if len(token) < 32:
            raise ValueError('API-toegangssleutel ontbreekt of is te kort')
        if bool(cloudflare_client_id) != bool(cloudflare_client_secret):
            raise ValueError('Cloudflare-toegang vereist zowel client-ID als client-secret')
        if cloudflare_client_id and urllib.parse.urlsplit(self.url).scheme != 'https':
            raise ValueError('Cloudflare-toegangssleutels mogen uitsluitend via HTTPS worden verstuurd')
        if any('\r' in value or '\n' in value for value in (token, cloudflare_client_id, cloudflare_client_secret)):
            raise ValueError('Ongeldige toegangssleutel: regeleinde gevonden')
        self.token, self.timeout = token, timeout
        self.cloudflare_headers = ({'CF-Access-Client-Id': cloudflare_client_id,
            'CF-Access-Client-Secret': cloudflare_client_secret} if cloudflare_client_id else {})
        # No browser cookies, environment proxies or credential forwarding on redirects.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(self, path, **query):
        url = self.url + '/api/v1/' + path
        if query:
            url += '?' + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/json', 'User-Agent': 'PortefeuilleViewer/1.7 Exchange/1',
            **self.cloudflare_headers})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.headers.get_content_type() != 'application/json':
                    raise ValueError('API gaf geen JSON terug')
                raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise ValueError('API-pagina te groot')
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise RuntimeError('Wyse API HTTP ' + str(exc.code)) from None
        except urllib.error.URLError:
            raise RuntimeError('Wyse niet bereikbaar; volgende poging hervat de synchronisatie') from None


def validate_page(page, manifest, old):
    if page.get('api_version') != 1 or manifest.get('api_version') != 1:
        raise ValueError('Niet-ondersteunde API-versie')
    identity = page.get('stream_id')
    if not isinstance(identity, str) or not identity or identity != manifest.get('stream_id'):
        raise ValueError('Ongeldige API-streamidentiteit')
    after, cursor, high = (page.get(k) for k in ('after', 'next_cursor', 'high_watermark'))
    if any(type(v) is not int or v < 0 for v in (after, cursor, high)) or not after <= cursor <= high:
        raise ValueError('Ongeldige API-voortgang')
    items = page.get('items')
    if not isinstance(items, list) or len(items) > 500 or page.get('has_more') != (cursor < high):
        raise ValueError('Ongeldige API-pagina')
    if old['cursor'] != after or old['stream_id'] not in ('', identity):
        raise ValueError('Stream of voortgang gewijzigd; geen gegevens overschreven')
    previous = after
    for item in items:
        seq = item.get('sequence')
        if type(seq) is not int or not previous < seq <= cursor:
            raise ValueError('Wijzigingen staan niet in oplopende volgorde')
        previous = seq
        required = ('id', 'source', 'dataset', 'subject', 'payload', 'schema_version', 'revision')
        if any(k not in item for k in required):
            raise ValueError('Onvolledige gegevensenvelop')
        if not all(isinstance(item[k], str) and item[k] for k in ('id', 'source', 'dataset')):
            raise ValueError('Ongeldige gegevensidentificatie')
        if (type(item['revision']) is not int or item['revision'] < 1 or
                type(item['schema_version']) is not int or item['schema_version'] < 1 or
                not isinstance(item['payload'], dict) or not isinstance(item['subject'], dict) or
                not all(isinstance(item['subject'].get(k), str) and item['subject'][k] for k in ('type', 'id'))):
            raise ValueError('Ongeldige gegevensstructuur')
        if item.get('operation') not in ('upsert', 'delete'):
            raise ValueError('Onbekende gegevensbewerking')
        json.dumps(item, allow_nan=False)
    if previous != cursor or not items and cursor != after:
        raise ValueError('Cursor past niet bij ontvangen wijzigingen')
    if not items and page['has_more']:
        raise ValueError('Lege pagina met openstaande wijzigingen')
    return items


def synchronize(client, inbox, stop=None, max_pages=20):
    manifest = client.get('manifest')
    count = 0
    for _ in range(max_pages):
        if stop and stop.is_set():
            break
        state = inbox.state()
        page = client.get('changes', after=state['cursor'], stream_id=state['stream_id'], limit=500)
        count += inbox.apply(page, manifest)
        if not page['has_more']:
            return dict(status='ok', received=count, cursor=page['next_cursor'])
    return dict(status='catching_up', received=count, cursor=inbox.state()['cursor'])


class MarketExchangeService:
    """One fixed thread per app; OS lease allows only one profile to fetch at once."""
    def __init__(self, config_path=None, stockdata_path=None):
        from portefeuille_viewer.config.local_runtime import runtime_root
        self.root = runtime_root() / 'market-exchange-v1'
        self.stockdata_path = stockdata_path
        self.config_path = Path(config_path) if config_path else self.root / 'connection.json'
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self._status = dict(status='starting', message='Wyse-synchronisatie wordt gestart')
        self.thread = threading.Thread(target=self._run, name='market-exchange', daemon=True)

    def start(self):
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return dict(self._status)

    def publish(self, **values):
        with self.lock:
            self._status = values

    def _run(self):
        from portefeuille_viewer.config.local_runtime import FileLease
        if self.stop_event.wait(20):
            return
        while not self.stop_event.is_set():
            delay = 60
            inbox = None
            lease = None
            try:
                if not self.config_path.exists():
                    self.publish(status='disabled', message='Wyse-synchronisatie niet ingesteld')
                else:
                    config = json.loads(self.config_path.read_text(encoding='utf-8-sig'))
                    if not config.get('enabled', False):
                        self.publish(status='disabled', message='Wyse-synchronisatie uitgeschakeld')
                    else:
                        client = ExchangeHTTP(config['server_url'], config['api_token'],
                            cloudflare_client_id=config.get('cloudflare_client_id', ''),
                            cloudflare_client_secret=config.get('cloudflare_client_secret', ''))
                        from portefeuille_viewer.config import get_stockdata_db_path
                        from portefeuille_viewer.config.process_lock import canonical_path
                        from portefeuille_viewer.data.market_exchange_repository import StockdataInbox
                        path = self.stockdata_path or get_stockdata_db_path()
                        lease = FileLease('market-exchange-stockdata-v1:' + canonical_path(path))
                        if lease.acquire():
                            inbox = StockdataInbox(path)
                            result = synchronize(client, inbox, self.stop_event)
                            if result['status'] == 'catching_up':
                                message = 'Wyse: synchroniseren — ' + str(result['received']) + ' wijzigingen verwerkt'
                            elif result['received']:
                                message = 'Wyse: ' + str(result['received']) + ' nieuwe wijzigingen verwerkt'
                            else:
                                message = 'Wyse: STOCKDATA bijgewerkt — geen nieuwe wijzigingen'
                            self.publish(**result, last_sync=inbox.state()['last_sync'],
                                message=message)
                            if result['status'] == 'catching_up':
                                delay = 1
                        else:
                            self.publish(status='shared', message='Wyse-synchronisatie loopt via een ander profiel')
            except Exception as exc:
                # Do not log credentials, complete URLs or raw server responses.
                message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                self.publish(status='error', message='Wyse-synchronisatie: ' + message)
            finally:
                if inbox:
                    inbox.close()
                if lease:
                    lease.release()
            self.stop_event.wait(delay)

    def stop(self):
        # Never wait for network I/O on the Qt thread. An in-flight page is atomic;
        # this daemon exits after the bounded request or on process shutdown.
        self.stop_event.set()
