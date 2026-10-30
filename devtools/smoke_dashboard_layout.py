"""Real QtWebEngine smoke test with in-memory snapshots/settings only."""
import configparser
import json
from pathlib import Path
from types import SimpleNamespace
import polars as pl
import sys
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from portefeuille_viewer.config.settings_manager import SettingsManager
from portefeuille_viewer.ui_logica import asset_dashboard_tab as module
from devtools.test_asset_dashboard import DashboardTests
from devtools.test_asset_dashboard_analytics import fixture

app=QApplication([])
settings=SettingsManager.__new__(SettingsManager)
settings.config=configparser.ConfigParser();settings.save=Mock();settings.get_eurusd=Mock(return_value=1.)
settings.config.read_dict({'ui':{'asset_dashboard_theme':'sand'}})
store=DashboardTests().store()
store.snapshot_aandelen_projection_v2=store.snapshot_aandelen_projection_v2.with_columns(pl.Series('koers_prev',[110.,19.]),pl.Series('pct_change',[-.0076,.01]),pl.Series('portfolio_total_waarde_lineair_pct',[.13,.1]),pl.Series('portfolio_total_waarde_delta_pct',[.15,.1]))
analytics_store,payload,cfg=fixture()
temp_preferences=TemporaryDirectory()
preferences_file=Path(temp_preferences.name)/'dashboard.json'
errors=[];result=[];tabs=[]
comment_cache={'known-test':dict(uniek_id='known-test',optie_comment='oud',optie_comment_color='#f8d7da',optie_comment_textcolor='#000000')}
def fetch_comments(ids):return pl.DataFrame([comment_cache[i] for i in ids if i in comment_cache])
def commit_comment(value):comment_cache[value['uniek_id']]={**comment_cache.get(value['uniek_id'],{}),**value}

def create(mode):
    tab=module.AssetDashboardTab(editable_layout=True,layout_mode=mode)
    tab._request_earnings=Mock()
    legacy=SimpleNamespace(_on_comment_commit=Mock(side_effect=commit_comment),_patch_comment_in_models=Mock(),
        commentFlushTimer=SimpleNamespace(isActive=lambda:False,start=Mock()))
    tab.set_comment_target(legacy);tab._comment_editor.remember([dict(id='known-test')])
    def publish(payload):
        calculated=module.calculate_analytics(analytics_store,payload,cfg)
        tab.bridge.analyticsUpdated.emit(json.dumps(calculated))
    tab._request_analytics=publish
    tab.resize(2300 if mode=='desktop' else 1300,1150)
    tab.set_active(True);tab.show();tabs.append(tab)
    return tab

def fail(message):
    errors.append(message);app.quit()

def check_desktop():
    desktop.web.page().runJavaScript("""JSON.stringify({blocks:document.querySelectorAll('.layout-item').length,asset:document.getElementById('asset').value,grid:getComputedStyle(document.querySelector('.layout-canvas')).gridTemplateColumns,canvases:[...document.querySelectorAll('canvas')].map(c=>({id:c.id,w:c.width,h:c.height})),mode:document.querySelector('.layout-toolbar').dataset.mode,metrics:[...document.querySelectorAll('#metrics b')].map(n=>n.textContent),busy:document.querySelector('.dashboard-workspace').getAttribute('aria-busy'),assetInfo:!!document.querySelector('[data-block=asset_info] #asset'),headerAsset:!!document.querySelector('header #asset'),events:!!document.querySelector('[data-block=asset_info] #dividend')&&!!document.querySelector('[data-block=asset_info] #earnings')})""",desktop_ready)

