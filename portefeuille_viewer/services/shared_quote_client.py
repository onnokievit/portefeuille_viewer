"""Qt facade for a shared feed; a viewer never writes its cached live quotes back."""
import logging
import queue
import threading
import time
from uuid import uuid4

from PySide6.QtCore import QObject,Signal

from portefeuille_viewer.config import get_settings,get_stockdata_db_path
from portefeuille_viewer.config.local_runtime import canonical_host
from portefeuille_viewer.services.price_feed import PriceFeedService
from portefeuille_viewer.services.subscription_manager import SubscriptionManager
from portefeuille_viewer.services.shared_quote_coordinator import ensure_coordinator,rpc


class RemoteSubscriptions:
    def __init__(self,feed):
        self.feed=feed
        self.fallback=SubscriptionManager(None,**get_settings().get_market_data_settings()).snapshot()

    def snapshot(self):
        try:
            result=self.feed.request({'op':'snapshot'})
            self.fallback=result
        except (OSError,EOFError,RuntimeError,TimeoutError):
            result=dict(self.fallback)
            result['connected']=False
        return result

    def configure(self,**values):return self.feed.request({'op':'configure','values':values})
    def reset_rejection_counters(self):self.feed.enqueue({'op':'reset'})
    def set_focus(self,keys):self.feed.set_rows('focus',list(keys))
    def processed(self,*args):pass  # the original service in the coordinator tracks actual processing


class RemotePriceFeedIB(QObject):
    quoteReceived=Signal(str,str,float,dict)
    optionTickUpdated=Signal(dict)
    statusChanged=Signal(str)
    connectionLost=Signal(str)
    ready=Signal()
    log=Signal(str)
    _shared_proxy=True

    def __init__(self,host,port,client_id):
        super().__init__()
        self.host,self.port,self.client_id=canonical_host(host),int(port),int(client_id)
        self.key=uuid4().hex
        self.profile=getattr(get_settings(),'profile_database',None) or 'viewer'
        self.subscriptions=RemoteSubscriptions(self)
        self.lock=threading.RLock();self.commands=queue.Queue()
        self.desired={'assets':[],'options':[],'focus':[]};self.changed=set(self.desired)
        self.callbacks={};self.manifest=None;self.sequence=0
        self.info={'status':'connecting','host':host,'port':port,'client_id':client_id,'is_ready':False}
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self._loop,daemon=True,name='shared-quotes-client')
        self.thread.start()

    def request(self,command):
        with self.lock:manifest=self.manifest
        if manifest is None:raise RuntimeError('Koerscoördinator nog niet verbonden')
        return rpc(manifest,{**command,'client':self.key})

    def enqueue(self,command):self.commands.put(command)

    def set_rows(self,kind,rows):
        with self.lock:
            self.desired[kind]=list(rows);self.changed.add(kind)

    def _status(self,info):
        with self.lock:
            old=self.info;self.info=dict(info)
        if old.get('status')!=info.get('status'):
            self.statusChanged.emit(str(info.get('status','disconnected')))
        if not old.get('is_ready') and info.get('is_ready'):self.ready.emit()
        if old.get('is_ready') and not info.get('is_ready'):self.connectionLost.emit(str(info.get('status','disconnected')))

    def _dispatch(self,kind,payload):
        if kind=='quote':
            pair,price,receipt=payload
            self.quoteReceived.emit(pair[0],pair[1],price,receipt)
        elif kind=='option':self.optionTickUpdated.emit(payload)
        elif kind in ('detail','detail_end','secdef'):
            token=payload[0]
            with self.lock:callbacks=self.callbacks.get(token)
            if callbacks:
                detail,end,_expires=callbacks
                try:
                    if kind=='detail_end':
                        with self.lock:self.callbacks.pop(token,None)
                        end()
                    elif kind=='secdef':detail(*payload[1])
                    else:detail(payload[1])
                except Exception:logging.exception('Contract callback failed')

    def _loop(self):
        joined=False
        while not self.stop.is_set():
            try:
                if not joined:
                    manifest=ensure_coordinator(get_stockdata_db_path(),self.host,self.port,self.client_id)
                    if self.stop.is_set():break
                    with self.lock:self.manifest=manifest
                    state=self.request({'op':'join','profile':self.profile})
                    self.sequence=state['sequence']
                    for kind,payload in state['latest']:self._dispatch(kind,payload)
                    with self.lock:self.changed.update(self.desired)
                    joined=True
                with self.lock:
                    changed={key:list(self.desired[key]) for key in self.changed}
                    self.changed.clear()
                for kind,rows in changed.items():self.request({'op':kind,'rows':rows})
                for _ in range(100):
                    try:command=self.commands.get_nowait()
                    except queue.Empty:break
                    self.request(command)
                state=self.request({'op':'poll','since':self.sequence})
                if state.get('resync'):
                    for kind,payload in state['latest']:self._dispatch(kind,payload)
                for _seq,kind,payload in state['events']:self._dispatch(kind,payload)
                self.sequence=state['sequence'];self._status(state['info'])
                with self.lock:
                    self.callbacks={k:v for k,v in self.callbacks.items() if v[2]>time.monotonic()}
            except Exception as exc:
                self._status({**self.info,'status':'reconnecting','is_ready':False,'last_disconnect_reason':str(exc)})
                self.log.emit('[shared-quotes] '+str(exc))
                joined=False
                self.stop.wait(1)
            self.stop.wait(.2)
        if joined:
            try:self.request({'op':'leave'})
            except Exception:logging.exception('Could not unregister quote client; lease will expire')

    def is_ready(self):return bool(self.connection_info().get('is_ready'))
    def connection_info(self):
        with self.lock:return dict(self.info)
    def connection_status(self):return str(self.connection_info().get('status','disconnected'))
    def endpoint(self):
        info=self.connection_info();return info['host'],int(info['port']),int(info['client_id'])
    def reconnect(self,host=None,port=None,client_id=None,**kwargs):
        if (host is not None and canonical_host(host) != self.host) or port not in (None,self.port):
            raise ValueError('Start dit profiel opnieuw om een andere TWS-verbinding te gebruiken')
        self.enqueue({'op':'reconnect','client_id':client_id})
    def ensure_subscriptions(self,rows):self.set_rows('assets',rows)
    def ensure_option_subscriptions(self,rows):self.set_rows('options',rows)
    def request_contract_details(self,contract,on_detail,on_end):
        token=uuid4().hex
        with self.lock:self.callbacks[token]=(on_detail,on_end,time.monotonic()+60)
        self.enqueue({'op':'details','contract':contract,'token':token})
        return token
    def request_secdef_opt_params(self,symbol,exchange,sec_type,conid,on_param,on_end):
        token=uuid4().hex
        with self.lock:self.callbacks[token]=(on_param,on_end,time.monotonic()+60)
        self.enqueue({'op':'secdef','args':(symbol,exchange,sec_type,conid),'token':token})
        return token
    def shutdown(self):
        self.stop.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=6)


class SharedPriceFeedService(PriceFeedService):
    def __init__(self,host,port,client_id,parent=None):
        super().__init__(host,port,client_id,parent,feed_factory=RemotePriceFeedIB)
