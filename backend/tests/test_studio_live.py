"""Real bounded playback, CEF compositing and browser acceptance; opt-in only."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
import uvicorn

from app.config import ROOT, Settings
from app.main import create_app


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        return listener.getsockname()[1]


def amcp(port, command):
    with socket.create_connection(('127.0.0.1',port),timeout=5) as connection:
        connection.sendall((command+'\r\n').encode())
        answer=connection.recv(65536).decode()
        assert answer.startswith(('200 ','201 ','202 ')),answer
        return answer


@pytest.mark.caspar
@pytest.mark.skipif(os.environ.get('OPENPLAYOUT_TEST_STUDIO')!='1',reason='Real studio acceptance is opt-in')
def test_real_segments_break_resume_and_graphics():
    workspace=ROOT/'.tools'/'studio-acceptance'/str(uuid4())
    media=workspace/'media';media.mkdir(parents=True)
    bundle=ROOT/'.tools'/'casparcg'/'2.5.1'
    ffmpeg=str(bundle/'ffmpeg.exe')
    subprocess.run([ffmpeg,'-v','error','-nostdin','-n','-f','lavfi','-i','color=c=red:s=320x180:r=25:d=3','-f','lavfi','-i','color=c=green:s=320x180:r=25:d=7','-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0','-c:v','mpeg4',str(media/'program.mp4')],check=True)
    subprocess.run([ffmpeg,'-v','error','-nostdin','-n','-f','lavfi','-i','color=c=blue:s=320x180:r=25','-t','3','-c:v','mpeg4',str(media/'bumper.mp4')],check=True)
    original=hashlib.sha256((media/'program.mp4').read_bytes()).hexdigest()
    port,http_port=free_port(),free_port()
    cfg=Settings(data_dir=workspace/'data',caspar_port=port,caspar_media_root=str(media),graphics_base_url=f'http://127.0.0.1:{http_port}',origins=f'http://127.0.0.1:{http_port}')
    app=create_app(cfg)
    observations=[]
    with TestClient(app) as client:
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=http_port,lifespan='off',log_level='warning'))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        try:
            client.headers['Authorization']='Bearer '+cfg.api_token
            def post(path,body=None):
                r=client.post('/api'+path,json=body)
                assert r.status_code==200,r.text
                return r.json()
            post('/playout',{'action':'disconnect'})
            channel=client.get('/api/settings').json()['channel'];channel['directories']=[str(media)]
            assert client.put('/api/settings',json=channel).status_code==200
            assert post('/media/scan',{'directory':str(media)})['indexed']==2
            assets={m['title']:m for m in client.get('/api/media').json()}
            ids=[post('/media/'+assets['program']['id']+'/segments',{'label':label,'in_frame':first,'out_frame':last})['id'] for label,first,last in [('Part 1',0,75),('Part 2',75,150)]]
            def resource(kind,name,payload):return post('/resources',{'kind':kind,'name':name,'payload':payload})['id']
            logo=resource('graphics','Acceptance logo',{'layout':'logo'})
            banner=resource('graphics','Acceptance NOW/NEXT',{'layout':'now_next'})
            instances=[post('/graphics',{'template_id':template,'layer':layer,'parameters':{'text':'OPENPLAYOUT LIVE'}})['id'] for template,layer in [(logo,200),(banner,210)]]
            # Start overlays before program so CEF has time to initialize.
            for instance in instances:post('/graphics/'+instance,{'action':'show'})
            time.sleep(2)
            seq=resource('sequence','Segment break resume',{'items':[{'kind':'segment','reference':ids[0]},{'kind':'media','reference':assets['bumper']['id']},{'kind':'segment','reference':ids[1]}]})
            plan=post('/resources/'+seq+'/preview',{})
            assert plan['duration_frames']==225
            post('/playout',{'action':'connect'})
            post('/resources/'+seq+'/run',{'signature':plan['signature']})
            deadline=time.monotonic()+15
            stages=set();captures=set()
            while time.monotonic()<deadline:
                state=client.get('/api/status').json()
                observations.append(state)
                assert state['error'] is None,state['error']
                item=state['current'];obs=state['observation']
                segment=(item or {}).get('segment')
                stage=segment['label'] if segment else (item or {}).get('media',{}).get('title')
                if obs['state']=='playing':
                    stages.add(stage)
                    if stage in ('Part 1','Part 2') and (obs['position_seconds'] or 0)-obs['clip_in_seconds']>.7 and stage not in captures:
                        filename='proof-'+stage.replace(' ','-').lower()
                        amcp(port,f'ADD 1 IMAGE {filename}')
                        captures.add(stage)
                    if stage=='Part 2':
                        assert obs['clip_in_seconds']==3 and obs['clip_duration_seconds']==3
                        assert obs['position_seconds']>=3
                if obs['state']=='ended':break
                time.sleep(.1)
            (workspace/'observations.json').write_text(json.dumps(observations,indent=2),encoding='utf-8')
            assert stages=={'Part 1','bumper','Part 2'},stages
            assert state['observation']['state']=='ended'
            assert captures=={'Part 1','Part 2'}
            for filename in ('proof-part-1.png','proof-part-2.png'):
                assert (media/filename).stat().st_size>1000
            assert hashlib.sha256((media/'program.mp4').read_bytes()).hexdigest()==original
            post('/playout',{'action':'stop'})
            environment=os.environ|{'OPENPLAYOUT_URL':f'http://127.0.0.1:{http_port}','OPENPLAYOUT_TOKEN':cfg.api_token,'OPENPLAYOUT_ARTIFACTS':str(workspace),'OPENPLAYOUT_PROGRAM_ID':assets['program']['id']}
            subprocess.run(['node',str(ROOT/'apps/web/scripts/studio-smoke.mjs')],env=environment,check=True,timeout=60)
            for instance in instances:post('/graphics/'+instance,{'action':'hide'})
            print('Real studio acceptance artifacts: '+str(workspace))
        finally:
            server.should_exit=True;thread.join(timeout=5)
