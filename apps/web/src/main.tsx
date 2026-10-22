import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core';
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { Radio, Library, Settings, Play, Pause, Square, SkipForward, Plug, Plus, Search, GripVertical, Trash2, Film, AlertTriangle, ArrowUp, ArrowDown, LogOut, RefreshCw } from 'lucide-react';
import { api, time, useStore } from './api';
import type { ChannelSettings, Item, Media, SettingsResponse, Status } from './types';
import './styles.css';
import SchedulePage from './SchedulePage';
import ChaptersPage from './ChaptersPage';
import StudioPage from './StudioPage';

const client = new QueryClient({defaultOptions: {queries: {retry: 1, refetchOnWindowFocus: false}}});

function ErrorMessage({error}: {error: Error | null}) {
  return error ? <p className="error" role="alert"><AlertTriangle size={16}/>{error.message}</p> : null;
}

function Synchronize() {
  const token = useStore(s => s.token);
  const setStatus = useStore(s => s.setStatus);
  const setLive = useStore(s => s.setLive);
  const queryClient = useQueryClient();
  const status = useQuery({queryKey: ['status', token], queryFn: () => api<Status>('/status'), refetchInterval: 3000});
  useEffect(() => { if (status.data) setStatus(status.data); }, [status.data, setStatus]);
  useEffect(() => {
    let socket: WebSocket | undefined;
    let retry: ReturnType<typeof setTimeout>;
    let disposed = false;
    let scanRunning = false;
    const connect = () => {
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
      socket.onopen = () => socket?.send(JSON.stringify({token}));
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as {type: string; data: Status};
        if (message.type === 'status') {
          setStatus(message.data); setLive(true);
          if (scanRunning && !message.data.scan?.running) void queryClient.invalidateQueries({queryKey: ['media']});
          scanRunning = !!message.data.scan?.running;
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {setLive(false); if (!disposed) retry = setTimeout(connect, 3000);};
    };
    connect();
    return () => {disposed = true; clearTimeout(retry); socket?.close(); setLive(false);};
  }, [token, setStatus, setLive, queryClient]);
  return <ErrorMessage error={status.error}/>;
}

function Login() {
  const [value, setValue] = useState('');
  const setToken = useStore(s => s.setToken);
  return <main className="login"><div className="panel"><Radio size={32} className="accent"/>
    <h1>OpenPlayout</h1><p>Local broadcast control</p>
    <form onSubmit={e => {e.preventDefault(); setToken(value.trim());}}>
      <label>Local API token<input autoComplete="off" type="password" required value={value} onChange={e => setValue(e.target.value)}/></label>
      <p className="muted">Read <code>data/api-token</code> in your project directory after starting the backend. The token stays in this browser tab.</p>
      <button className="primary" type="submit">Open control room</button>
    </form></div></main>;
}

function RundownRow({item, index, total, locked, onRemove, onMove, onCue, pending}: {
  item: Item; index: number; total: number; locked: boolean; pending: boolean;
  onRemove: () => void; onMove: (delta: number) => void; onCue: () => void;
}) {
  const {attributes, listeners, setNodeRef, transform, transition} = useSortable({id: item.id, disabled: locked});
  const current = useStore(s => s.status?.current?.id === item.id);
  return <div ref={setNodeRef} style={{transform: CSS.Transform.toString(transform), transition}} className={`rundown-row ${current ? 'active-row' : ''}`}>
    <button className="icon grip" {...attributes} {...listeners} disabled={locked} aria-label={`Drag ${item.media.title}`}><GripVertical size={16}/></button>
    <span className="muted mono">{String(index + 1).padStart(2, '0')}</span>
    <div className="truncate"><strong>{item.media.title}</strong><small>{item.media.missing ? 'MISSING FILE' : item.media.error || item.media.relative_path}</small></div>
    <span className="mono">{time(item.media.duration_seconds)}</span>
    <button className="icon" onClick={onCue} disabled={pending} title="Cue on program output (replaces current media)" aria-label={`Cue ${item.media.title}`}><Film size={16}/></button>
    <div className="reorder-buttons"><button className="icon" onClick={() => onMove(-1)} disabled={locked || index === 0} aria-label="Move up"><ArrowUp size={14}/></button><button className="icon" onClick={() => onMove(1)} disabled={locked || index === total - 1} aria-label="Move down"><ArrowDown size={14}/></button></div>
    <button className="icon danger" onClick={onRemove} disabled={locked} aria-label={`Remove ${item.media.title}`}><Trash2 size={15}/></button>
  </div>;
}

function Dashboard() {
  const status = useStore(s => s.status);
  const queryClient = useQueryClient();
  const playlist = useQuery({queryKey: ['playlist'], queryFn: () => api<Item[]>('/playlists/main')});
  const control = useMutation({mutationFn: ({action, item_id}: {action: string; item_id?: string}) => api<Status>('/playout', 'POST', {action, item_id}), onSuccess: s => {useStore.getState().setStatus(s); void queryClient.invalidateQueries({queryKey: ['history']});}});
  const edit = useMutation({mutationFn: ({path, method, body}: {path: string; method: string; body?: unknown}) => api(path, method, body), onSuccess: () => queryClient.invalidateQueries({queryKey: ['playlist']})});
  const sensors = useSensors(useSensor(PointerSensor, {activationConstraint: {distance: 6}}), useSensor(KeyboardSensor, {coordinateGetter: sortableKeyboardCoordinates}));
  const rows = playlist.data || [];
  const locked = !!status?.current || !!status?.automation || edit.isPending;
  const observation = status?.observation;
  const connected = observation?.connected;
  const position = observation?.position_seconds;
  const duration = observation?.duration_seconds;
  const order = (from: number, to: number) => {if (from !== to) edit.mutate({path: '/playlists/main/order', method: 'PUT', body: {item_ids: arrayMove(rows, from, to).map(r => r.id)}});};
  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(event.target.tagName)) return;
      if (event.code === 'Space' && connected && !control.isPending) {event.preventDefault(); control.mutate({action: observation?.state === 'playing' ? 'pause' : 'resume'});}
    };
    window.addEventListener('keydown', handle);
    return () => window.removeEventListener('keydown', handle);
  }, [connected, observation?.state, control]);
  return <>
    <div className="page-heading"><div><p className="eyebrow">OPERATIONS</p><h1>Control room</h1></div><button disabled={control.isPending} onClick={() => control.mutate({action: status?.connection_requested ? 'disconnect' : 'connect'})}><Plug size={16}/>{status?.connection_requested ? 'Disconnect / cancel retry' : 'Connect CasparCG'}</button></div>
    <ErrorMessage error={control.error || edit.error || playlist.error}/>
    {status?.error && <p className="error" role="alert"><AlertTriangle size={16}/>{status.error}</p>}
    {status?.runtime?.error && <p className="error" role="alert"><AlertTriangle size={16}/>{status.runtime.error}</p>}
    <section className="panel schedule-status"><div><strong>{status?.scheduler?.armed_schedule_id ? 'Schedule armed' : 'Schedule disarmed'}</strong><p>{status?.scheduler?.next ? `Next: ${status.scheduler.next.label || status.scheduler.next.media.title} · ${new Date(status.scheduler.next.planned_start).toISOString().slice(11, 19)} UTC` : 'No timed event is waiting to start.'}</p>{status?.scheduler?.error && <p className="warning" role="alert">{status.scheduler.error}</p>}</div><NavLink className="button" to="/schedule">Open schedule</NavLink></section>
    <div className="monitors"><section className="panel program"><div className="panel-heading"><h2>Program output</h2><span className={`badge ${observation?.state === 'playing' ? 'green' : ''}`}>{observation?.state || 'UNKNOWN'}</span></div>
      <div className="monitor"><Radio size={40}/><strong>{observation?.clip || 'No observed media'}</strong><p>Video return is not configured</p><small>Verify the actual CasparCG output on its screen or broadcast device.</small></div>
      <div className="progress"><div style={{width: `${duration && position != null ? Math.min(100, position / duration * 100) : 0}%`}}/></div>
      <div className="timing"><div><small>ELAPSED · SERVER</small><strong className="mono">{time(position)}</strong></div><div><small>REMAINING</small><strong className="mono">{duration != null && position != null ? time(duration - position) : '—'}</strong></div></div>
      <div className="transport"><button className="primary" disabled={!connected || control.isPending || !rows.length} onClick={() => control.mutate({action: 'play'})}><Play size={17}/>Play rundown</button><button disabled={!connected || control.isPending} onClick={() => control.mutate({action: observation?.state === 'paused' ? 'resume' : 'pause'})}><Pause size={16}/>{observation?.state === 'paused' ? 'Resume' : 'Pause'}</button><button disabled={!connected || control.isPending} onClick={() => control.mutate({action: 'stop'})} title="Clear this program layer"><Square size={16}/>Stop</button><button disabled={!connected || !status?.next || control.isPending} onClick={() => control.mutate({action: 'next'})}><SkipForward size={17}/>Next</button></div>
    </section><aside className="panel next-panel"><p className="eyebrow">UP NEXT</p><Film size={32} className="accent"/><h2>{status?.next?.media.title || 'No next item'}</h2><p className="mono">{time(status?.next?.media.duration_seconds)}</p><div className="divider"/><dl><dt>Playback engine</dt><dd>CasparCG</dd><dt>Server startup</dt><dd>{status?.runtime?.managed ? 'Started with app' : status?.runtime?.state === 'external' ? 'Existing server' : 'Manual'}</dd><dt>Connection</dt><dd>{connected ? 'Connected' : 'Disconnected'}</dd><dt>Sequence</dt><dd>{status?.automation ? 'AUTO armed' : 'Manual / idle'}</dd><dt>Restart policy</dt><dd>Manual recovery</dd></dl><p className="muted">The next clip runs through CasparCG AUTO. Timing and transitions require verification on your output.</p></aside></div>
    <section className="panel rundown"><div className="panel-heading"><div><h2>Sequential rundown <span className="count">{rows.length}</span></h2><p className="muted">{locked ? 'Stop playback to edit the rundown.' : 'Drag to reorder. Cue replaces the current program output.'}</p></div><span className="mono muted">{time(rows.reduce((sum, r) => sum + (r.media.duration_seconds || 0), 0))}</span></div>
      {!rows.length && <div className="empty"><Library size={28}/><h3>Your rundown is empty</h3><p>Index a directory in Settings, then add media from the library.</p><NavLink className="button" to="/library">Open media library</NavLink></div>}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={({active, over}) => {if (!locked && over) order(rows.findIndex(r => r.id === active.id), rows.findIndex(r => r.id === over.id));}}><SortableContext items={rows.map(r => r.id)} strategy={verticalListSortingStrategy}>{rows.map((item, index) => <RundownRow key={item.id} item={item} index={index} total={rows.length} locked={locked} pending={control.isPending || !connected} onRemove={() => edit.mutate({path: `/playlists/main/items/${item.id}`, method: 'DELETE'})} onMove={delta => order(index, index + delta)} onCue={() => control.mutate({action: 'cue', item_id: item.id})}/>)}</SortableContext></DndContext>
    </section><History/>
  </>;
}