def desktop_ready(raw):
    try:
        value=json.loads(raw);assert value['blocks']==11,value;assert value['asset']=='AAPL',value
        assert value['mode']=='desktop';assert value['busy']=='false',value
        assert value['assetInfo'] and value['events'] and not value['headerAsset'],value
        assert [value['metrics'][i] for i in (2,4,5)]==['-0,76%','13,00%','15,00%'],value
        assert all(c['w']>0 and c['h']>0 for c in value['canvases']),value
        assert len(value['grid'].split())==240,value
        desktop.web.page().runJavaScript("JSON.stringify({overflow:document.getElementById('payoff-table').scrollWidth>document.getElementById('payoff-table').clientWidth+1,width:document.querySelector('#payoff-table th').getBoundingClientRect().width,padding:getComputedStyle(document.querySelector('#payoff-table td')).paddingRight})",payoff_fit_ready)
        desktop.web.page().runJavaScript("""
          const geometry=()=>['payoff-table','asset-info-panel','indicator'].map(id=>{const n=document.getElementById(id);return [n.getBoundingClientRect().height,n.clientHeight,n.scrollHeight];});
          const beforeEdit=JSON.stringify(geometry());
          document.getElementById('layout-edit').click();
          window.editGeometryStable=beforeEdit===JSON.stringify(geometry())&&!document.querySelector('.layout-handle,.layout-resize');
          const grid=document.querySelector('.layout-canvas'),handle=document.querySelector('[data-block=payoff] .layout-edge[data-action=move]');
          handle.setPointerCapture=()=>{};
          handle.dispatchEvent(new PointerEvent('pointerdown',{button:0,clientX:100,clientY:100,bubbles:true,pointerId:1}));
          grid.dispatchEvent(new PointerEvent('pointermove',{clientX:100+grid.getBoundingClientRect().width/240,clientY:100,bubbles:true,pointerId:1}));
          grid.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:1}));
          const resize=document.querySelector('[data-block=payoff] .layout-edge[data-edge=se]');resize.setPointerCapture=()=>{};
          resize.dispatchEvent(new PointerEvent('pointerdown',{button:0,clientX:100,clientY:100,bubbles:true,pointerId:2}));
          grid.dispatchEvent(new PointerEvent('pointermove',{clientX:100,clientY:127,bubbles:true,pointerId:2}));
          grid.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:2}));
          document.getElementById('layout-edit').click();""")
        QTimer.singleShot(700,after_save)
    except Exception as exc:fail(str(exc))

def payoff_fit_ready(raw):
    try:
        value=json.loads(raw);assert not value['overflow'],value
        assert abs(value['width']-84)<1,value;assert value['padding']=='2px',value
        desktop.web.page().runJavaScript("""(()=>{
          const grips=document.querySelectorAll('#position-group-1 .position-column-grip');if(document.querySelector('.payoff-column-grip'))throw new Error('Payoff resizing must be removed');
          for(const [index,delta]of [[0,20],[1,6]]){
            const grip=grips[index];grip.setPointerCapture=()=>{};
            grip.dispatchEvent(new PointerEvent('pointerdown',{button:0,clientX:100,bubbles:true,pointerId:7}));
            grip.dispatchEvent(new PointerEvent('pointermove',{clientX:100+delta,bubbles:true,pointerId:7}));
            grip.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:7}));
          }
        })()""")
    except Exception as exc:fail(str(exc))

def after_save():
    global laptop
    try:
        saved=settings.get_asset_dashboard_layout('desktop');assert saved,saved
        columns=settings.get_asset_dashboard_position_columns('desktop');assert columns,columns
        assert columns['tables']['options'][0]>4/107,columns
        assert settings.get_asset_dashboard_position_columns('laptop') is None
        payoff=next(b for b in saved['blocks'] if b['id']=='payoff');assert payoff['x']==71,payoff;assert payoff['h']==170,payoff
        assert settings.get_asset_dashboard_layout('laptop') is None
        desktop.web.page().runJavaScript("document.querySelector('[data-block=payoff]').style.gridColumn=document.querySelector('[data-block=payoff_table]').style.gridColumn")
        QTimer.singleShot(200,check_payoff_alignment)
    except Exception as exc:fail(str(exc))

def check_payoff_alignment():
    desktop.web.page().runJavaScript("""(()=>{
      const chart=document.getElementById('payoff-chart'),rect=chart.getBoundingClientRect();
      const cells=[...document.querySelector('#payoff-table thead tr').cells].slice(1);
      const left=rect.left+Number(chart.dataset.plotLeft),right=rect.left+Number(chart.dataset.plotRight);
      const errors=cells.map((cell,i)=>{const r=cell.getBoundingClientRect();return Math.abs((r.left+r.right)/2-(left+(i+.5)/cells.length*(right-left)));});
      return JSON.stringify({leftError:Math.abs(left-cells[0].getBoundingClientRect().left),rightError:Math.abs(right-cells.at(-1).getBoundingClientRect().right),centers:Math.max(...errors),editGeometryStable:window.editGeometryStable,label:document.querySelector('#payoff-table tbody th').textContent});
    })()""",payoff_alignment_ready)

