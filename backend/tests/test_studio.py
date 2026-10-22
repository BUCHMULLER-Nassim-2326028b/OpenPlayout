import hashlib
import io
import json
import sqlite3
import time
import zipfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from app.database import AutomationEvent, PlaybackHistory, PlayoutSession
from test_api import add_asset


def resource(client, kind, payload, name='Test template'):
    result = client.post('/api/resources', json={'name': name, 'kind': kind, 'payload': payload})
    assert result.status_code == 200, result.text
    return result.json()['id']


def collection(client, ids, name='Collection'):
    result = client.post('/api/collections', json={'name': name, 'media_ids': ids})
    assert result.status_code == 200, result.text
    return result.json()['id']


def segment(client, media, first, last):
    result = client.post(f'/api/media/{media}/segments', json={'label':f'{first}-{last}', 'in_frame':first, 'out_frame':last})
    assert result.status_code == 200, result.text
    return result.json()['id']


def wait_for(predicate):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        if value := predicate():
            return value
        time.sleep(.04)
    raise AssertionError('Timed out waiting for background observation/event')


def test_chapters_segments_bounds_and_source_unchanged(harness):
    client, app, _, root = harness
    media = add_asset(app, root)
    before = hashlib.sha256((root/'one.mp4').read_bytes()).hexdigest()
    body = {'label':'Boundary', 'in_frame':75, 'out_frame':150, 'notes':'test'}
    chapter = client.post(f'/api/media/{media}/chapters', json=body).json()['id']
    assert client.put(f'/api/chapters/{chapter}', json=body|{'label':'Edited'}).status_code == 200
    assert client.get(f'/api/media/{media}/chapters').json()['chapters'][0]['label'] == 'Edited'
    assert client.post(f'/api/media/{media}/segments', json=body|{'out_frame':300}).status_code == 400
    assert client.post(f'/api/media/{media}/segments', json=body|{'in_frame':1,'out_frame':10,'fps_num':24}).status_code == 400
    assert client.post(f'/api/media/{media}/segments', json=body|{'out_frame':75}).status_code == 400
    segment(client, media, 75, 150)
    assert client.delete(f'/api/chapters/{chapter}').status_code == 200
    assert hashlib.sha256((root/'one.mp4').read_bytes()).hexdigest() == before


def test_scoped_range_preview_requires_session(harness):
    client, app, _, root = harness
    one, two = add_asset(app,root), add_asset(app,root,'two.mp4')
    assert client.get(f'/api/media/{one}/content').status_code == 401
    session = client.post(f'/api/media/{one}/preview-session').json()
    assert 'token' not in session['url']
    response = client.get(session['url'], headers={'Range':'bytes=0-3','Authorization':''})
    assert response.status_code == 206 and response.content == b'test'
    assert client.get(f'/api/media/{two}/content').status_code == 401


def test_segment_break_resume_and_native_bounds(harness):
    client, app, engine, root = harness
    media, bumper = add_asset(app,root), add_asset(app,root,'break.mp4')
    first, last = segment(client,media,0,75), segment(client,media,75,150)
    template = resource(client,'sequence',{'items':[{'kind':'segment','reference':first},{'kind':'media','reference':bumper},{'kind':'segment','reference':last}]})
    preview = client.post(f'/api/resources/{template}/preview',json={}).json()
    assert preview['duration_frames'] == 400
    client.post('/api/playout',json={'action':'connect'})
    assert client.post(f'/api/resources/{template}/run',json={'signature':preview['signature']}).status_code == 200
    assert engine.bounds == (0,75)
    engine.finish()
    wait_for(lambda:client.get('/api/status').json()['current']['media']['id']==bumper)
    engine.finish()
    wait_for(lambda:(client.get('/api/status').json()['current'].get('segment') or {}).get('id')==last)
    assert engine.bounds == (75,150) and engine.position == 3
    assert client.post('/api/playout',json={'action':'seek','frame':74}).status_code == 409
    assert client.post('/api/playout',json={'action':'seek','frame':100}).status_code == 200
    assert not client.get('/api/playlists/main').json()