function History() {
  const history = useQuery({queryKey: ['history'], queryFn: () => api<{id: string; started_at: string; outcome: string; media_id: string}[]>('/history'), refetchInterval: 10000});
  return <details className="panel history"><summary>As-run history · latest 200 records</summary><ErrorMessage error={history.error}/>{history.data?.length ? history.data.map(r => <div key={r.id}><time>{new Date(r.started_at).toLocaleString()}</time><code>{r.media_id.slice(0, 8)}</code><span>{r.outcome.replaceAll('_', ' ')}</span></div>) : <p className="muted">No observed playback records yet.</p>}</details>;
}

function MediaLibrary() {
  const [search, setSearch] = useState('');
  const [folder, setFolder] = useState('');
  const [selected, setSelected] = useState<Media | null>(null);
  const queryClient = useQueryClient();
  const media = useQuery({queryKey: ['media', search], queryFn: () => api<Media[]>(`/media?q=${encodeURIComponent(search)}&limit=2000`)});
  const all = media.data || [];
  const folders = [...new Set(all.map(m => m.relative_path.includes('/') ? m.relative_path.slice(0, m.relative_path.lastIndexOf('/')) : ''))].sort();
  const filtered = folder ? all.filter(m => m.relative_path.startsWith(folder + '/')) : all;
  const locked = useStore(s => !!s.status?.current);
  const add = useMutation({mutationFn: (media_id: string) => api('/playlists/main/items', 'POST', {media_id}), onSuccess: () => queryClient.invalidateQueries({queryKey: ['playlist']})});
  return <><div className="page-heading"><div><p className="eyebrow">ASSETS</p><h1>Media library</h1></div><NavLink className="button" to="/settings">Configure directories</NavLink></div><ErrorMessage error={media.error || add.error}/>
    <div className="library-tools"><label className="search"><Search size={17}/><input aria-label="Search media" placeholder="Search titles…" value={search} onChange={e => setSearch(e.target.value)}/></label><select aria-label="Filter by folder" value={folder} onChange={e => setFolder(e.target.value)}><option value="">All folders</option>{folders.filter(Boolean).map(f => <option key={f}>{f}</option>)}</select><button onClick={() => void media.refetch()}><RefreshCw size={15}/>Refresh</button></div>
    {add.isSuccess && <p className="success" role="status">Added to rundown.</p>}
    <section className="panel media-table"><div className="media-row table-head"><span>MEDIA / SOURCE PATH</span><span>FORMAT</span><span>DURATION</span><span>ACTION</span></div>{filtered.map(m => <div key={m.id} className="media-row"><button className="media-name" onClick={() => setSelected(m)}><Film size={20}/><div><strong>{m.title}</strong><small>{m.relative_path}</small>{(m.missing || m.error) && <small className="warning">{m.missing ? 'Missing media' : m.error}</small>}</div></button><span>{m.metadata.width ? `${m.metadata.width} × ${m.metadata.height}` : m.kind}<small>{m.metadata.video_codec || m.metadata.audio_codec || 'Unprobed'} {m.metadata.possible_vfr ? '· possible VFR' : ''}</small></span><span className="mono">{time(m.duration_seconds)}</span><button disabled={locked || add.isPending || m.missing || !!m.error || m.kind !== 'video'} onClick={() => add.mutate(m.id)} aria-label={`Add ${m.title} to rundown`}><Plus size={16}/>Add</button></div>)}
    {!filtered.length && <div className="empty"><Library size={28}/><h3>{media.isLoading ? 'Loading library…' : 'No media found'}</h3><p>Add and scan a local directory in Settings. Indexing leaves source files unchanged.</p></div>}</section>
    <p className="muted">Showing up to 2,000 matching assets. Search narrows results. Indexing is read-only.</p>
    {selected && <div className="modal-backdrop" onClick={() => setSelected(null)}><section role="dialog" aria-modal="true" aria-labelledby="asset-title" className="panel modal" onClick={e => e.stopPropagation()}><h2 id="asset-title">{selected.title}</h2><p className="path">{selected.path}</p><pre>{JSON.stringify(selected.metadata, null, 2)}</pre><button autoFocus onClick={() => setSelected(null)}>Close metadata</button></section></div>}
  </>;
}

