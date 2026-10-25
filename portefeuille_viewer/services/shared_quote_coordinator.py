"""One existing PriceFeedService/SubscriptionManager shared over a local named pipe."""
import argparse
from collections import deque
import copy
import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from uuid import uuid4

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from multiprocessing.connection import Client, Listener
from portefeuille_viewer.config.local_runtime import FileLease, resource_id, runtime_root, canonical_host
from portefeuille_viewer.config.process_lock import canonical_path

PROTOCOL = 1


def coordinator_manifest(stock_path, host, port):
    key = resource_id(canonical_path(stock_path) + '|' + canonical_host(host) + ':' + str(port))
    return runtime_root() / ('quotes-' + key + '.json')


def rpc(manifest, command, timeout=5):
    info = json.loads(Path(manifest).read_text(encoding='utf-8'))
    connection = Client(info['pipe'], family='AF_PIPE', authkey=bytes.fromhex(info['auth']))
    try:
        connection.send(command)
        if not connection.poll(timeout):
            raise TimeoutError('Lokale koerscoördinator reageert niet')
        response = connection.recv()
        if not response.get('ok'):
            raise RuntimeError(response.get('error', 'Coördinatorfout'))
        return response.get('value')
    finally:
        connection.close()


def ensure_coordinator(stock_path, host, port, client_id):
    host = canonical_host(host)
    manifest = coordinator_manifest(stock_path, host, port)
    lease = FileLease('quote-start:' + str(manifest))
    if not lease.acquire(15):
        raise TimeoutError('Starten van de gedeelde koerscoördinator duurt te lang')
    try:
        try:
            info = rpc(manifest, {'op':'ping'}, timeout=2)
            if info['protocol'] != PROTOCOL:
                raise RuntimeError('Niet-compatibele koerscoördinator; sluit alle instanties en start opnieuw')
            return manifest
        except (OSError, EOFError, json.JSONDecodeError, TimeoutError):
            pass
        # Do not overwrite credentials of a live but temporarily unresponsive server.
        probe = FileLease('quote-server:' + str(manifest.resolve()))
        if not probe.acquire():
            raise RuntimeError('De koerscoördinator draait maar reageert nog niet; opnieuw verbinden volgt')
        probe.release()
        info = {'pipe':r'\\.\pipe\PortefeuilleViewer-' + resource_id(str(manifest)),
                'auth':secrets.token_hex(32), 'stock':canonical_path(stock_path),
                'host':host, 'port':int(port), 'client_id':int(client_id), 'protocol':PROTOCOL}
        tmp = manifest.with_suffix('.tmp-' + uuid4().hex)
        tmp.write_text(json.dumps(info),encoding='utf-8');os.replace(tmp,manifest)
        env = os.environ.copy()
        env.pop('PV_PROFILE_DATABASE',None)
        env['PV_COORDINATOR']='1'
        env['PV_STOCKDATA_DATABASE']=canonical_path(stock_path)
        env['PV_INSTANCE_RUNTIME']=str(manifest.parent / manifest.stem)
        log = open(manifest.with_suffix('.log'),'ab',buffering=0)
        try:
            process = subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--manifest',str(manifest)],
                       cwd=str(APP_ROOT),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            log.close()
        deadline = time.monotonic()+15
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise RuntimeError('Koerscoördinator kon niet starten; zie '+str(manifest.with_suffix('.log')))
            try:
                rpc(manifest,{'op':'ping'},timeout=1)
                return manifest
            except (OSError,EOFError,TimeoutError):
                time.sleep(.1)
        process.terminate();process.wait(timeout=5)
        raise TimeoutError('Koerscoördinator is niet bereikbaar na starten')
    finally:
        lease.release()