def test_nested_cycle_and_hard_deadline_rejected(harness):
    client, app, _, root = harness
    media = add_asset(app,root)
    inner = resource(client,'sequence',{'items':[{'kind':'media','reference':media}]})
    outer = resource(client,'sequence',{'items':[{'kind':'sequence','reference':inner}]})
    now = datetime.now(timezone.utc)
    assert client.post(f'/api/resources/{outer}/preview',json={'start_at':now.isoformat(),'deadline':(now+timedelta(seconds=9)).isoformat()}).status_code == 400
    client.put(f'/api/resources/{inner}',json={'kind':'sequence','name':'Cycle','payload':{'items':[{'kind':'sequence','reference':outer}]}})
    assert 'cycle' in client.post(f'/api/resources/{outer}/preview',json={}).json()['detail']


def test_rules_repeated_groups_breaks_fill_exact_deadline(harness):
    client, app, _, root = harness
    programs = [add_asset(app,root,f'program-{n}.mp4') for n in range(4)]
    bumpers = [add_asset(app,root,f'bumper-{n}.mp4') for n in range(2)]
    pc, bc = collection(client,programs), collection(client,bumpers)
    br = resource(client,'break',{'stages':[{'collection_id':bc}], 'target_seconds':'10'})
    rule = resource(client,'rule',{'collection_id':pc,'min_items':2,'preferred_items':2,'max_items':2,'max_groups':2,'break_id':br})
    now = datetime.now(timezone.utc)
    response = client.post(f'/api/resources/{rule}/preview',json={'start_at':now.isoformat(),'deadline':(now+timedelta(seconds=50)).isoformat(),'strict':True})
    assert response.status_code == 200,response.text
    result = response.json()
    assert result['duration_frames'] == 1250 and result['unused_frames']==0
    assert [bool(i.get('break_id')) for i in result['items']] == [False,False,True,False,False]
    assert client.post(f'/api/resources/{rule}/preview',json={'target_seconds':'49','strict':True}).status_code == 400


def test_cooldown_history_and_filler_selection(harness):
    client, app, _, root = harness
    program, filler = add_asset(app,root), add_asset(app,root,'filler.mp4')
    pc, fc = collection(client,[program]),collection(client,[filler])
    rule = resource(client,'rule',{'collection_id':pc,'allow_new_group':False,'filler_collection_id':fc,'no_repeat_hours':24})
    assert client.post(f'/api/resources/{rule}/preview',json={'target_seconds':'20','strict':True}).json()['duration_frames']==500
    with app.state.sessions() as db:
        db.add(PlaybackHistory(media_id=program, outcome='completed'))
        db.commit()
    assert client.post(f'/api/resources/{rule}/preview',json={'target_seconds':'20'}).status_code==400


def test_break_required_stage_and_target_can_overshoot_preference(harness):
    client, app, _, root = harness
    a,b=add_asset(app,root),add_asset(app,root,'b.mp4')
    ca,cb=collection(client,[a]),collection(client,[b])
    br=resource(client,'break',{'stages':[{'collection_id':ca},{'collection_id':cb}],'target_seconds':'15'})
    assert client.post(f'/api/resources/{br}/preview',json={'target_seconds':'30'}).json()['duration_frames']==500
    assert client.post(f'/api/resources/{br}/preview',json={'target_seconds':'19'}).status_code==400


def test_stale_preview_does_not_start_output(harness):
    client,app,engine,root=harness
    media=add_asset(app,root)
    seq=resource(client,'sequence',{'items':[{'kind':'media','reference':media}]})
    preview=client.post(f'/api/resources/{seq}/preview',json={}).json()
    client.put(f'/api/media/{media}/tags',json={'tags':['changed']})
    client.post('/api/playout',json={'action':'connect'})
    response=client.post(f'/api/resources/{seq}/run',json={'signature':preview['signature']})
    assert response.status_code==409 and engine.foreground is None