function SettingsPage() {
  const query = useQuery({queryKey: ['settings'], queryFn: () => api<SettingsResponse>('/settings')});
  return <><div className="page-heading"><div><p className="eyebrow">CONFIGURATION</p><h1>Channel & engine</h1></div></div><ErrorMessage error={query.error}/>{query.data && <SettingsForm initial={query.data}/>}</>;
}

function SettingsForm({initial}: {initial: SettingsResponse}) {
  const [cfg, setCfg] = useState<ChannelSettings>(initial.channel);
  const [directory, setDirectory] = useState('');
  const queryClient = useQueryClient();
  const status = useStore(s => s.status);
  const save = useMutation({mutationFn: () => api('/settings', 'PUT', cfg), onSuccess: () => queryClient.invalidateQueries({queryKey: ['settings']})});
  const scan = useMutation({mutationFn: (directory: string) => api<{indexed: number; unchanged: number; failed: number; missing: number}>('/media/scan', 'POST', {directory}), onSuccess: () => queryClient.invalidateQueries({queryKey: ['media']})});
  const disabled = !!status?.connection_requested || save.isPending || scan.isPending;
  const field = (key: keyof ChannelSettings, label: string, numeric = false) => <label>{label}<input required disabled={disabled} type={numeric ? 'number' : 'text'} value={String(cfg[key])} onChange={e => setCfg({...cfg, [key]: numeric ? Number(e.target.value) : e.target.value})}/></label>;
  return <><ErrorMessage error={save.error || scan.error}/>{save.isSuccess && <p className="success" role="status">Settings saved. Source media was not changed.</p>}{disabled && status?.observation.connected && <p className="warning">Disconnect CasparCG in the control room before editing settings.</p>}
    <form onSubmit={e => {e.preventDefault(); save.mutate();}}><section className="panel settings-panel"><h2>Channel identity & output reference</h2><div className="form-grid">{field('name', 'Channel name')}{field('timezone', 'IANA timezone')}{field('width', 'Width', true)}{field('height', 'Height', true)}{field('fps_num', 'Frame rate numerator', true)}{field('fps_den', 'Frame rate denominator', true)}</div><p className="muted">{initial.settings_apply}</p></section>
      <section className="panel settings-panel"><h2>CasparCG connection</h2><div className="form-grid">{field('host', 'AMCP host')}{field('port', 'AMCP port', true)}{field('channel', 'Server channel', true)}{field('layer', 'Program layer', true)}{field('media_root', 'CasparCG media root')}{field('ffprobe', 'FFprobe executable or full path')}</div><p className="muted">FFprobe: <span className={initial.ffprobe_available ? 'success' : 'warning'}>{initial.ffprobe_available ? 'available' : 'not found'}</span>. Media must be inside the configured CasparCG media root. No automatic transcoding.</p></section>
      <section className="panel settings-panel"><h2>Read-only media directories</h2><p className="muted">Add a path, save settings, then scan it. Scans detect changes and missing files.</p><div className="directory-add"><input disabled={disabled} aria-label="New media directory" placeholder="C:\\CasparCG\\media" value={directory} onChange={e => setDirectory(e.target.value)}/><button type="button" disabled={disabled || !directory.trim()} onClick={() => {setCfg({...cfg, directories: [...new Set([...cfg.directories, directory.trim()])]}); setDirectory('');}}><Plus size={16}/>Add directory</button></div>
      {cfg.directories.map(dir => <div className="directory-row" key={dir}><code>{dir}</code><button type="button" disabled={scan.isPending || save.isPending} onClick={() => scan.mutate(dir)}><RefreshCw size={15}/>{scan.isPending && scan.variables === dir ? 'Scanning…' : 'Scan'}</button><button type="button" className="icon" aria-label={`Remove directory ${dir}`} disabled={disabled} onClick={() => setCfg({...cfg, directories: cfg.directories.filter(d => d !== dir)})}><Trash2 size={16}/></button></div>)}
      {scan.data && <p role="status">Indexed {scan.data.indexed} · unchanged {scan.data.unchanged} · failed {scan.data.failed} · missing {scan.data.missing}</p>}</section><button className="primary" disabled={disabled} type="submit">{save.isPending ? 'Saving…' : 'Save settings'}</button></form>
  </>;
}

