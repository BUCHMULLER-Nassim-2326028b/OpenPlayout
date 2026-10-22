import {useRef, useState} from 'react';
import {useQuery, useQueryClient} from '@tanstack/react-query';
import {api} from './api';
import type {Media, SettingsResponse} from './types';

interface Boundary {id: string; label: string; in_frame: number; out_frame: number | null; fps_num: number; fps_den: number; kind?: string; notes?: string; triggers?: string[]}
export default function ChaptersPage() {
  const cache = useQueryClient(), video = useRef<HTMLVideoElement>(null);
  const media = useQuery({queryKey:['media'], queryFn:()=>api<Media[]>('/media')});
  const settings = useQuery({queryKey:['settings'], queryFn:()=>api<SettingsResponse>('/settings')});
  const [asset,setAsset]=useState(''), [url,setUrl]=useState(''), [label,setLabel]=useState('Chapter'), [first,setFirst]=useState(0), [last,setLast]=useState(75), [position,setPosition]=useState(0), [editing,setEditing]=useState(''), [notes,setNotes]=useState(''), [triggers,setTriggers]=useState(''), [error,setError]=useState(''), [busy,setBusy]=useState(false), [notice,setNotice]=useState('');
  const cfg=settings.data?.channel, fps=(cfg?.fps_num||25)/(cfg?.fps_den||1);
  const chapters=useQuery({queryKey:['chapters',asset],enabled:!!asset,queryFn:()=>api<{chapters:Boundary[];segments:Boundary[];embedded:unknown[]}>(`/media/${asset}/chapters`)});
  async function work(fn:()=>Promise<unknown>) {setBusy(true);setError('');setNotice('');try{await fn();await cache.invalidateQueries({queryKey:['chapters',asset]});}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  function seek(frame:number){if(video.current){video.current.currentTime=Math.max(0,frame/fps);setPosition(frame);}}
  async function select(id:string){setAsset(id);setUrl('');setEditing('');if(id)await work(async()=>setUrl((await api<{url:string}>(`/media/${id}/preview-session`,'POST')).url));}
  const body={label,in_frame:first,out_frame:last,fps_num:cfg?.fps_num||25,fps_den:cfg?.fps_den||1,notes,triggers:triggers.split(',').map(s=>s.trim()).filter(Boolean)};
  return <><div className="page-heading"><div><p className="eyebrow">SOURCE EDITING</p><h1>Chapters & virtual segments</h1></div></div>
    {error&&<p className="error" role="alert">{error}</p>}{notice&&<p className="success" role="status">{notice}</p>}
    <section className="panel settings-panel"><label>Source video<select aria-label="Source video" value={asset} onChange={e=>void select(e.target.value)}><option value="">Select indexed video</option>{media.data?.filter(m=>m.kind==='video').map(m=><option key={m.id} value={m.id}>{m.title}</option>)}</select></label>
    {asset&&<><p className="muted">Browser source preview. Seeking depends on browser decoding; CasparCG uses the saved frame boundaries. IN inclusive, OUT exclusive. Source files stay unchanged.</p>
      <video className="source-preview" ref={video} src={url||undefined} controls onTimeUpdate={()=>setPosition(Math.round((video.current?.currentTime||0)*fps))}/>
      <div className="transport"><button onClick={()=>seek(position-1)}>−1 frame</button><strong className="mono">Frame {position} / {fps.toFixed(3)} fps</strong><button onClick={()=>seek(position+1)}>+1 frame</button><button onClick={()=>setFirst(position)}>Mark IN</button><button onClick={()=>setLast(position)}>Mark OUT</button></div>
      <form onSubmit={e=>{e.preventDefault();void work(async()=>{await api(editing?`/chapters/${editing}`:`/media/${asset}/chapters`,editing?'PUT':'POST',body);setEditing('');setNotice('Chapter saved');});}}>
      <div className="form-grid"><label>Label<input required value={label} onChange={e=>setLabel(e.target.value)}/></label><label>IN frame<input type="number" min="0" required value={first} onChange={e=>setFirst(+e.target.value)}/></label><label>OUT frame<input type="number" min={first+1} required value={last} onChange={e=>setLast(+e.target.value)}/></label><label>Notes<input value={notes} onChange={e=>setNotes(e.target.value)}/></label><label>Chapter automation IDs (comma separated)<input value={triggers} onChange={e=>setTriggers(e.target.value)}/></label></div>
      <div className="transport"><button disabled={busy} className="primary">{editing?'Update chapter':'Save chapter'}</button><button type="button" disabled={busy} onClick={()=>void work(async()=>{await api(`/media/${asset}/segments`,'POST',body);setNotice('Virtual segment saved');})}>Save as virtual segment</button><button type="button" disabled={busy} onClick={()=>void work(async()=>{const r=await api<{imported:number}>(`/media/${asset}/chapters/import`,'POST');setNotice(`Imported ${r.imported} embedded chapters`);})}>Import embedded chapters ({chapters.data?.embedded.length||0})</button></div></form></>}
    </section>
    {asset&&<div className="studio-columns"><section className="panel settings-panel"><h2>Chapters</h2>{chapters.data?.chapters.map(c=><div className="studio-row" key={c.id}><div><strong>{c.label}</strong><small>{c.in_frame} → {c.out_frame??'marker'} @ {c.fps_num}/{c.fps_den}</small></div><button onClick={()=>{setEditing(c.id);setLabel(c.label);setFirst(c.in_frame);setLast(c.out_frame||c.in_frame+1);setNotes(c.notes||'');setTriggers(c.triggers?.join(', ')||'');seek(c.in_frame*fps*c.fps_den/c.fps_num);}}>Edit</button><button disabled={busy} onClick={()=>void work(()=>api(`/chapters/${c.id}`,'DELETE'))}>Delete</button></div>)}</section>
      <section className="panel settings-panel"><h2>Virtual segments</h2><p className="muted">Build a sequence in Automation studio: segment → break/video → next segment.</p>{chapters.data?.segments.map(s=><div className="studio-row" key={s.id}><div><strong>{s.label}</strong><small>{s.in_frame} → {s.out_frame} @ {s.fps_num}/{s.fps_den}</small></div><button disabled={busy} onClick={()=>void work(()=>api(`/segments/${s.id}/preview`,'POST'))}>Play on program</button></div>)}</section></div>}
  </>;
}