def test_graphics_context_updates_and_hook_action(harness):
    client,app,engine,root=harness
    a,b=add_asset(app,root),add_asset(app,root,'b.mp4')
    template=resource(client,'graphics',{'layout':'now_next'})
    assert client.post('/api/graphics',json={'template_id':template,'layer':1}).status_code==400
    instance=client.post('/api/graphics',json={'template_id':template,'layer':200}).json()['id']
    resource(client,'automation',{'hook':'media.started','actions':[{'type':'graphics.show','instance_id':instance}]})
    for media in (a,b):client.post('/api/playlists/main/items',json={'media_id':media})
    client.post('/api/playout',json={'action':'connect'})
    client.post('/api/playout',json={'action':'play'})
    wait_for(lambda:any(c[0]=='graphic' for c in engine.calls))
    url=client.get(f'/api/graphics/{instance}/preview').json()['url']
    path,key=url.split('?')
    context=client.get(path+'/context?'+key,headers={'Authorization':''}).json()
    assert context['now']['title']=='one' and context['next']['title']=='b'
    assert client.get(path+'?key=wrong').status_code==403
    engine.finish()
    wait_for(lambda:client.get(path+'/context?'+key).json()['now']['title']=='b')
    assert client.get(path+'/context?'+key).json()['next']['title']==''
    assert client.post(f'/api/graphics/{instance}',json={'action':'variables','parameters':{'text':'Updated'}}).status_code==200
    assert client.get(path+'/context?'+key).json()['variables']['text']=='Updated'


def test_plugin_failure_isolated_from_playout(harness):
    client,app,engine,root=harness
    def fail(hook,payload):raise RuntimeError('Test plugin failure')
    app.state.events.subscribe('media.started',fail)
    media=add_asset(app,root)
    client.post('/api/playlists/main/items',json={'media_id':media})
    client.post('/api/playout',json={'action':'connect'})
    client.post('/api/playout',json={'action':'play'})
    wait_for(lambda:client.get('/api/diagnostics').json()['automation']['errors']>0)
    assert engine.state=='playing' and client.get('/api/status').json()['error'] is None


def test_backup_integrity_config_round_trip_and_recovery_expected_position(harness,tmp_path):
    client,app,_,root=harness
    media=add_asset(app,root)
    client.post('/api/playlists/main/items',json={'media_id':media})
    client.post('/api/playout',json={'action':'connect'})
    client.post('/api/playout',json={'action':'play'})
    item=client.get('/api/status').json()['current']
    with app.state.sessions() as db:
        old=db.get(PlayoutSession,'main')
        if old:db.delete(old);db.flush()
        db.add(PlayoutSession(id='main',state='playing',updated_at=(datetime.now(timezone.utc)-timedelta(seconds=2)).isoformat(),snapshot={'item':item,'queue':[item], 'observation':{'position_seconds':1,'duration_seconds':10}}))
        db.commit()
    preview=client.get('/api/recovery').json()['preview']
    assert preview['available'] and 75<=preview['source_frame']<90
    backup=client.post('/api/backups').json()
    data=client.get('/api/backups/'+backup['id']).content
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert set(archive.namelist())=={'openplayout.db','manifest.json'}
        database=tmp_path/'restored.db';database.write_bytes(archive.read('openplayout.db'))
    with sqlite3.connect(database) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT count(*) FROM media_assets').fetchone()[0]==1
    cfg=client.get('/api/configuration/export').json()
    client.post('/api/playout',json={'action':'disconnect'})
    assert client.post('/api/configuration/import',json=cfg).status_code==400
    assert client.post('/api/configuration/import',json=cfg|{'confirm_replace_settings':True}).status_code==200


def test_resource_portability_and_invalid_actions(harness):
    client,_,_,_=harness
    seq=resource(client,'sequence',{'items':[]})
    exported=client.get(f'/api/resources/{seq}/export').json()
    assert 'id' not in exported
    assert client.post('/api/resources/import',json=exported).status_code==200
    assert client.post('/api/resources',json={'kind':'automation','name':'Unsafe','payload':{'hook':'media.started','actions':[{'type':'shell','command':'no'}]}}).status_code==400
    assert client.post('/api/resources',json={'kind':'graphics','name':'Unsafe','payload':{'source':'remote','url':'http://example.com'}}).status_code==400