function App() {
  const token = useStore(s => s.token);
  const live = useStore(s => s.live);
  if (!token) return <Login/>;
  return <div className="app"><aside className="sidebar">
    <NavLink to="/" className="brand"><Radio size={26}/><span>Open<span className="brand-light">Playout</span><small>BROADCAST AUTOMATION</small></span></NavLink>
    <div className="nav-caption">WORKSPACE</div><nav>
      <NavLink to="/" end><Radio size={18}/>Control room</NavLink>
      <NavLink to="/library"><Library size={18}/>Media library</NavLink>
      <NavLink to="/schedule"><Film size={18}/>Schedule</NavLink>
      <NavLink to="/chapters"><Film size={18}/>Chapters & segments</NavLink>
      <NavLink to="/studio"><Plug size={18}/>Automation studio</NavLink>
      <NavLink to="/settings"><Settings size={18}/>Settings</NavLink>
    </nav>
    <div className="sidebar-bottom"><span className="badge">LOCAL BROADCAST</span><p>Playout, scheduling & automation</p><button className="quiet" onClick={() => {useStore.getState().setToken(''); client.clear();}}><LogOut size={15}/>Lock interface</button></div>
  </aside><div className="workspace"><header className="topbar"><span className="muted">Local control interface</span><span className="connection"><i className={live ? 'online' : ''}/>{live ? 'Live status connected' : 'Status stream offline'}</span></header>
    <main className="content"><Synchronize/><Routes>
      <Route path="/" element={<Dashboard/>}/><Route path="/library" element={<MediaLibrary/>}/>
      <Route path="/schedule" element={<SchedulePage/>}/><Route path="/settings" element={<SettingsPage/>}/>
      <Route path="/chapters" element={<ChaptersPage/>}/><Route path="/studio" element={<StudioPage/>}/>
    </Routes></main><footer>OpenPlayout 0.1 · CasparCG output must be verified independently · Space: pause / resume</footer>
  </div></div>;
}

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={client}><BrowserRouter><App/></BrowserRouter></QueryClientProvider></React.StrictMode>);