def payoff_alignment_ready(raw):
    global laptop
    try:
        value=json.loads(raw);assert value['leftError']<1,value;assert value['rightError']<1,value
        assert value['centers']<1,value;assert value['label']=='Open aand.',value
        assert value['editGeometryStable'],value
        desktop.set_active(False)
        desktop.grab().save(str(Path('C:/python_coding/diagnostics/dashboard_layout_desktop.png')))
        laptop=create('laptop');QTimer.singleShot(1800,check_laptop)
    except Exception as exc:fail(str(exc))

def check_laptop():
    laptop.web.page().runJavaScript("JSON.stringify({mode:document.querySelector('.layout-toolbar').dataset.mode,blocks:document.querySelectorAll('.layout-item').length,asset:document.getElementById('asset').value})",laptop_ready)

def laptop_ready(raw):
    try:
        value=json.loads(raw);assert value['mode']=='laptop',value;assert value['blocks']==11,value
        laptop.web.page().runJavaScript("""document.getElementById('layout-edit').click();document.querySelector('[data-block=price] .layout-edge[data-edge=se]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));document.getElementById('layout-edit').click();""")
        QTimer.singleShot(500,test_auto_height)
    except Exception as exc:fail(str(exc))

def test_auto_height():
    laptop.web.page().runJavaScript("""(()=>{
      const stack=document.querySelector('.layout-auto-stack'),section=document.getElementById('calls-section');
      const body=section.querySelector('tbody'),row=body.rows[0];
      window.stackOneHeight=stack.getBoundingClientRect().height;
      for(let i=0;i<3;i++)body.append(row.cloneNode(true));
      return body.rows.length;
    })()""",lambda count:QTimer.singleShot(250,check_auto_height))

def check_auto_height():
    laptop.web.page().runJavaScript("""(()=>{
      const stack=document.querySelector('.layout-auto-stack'),calls=document.getElementById('calls-section'),holdings=document.getElementById('holdings-section');
      return JSON.stringify({one:window.stackOneHeight,four:stack.getBoundingClientRect().height,
        gap:holdings.getBoundingClientRect().top-calls.getBoundingClientRect().bottom,
        overflow:[...stack.querySelectorAll('.layout-body,.scroll')].some(e=>e.scrollHeight>e.clientHeight+1)});
    })()""",auto_height_ready)

def auto_height_ready(raw):
    try:
        value=json.loads(raw);assert value['four']>value['one']+30,value
        assert abs(value['gap']-7)<1,value;assert not value['overflow'],value
        laptop.web.page().runJavaScript("document.getElementById('calls-section').hidden=true")
        QTimer.singleShot(150,check_hidden_stack)
    except Exception as exc:fail(str(exc))

def check_hidden_stack():
    laptop.web.page().runJavaScript("""JSON.stringify({height:document.querySelector('.layout-auto-stack').getBoundingClientRect().height,overflow:[...document.querySelector('.layout-auto-stack').querySelectorAll('.layout-body,.scroll')].some(e=>e.scrollHeight>e.clientHeight+1)})""",hidden_ready)

def hidden_ready(raw):
    try:
        value=json.loads(raw);assert value['height']>0,value;assert not value['overflow'],value
        check_test_order_block()
    except Exception as exc:fail(str(exc))

def check_test_order_block():
    laptop.web.page().runJavaScript("""(()=>{
      const table=document.createElement('table'),body=document.createElement('tbody');
      for(let i=0;i<60;i++){const row=document.createElement('tr');const cell=document.createElement('td');cell.textContent='Testorder '+i;row.append(cell);body.append(row);}
      table.append(body);document.getElementById('tests-table').replaceChildren(table);
    })()""")
    QTimer.singleShot(100,verify_test_order_block)

def verify_test_order_block():
    laptop.web.page().runJavaScript("""(()=>{
      const section=document.getElementById('test-orders-section'),body=section.closest('.layout-body'),table=document.getElementById('tests-table');
      return JSON.stringify({details:!!section.querySelector('details'),bodyOverflow:body.scrollHeight>body.clientHeight+1,sectionOverflow:section.scrollHeight>section.clientHeight+1,tableScroll:table.scrollHeight>table.clientHeight,select:document.getElementById('tests-scenario').getBoundingClientRect().height,button:document.getElementById('tests-editor').getBoundingClientRect().height});
    })()""",test_order_block_ready)