class QuoteHub:
    """Thread-safe registry; transport and subscription logic remain in the original feed."""
    def __init__(self, feed, clock=time.monotonic):
        self.feed=feed;self.clock=clock;self.lock=threading.RLock()
        self.clients={};self.events=deque(maxlen=20000);self.sequence=0
        self.latest={};self.idle_since=clock()
        feed._feed.quoteReceived.connect(self.quote)
        feed.optionTickUpdated.connect(self.option)
        self._stop=False
        self.reserved=0

    def event(self, kind, payload, recipient=None):
        with self.lock:
            self.sequence+=1
            self.events.append((self.sequence,kind,copy.deepcopy(payload),recipient))
            if recipient is None:
                key=(kind,payload[0]) if kind=='quote' else (kind,payload.get('series_id'),payload.get('field'))
                self.latest[key]=(kind,copy.deepcopy(payload))

    def quote(self,symbol,currency,price,receipt):
        self.event('quote',((symbol,currency),price,receipt))

    def option(self,payload):
        self.event('option',payload)

    def _reconcile(self):
        assets={};options={};focus=set()
        for client in self.clients.values():
            for row in client['assets']:assets[repr(row)]=row
            for row in client['options']:options[repr(row)]=row
            focus.update(tuple(key) for key in client['focus'])
        reserved = sum(c.get('reserved', 0) for c in self.clients.values())
        manager = self.feed._feed.subscriptions
        with manager.lock:
            manager.effective_capacity = max(1, min(manager.capacity-reserved,
                manager.effective_capacity+self.reserved-reserved))
        self.reserved = reserved
        self.feed.ensure_subscriptions(list(assets.values()))
        self.feed.ensure_option_subscriptions(list(options.values()))
        self.feed.set_active_option_series_ids([r[0] for r in options.values()])
        self.feed._feed.subscriptions.set_focus(focus)
        with manager.lock:
            records = list(manager.records.values())
        pairs = {(r.spec['symbol'], r.spec['currency']) for r in records if r.spec['kind']=='asset'}
        series = {int(row[0]) for row in options.values()}
        self.latest = {key:value for key,value in self.latest.items()
            if (key[0]=='quote' and key[1] in pairs) or (key[0]=='option' and key[1] in series)}

    def expire(self,ttl=10):
        with self.lock:
            stale=[key for key,c in self.clients.items() if self.clock()-c['seen']>ttl]
            for key in stale:self.clients.pop(key)
            if stale:self._reconcile()
            if self.clients:self.idle_since=self.clock()
            return not self.clients and self.clock()-self.idle_since>15

    def command(self,request):
        with self.lock:
            op=request['op'];key=request.get('client')
            if op=='ping':return {'protocol':PROTOCOL,'pid':os.getpid(),'clients':len(self.clients)}
            if op=='join':
                self.clients[key]={'seen':self.clock(),'assets':[],'options':[],'focus':[],'profile':request.get('profile',''), 'reserved':0}
                self.idle_since=self.clock()
                return {'sequence':self.sequence,'latest':list(self.latest.values()),'info':self.feed.connection_info()}
            if key not in self.clients:raise RuntimeError('Koerssessie verlopen; opnieuw aanmelden')
            client=self.clients[key];client['seen']=self.clock()
            if op=='poll':
                since=int(request.get('since',0))
                events=[(seq,kind,payload) for seq,kind,payload,recipient in self.events if seq>since and recipient in (None,key)]
                return {'sequence':self.sequence,'events':events,'info':self.feed.connection_info(),
                        'resync':bool(self.events and since<self.events[0][0]-1),
                        'latest':list(self.latest.values()) if self.events and since<self.events[0][0]-1 else []}
            if op in ('assets','options','focus'):
                client[op]=request['rows'];self._reconcile();return True
            if op=='reserve':
                amount=max(0,int(request['amount']))
                manager=self.feed._feed.subscriptions
                if amount + self.reserved-client['reserved'] >= manager.capacity:
                    raise RuntimeError('Geen ruimte in het gezamenlijke koersbudget voor deze taak')
                client['reserved']=amount
                self._reconcile()
                return True
            if op=='leave':self.clients.pop(key);self._reconcile();return True
            if op=='snapshot':
                snapshot=self.feed.subscription_snapshot()
                snapshot['shared_clients']=[c['profile'] for c in self.clients.values()]
                snapshot['coordinator_pid']=os.getpid()
                snapshot['reserved_external']=self.reserved
                snapshot['reservations_ready']=(snapshot['occupied']<=snapshot['effective_capacity'] and not self.feed._feed.subscriptions.pending_cancels)
                return snapshot
            if op=='configure':
                if int(request['values']['capacity']) <= self.reserved:
                    raise RuntimeError('Koersbudget is kleiner dan de actieve achtergrondreserveringen')
                self.feed.configure_subscriptions(**request['values'])
                self.reserved=0
                self._reconcile()
                return True
            if op=='reset':self.feed.reset_subscription_rejection_counters();return True
            if op=='reconnect':
                endpoint=self.feed.endpoint()
                if request.get('host',endpoint[0]) not in (None,endpoint[0]) or request.get('port',endpoint[1]) not in (None,endpoint[1]):
                    raise ValueError('Sluit dit profiel en start met de nieuwe TWS-verbinding')
                self.feed.reconnect(client_id=request.get('client_id'));return True
            if op=='details':
                token=request['token']
                self.feed._feed.request_contract_details(request['contract'],
                    lambda detail:self.event('detail',(token,detail),key),
                    lambda:self.event('detail_end',(token,),key))
                return token
            if op=='secdef':
                token=request['token']
                self.feed._feed.request_secdef_opt_params(*request['args'],
                    lambda *values:self.event('secdef',(token,values),key),
                    lambda:self.event('detail_end',(token,),key))
                return token
            raise ValueError('Onbekend coördinatorcommando: '+op)


def serve(manifest, factory=None):
    from PySide6.QtCore import QCoreApplication,QTimer
    from portefeuille_viewer.services.price_feed import PriceFeedService
    info=json.loads(Path(manifest).read_text(encoding='utf-8'))
    singleton=FileLease('quote-server:'+str(Path(manifest).resolve()))
    if not singleton.acquire():return
    app=QCoreApplication.instance() or QCoreApplication([])
    from portefeuille_viewer.data.stockdata_worker import enable_stockdata_workers, shutdown_stockdata_workers
    if factory is None:
        enable_stockdata_workers()
    feed=(factory or PriceFeedService)(info['host'],info['port'],info['client_id'])
    hub=QuoteHub(feed)
    listener=Listener(info['pipe'],family='AF_PIPE',authkey=bytes.fromhex(info['auth']))
    def handle(connection):
        try:
            request=connection.recv()
            connection.send({'ok':True,'value':hub.command(request)})
        except Exception as exc:
            logging.exception('Coordinator request failed')
            try:connection.send({'ok':False,'error':str(exc)})
            except (OSError,EOFError):pass
        finally:connection.close()
    def accept():
        while not hub._stop:
            try:
                connection=listener.accept()
                threading.Thread(target=handle,args=(connection,),daemon=True).start()
            except (OSError,EOFError):
                if not hub._stop:logging.exception('Coordinator accept failed')
    threading.Thread(target=accept,daemon=True,name='local-quote-pipe').start()
    timer=QTimer();timer.setInterval(1000)
    timer.timeout.connect(lambda:app.quit() if hub.expire() else None);timer.start()
    try:app.exec()
    finally:
        hub._stop=True
        try:
            listener.close()
            feed.shutdown()
        finally:
            if factory is None:
                shutdown_stockdata_workers()
            singleton.release()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True)
    arguments=parser.parse_args();serve(arguments.manifest)