def test_order_block_ready(raw):
    try:
        value=json.loads(raw);assert not value['details'],value
        assert not value['bodyOverflow'],value;assert not value['sectionOverflow'],value
        assert value['tableScroll'],value;assert value['select']==value['button'],value
        check_inline_test_comment()
    except Exception as exc:fail(str(exc))

def check_inline_test_comment():
    laptop.web.page().runJavaScript("""(()=>{
      window.inlineState={enabled:false,asset_only:true,scenario:1,scenarios:[{id:1,name:'Default'}],columns:['Broker','Comment'],row_keys:['test-uid'],rows:[[{text:'lynx'},{text:'oud',comment:{id:'known-test',background:'#f8d7da',foreground:'#000000'}}]]};
      updateTestOrders(window.inlineState);
      const cell=document.querySelector('#tests-table [data-comment-id]');cell.focus();cell.textContent='direct geschreven';
      window.inlineState.enabled=true;updateTestOrders(window.inlineState);
      const kept=document.querySelector('#tests-table [data-comment-id]')===cell&&document.activeElement===cell&&cell.textContent==='direct geschreven';
      cell.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));cell.blur();
      return kept;
    })()""",inline_started)

def inline_started(kept):
    if not kept:fail('Test comment editor was replaced during refresh');return
    QTimer.singleShot(400,inline_saved)

def inline_saved():
    try:
        assert comment_cache['known-test']['optie_comment']=='direct geschreven',comment_cache
        assert comment_cache['known-test']['optie_comment_color']=='#f8d7da',comment_cache
        finish()
    except Exception as exc:fail(str(exc))

def finish():
    try:
        assert settings.get_asset_dashboard_layout('laptop') is not None
        assert next(b for b in settings.get_asset_dashboard_layout('desktop')['blocks'] if b['id']=='payoff')['x']==71
        laptop.grab().save(str(Path('C:/python_coding/diagnostics/dashboard_layout_laptop.png')))
        laptop.web.page().runJavaScript("document.getElementById('layout-export').click()")
        QTimer.singleShot(350,preferences_exported)
    except Exception as exc:fail(str(exc))

def preferences_exported():
    try:
        assert preferences_file.exists(),'No settings export file'
        data=json.loads(preferences_file.read_text(encoding='utf-8'))
        assert data['modes']['desktop']['layout'] is not None
        settings.config.set('ui','asset_dashboard_theme','dark')
        for mode in ('desktop','laptop'):
            settings.config.remove_option('ui','asset_dashboard_layout_'+mode)
            settings.config.remove_option('ui','asset_dashboard_position_columns_'+mode)
        laptop.web.page().runJavaScript("document.getElementById('layout-import').click()")
        QTimer.singleShot(1200,preferences_imported)
    except Exception as exc:fail(str(exc))

def preferences_imported():
    laptop.web.page().runJavaScript("JSON.stringify({theme:document.documentElement.dataset.theme,blocks:document.querySelectorAll('.layout-item').length})",preferences_ready)

def preferences_ready(raw):
    try:
        value=json.loads(raw);assert value['theme']=='sand',value;assert value['blocks']==11,value
        assert settings.get_asset_dashboard_layout('desktop') is not None
        assert settings.get_asset_dashboard_layout('laptop') is not None
        result.append('desktop/laptop rendering, editing, persistence and JSON export/import with reload OK')
    except Exception as exc:errors.append(str(exc))
    app.quit()

with patch.object(module.QFileDialog,'getSaveFileName',return_value=(str(preferences_file),'')),patch.object(module.QFileDialog,'getOpenFileName',return_value=(str(preferences_file),'')),patch.object(module,'get_settings',return_value=settings),patch.object(module,'SNAPSHOT_STORE',store),patch('portefeuille_viewer.services.asset_dashboard_comments.repository.fetch_open_optie_comments',side_effect=fetch_comments):
    desktop=create('desktop')
    QTimer.singleShot(2200,check_desktop)
    QTimer.singleShot(18000,lambda:fail('GUI timeout'))
    app.exec()
assert not errors,errors
assert result,'No result'
print(result[0])
temp_preferences.cleanup()
