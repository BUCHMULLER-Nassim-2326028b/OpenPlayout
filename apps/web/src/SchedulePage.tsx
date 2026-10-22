import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DndContext, PointerSensor, useDraggable, useSensor, useSensors } from '@dnd-kit/core';
import { CalendarDays, Download, Edit3, Plus, Trash2, Upload } from 'lucide-react';
import { api, time, useStore } from './api';
import type { Media, SettingsResponse } from './types';

interface SourceEvent {
  id: string; media_id: string; label: string; kind: 'hard' | 'soft';
  preferred_start: string; max_delay_seconds: number; user_fields: Record<string, unknown>;
}
interface PlannedEvent extends SourceEvent {
  media: Media; planned_start: string; planned_end: string; duration_seconds: number; delay_seconds: number;
}
interface Execution {
  id: string; event_id: string; status: string; planned_start: string; command_at: string | null;
  observed_at: string | null; error: string | null;
}
interface ScheduleDetail {
  id: string; name: string; timezone: string; valid: boolean; editable: boolean;
  events: PlannedEvent[]; source_events: SourceEvent[]; executions: Execution[];
  errors: {event_id: string; message: string}[]; timing: string;
}

function localValue(value: string | Date, zone: string) {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'}).formatToParts(new Date(value));
  const fields = Object.fromEntries(parts.map(p => [p.type, p.value]));
  return `${fields.year}-${fields.month}-${fields.day}T${fields.hour}:${fields.minute}:${fields.second}`;
}

function clock(value: string | null, zone: string) {
  return value ? new Intl.DateTimeFormat('en-GB', {timeZone: zone, month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short'}).format(new Date(value)) : '—';
}

function TimelineBlock({event, start, span, index, disabled}: {event: PlannedEvent; start: number; span: number; index: number; disabled: boolean}) {
  const drag = useDraggable({id: event.id, disabled});
  const left = (new Date(event.planned_start).getTime() - start) / span * 100;
  const width = event.duration_seconds * 1000 / span * 100;
  return <button ref={drag.setNodeRef} {...drag.attributes} {...drag.listeners} className={`schedule-block ${event.kind}`} disabled={disabled}
    title={`${event.label || event.media.title} · ${time(event.duration_seconds)}`}
    style={{left: `${Math.max(0, left)}%`, width: `${Math.min(width, 100 - Math.max(0, left))}%`, top: `${30 + index % 3 * 38}px`, transform: drag.transform ? `translateX(${drag.transform.x}px)` : undefined}}>
    {event.label || event.media.title}
  </button>;
}

export default function SchedulePage() {
  const queryClient = useQueryClient();
  const scheduler = useStore(s => s.status?.scheduler);
  const settings = useQuery({queryKey: ['settings'], queryFn: () => api<SettingsResponse>('/settings')});
  const schedules = useQuery({queryKey: ['schedules'], queryFn: () => api<{id: string; name: string; timezone: string}[]>('/schedules')});
  const [chosen, setChosen] = useState('');
  const selected = chosen || schedules.data?.[0]?.id || '';
  const detail = useQuery({queryKey: ['schedule', selected], queryFn: () => api<ScheduleDetail>(`/schedules/${selected}`), enabled: !!selected, refetchInterval: 2000});
  const zone = detail.data?.timezone || settings.data?.channel.timezone || 'Europe/Paris';
  const [day, setDay] = useState('');
  const shownDay = day || localValue(new Date(), zone).slice(0, 10);
  const dayWindow = useQuery({queryKey: ['schedule-day', shownDay, zone], queryFn: () => api<{start: string; end: string; seconds: number}>(`/schedules/day?date=${shownDay}&timezone=${encodeURIComponent(zone)}`)});
  const media = useQuery({queryKey: ['media', 'schedule'], queryFn: () => api<Media[]>('/media?limit=2000')});
  const [name, setName] = useState('');
  const [asset, setAsset] = useState('');
  const [kind, setKind] = useState<'hard' | 'soft'>('hard');
  const [localTime, setLocalTime] = useState('');
  const [fold, setFold] = useState('');
  const [delay, setDelay] = useState(300);
  const [label, setLabel] = useState('');
  const [editing, setEditing] = useState<SourceEvent | null>(null);
  const [importText, setImportText] = useState('');
  const [importFormat, setImportFormat] = useState<'json' | 'csv'>('json');
  const [importValid, setImportValid] = useState(false);
  const [notice, setNotice] = useState('');
  const track = useRef<HTMLDivElement>(null);
  const sensors = useSensors(useSensor(PointerSensor, {activationConstraint: {distance: 5}}));
  const refresh = async () => {await queryClient.invalidateQueries({queryKey: ['schedule']}); await queryClient.invalidateQueries({queryKey: ['schedules']}); await queryClient.invalidateQueries({queryKey: ['status']});};
  const mutation = useMutation({mutationFn: async (request: {path: string; method?: string; body?: unknown}) => api<unknown>(request.path, request.method || 'POST', request.body), onSuccess: refresh});
  const create = useMutation({mutationFn: () => api<{id: string}>('/schedules', 'POST', {name, timezone: settings.data?.channel.timezone || zone}), onSuccess: async result => {setChosen(result.id); setName(''); setNotice('Schedule created. Editing never starts playback.'); await refresh();}});
  const save = useMutation({mutationFn: async () => {
    const resolved = await api<{utc: string}>('/schedules/resolve-time', 'POST', {local_time: localTime, timezone: zone, fold: fold === '' ? null : Number(fold)});
    return api(`/schedules/${selected}/events${editing ? `/${editing.id}` : ''}`, editing ? 'PUT' : 'POST', {
      media_id: asset, preferred_start: resolved.utc, kind, label, max_delay_seconds: kind === 'soft' ? delay : 0, user_fields: editing?.user_fields || {},
    });
  }, onSuccess: async () => {setEditing(null); setNotice('Event saved; dry run recalculated.'); await refresh();}});
  const importer = useMutation({mutationFn: (commit: boolean) => api<{id?: string; valid?: boolean; count?: number; errors?: {message: string}[]}>('/schedules/import', 'POST', {format: importFormat, content: importText, name: name || 'Imported schedule', timezone: zone, commit}), onSuccess: async (result, commit) => {
    if (commit && result.id) {setChosen(result.id); setImportValid(false); setNotice('Imported into a new schedule. Existing schedules were preserved.'); await refresh();}
    else {setImportValid(!!result.valid); setNotice(result.valid ? `Valid import: ${result.count} events. Click Import as new schedule to save.` : (result.errors || []).map(e => e.message).join(' '));}
  }});
  const error = detail.error || schedules.error || dayWindow.error || media.error || settings.error || mutation.error || create.error || save.error || importer.error;
  const busy = mutation.isPending || save.isPending || importer.isPending;
  const armed = scheduler?.armed_schedule_id === selected;
  const readonly = !detail.data?.editable || busy;
  const start = dayWindow.data ? new Date(dayWindow.data.start).getTime() : 0;
  const span = (dayWindow.data?.seconds || 86400) * 1000;
  const visible = detail.data?.events.filter(e => new Date(e.planned_start).getTime() < start + span && new Date(e.planned_end).getTime() > start) || [];
  const loadEvent = (event: SourceEvent) => {setEditing(event); setAsset(event.media_id); setKind(event.kind); setLocalTime(localValue(event.preferred_start, zone)); setDelay(event.max_delay_seconds); setLabel(event.label); setFold('');};
  const exportFile = async (format: 'json' | 'csv') => {
    const result = await api<{filename: string; content: string}>(`/schedules/${selected}/export?format=${format}`);
    const url = URL.createObjectURL(new Blob([result.content], {type: format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = result.filename; link.click(); URL.revokeObjectURL(url);
  };
  return <>
    <div className="page-heading"><div><p className="eyebrow">PROGRAMMING</p><h1>Schedule</h1></div><span className="badge">{zone}</span></div>
    {error && <p className="error" role="alert">{error.message}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    {scheduler?.error && <p className="error" role="alert">{scheduler.error}</p>}
    <section className="panel schedule-toolbar"><label>Schedule<select value={selected} onChange={e => {setChosen(e.target.value); setEditing(null); setNotice('');}}><option value="">Select a schedule</option>{schedules.data?.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
      <form onSubmit={e => {e.preventDefault(); create.mutate();}}><label>New schedule name<input required maxLength={120} value={name} onChange={e => setName(e.target.value)}/></label><button disabled={create.isPending}><Plus size={15}/>Create</button></form></section>
    {selected && detail.data && <>
      <section className="panel settings-panel"><div className="panel-heading schedule-heading"><div><h2>{detail.data.name}</h2><p className="muted">{detail.data.timing}</p></div><button className={armed ? '' : 'primary'} disabled={busy || (!armed && (!detail.data.valid || !detail.data.events.length || !!scheduler?.armed_schedule_id))} onClick={() => mutation.mutate({path: `/schedules/${selected}/${armed ? 'disarm' : 'arm'}`})}>{armed ? 'Disarm schedule' : 'Arm schedule'}</button></div>
        <div className="timeline-tools"><label>Local date<input type="date" value={shownDay} onChange={e => setDay(e.target.value)}/></label><span className="muted">{(dayWindow.data?.seconds || 0) / 3600} hour local day · drag blocks in 5-minute steps</span><span className={`badge ${detail.data.valid ? 'green' : ''}`}>{detail.data.valid ? 'DRY RUN VALID' : 'CONFLICTS'}</span></div>
        {detail.data.errors.map((e, i) => <p className="error" key={i}>{e.message}</p>)}
        <DndContext sensors={sensors} onDragEnd={({active, delta}) => {
          const source = detail.data?.source_events.find(e => e.id === active.id);
          if (!source || readonly || !track.current || !delta.x) return;
          const minutes = Math.round(delta.x / track.current.clientWidth * span / 300000) * 5;
          const preferred_start = new Date(new Date(source.preferred_start).getTime() + minutes * 60000).toISOString();
          mutation.mutate({path: `/schedules/${selected}/events/${source.id}`, method: 'PUT', body: {...source, preferred_start}});
        }}><div ref={track} className="schedule-track"><div className="timeline-axis"><span>00:00</span><span>¼ day</span><span>½ day</span><span>¾ day</span><span>Next midnight</span></div>{visible.map((event, index) => <TimelineBlock key={event.id} event={event} start={start} span={span} index={index} disabled={readonly}/>)}</div></DndContext>
        <p className="muted">Red: fixed time · Blue: movable within its delay window. Empty intervals have no automatic filler. Use the event editor for exact times.</p>
      </section>
      <section className="panel settings-panel"><h2>{editing ? 'Edit event' : 'Add event'}</h2>{!detail.data.editable && <p className="warning">This schedule has execution records and is read-only. Export and import a new copy to revise it.</p>}
        <form onSubmit={e => {e.preventDefault(); save.mutate();}}><div className="form-grid">
          <label>Media<select aria-label="Media" required disabled={readonly} value={asset} onChange={e => setAsset(e.target.value)}><option value="">Choose indexed video</option>{media.data?.filter(m => m.kind === 'video' && !m.missing && !m.error).map(m => <option key={m.id} value={m.id}>{m.title} · {time(m.duration_seconds)}</option>)}</select></label>
          <label>Event label<input disabled={readonly} value={label} onChange={e => setLabel(e.target.value)}/></label>
          <label>Local start time<input required disabled={readonly} type="datetime-local" step="1" value={localTime} onChange={e => setLocalTime(e.target.value)}/></label>
          <label>Time constraint<select aria-label="Time constraint" disabled={readonly} value={kind} onChange={e => setKind(e.target.value as 'hard' | 'soft')}><option value="hard">Hard · fixed time</option><option value="soft">Soft · may move later</option></select></label>
          <label>DST occurrence<select disabled={readonly} value={fold} onChange={e => setFold(e.target.value)}><option value="">Require an unambiguous time</option><option value="0">First occurrence if clock repeats</option><option value="1">Second occurrence if clock repeats</option></select></label>
          {kind === 'soft' && <label>Maximum delay (seconds)<input disabled={readonly} type="number" min="0" max="604800" value={delay} onChange={e => setDelay(Number(e.target.value))}/></label>}
        </div><div className="schedule-actions"><button className="primary" disabled={readonly || !asset}>{editing ? 'Save event' : 'Add event'}</button>{editing && <button type="button" onClick={() => setEditing(null)}>Cancel edit</button>}</div></form>
      </section>
      <section className="panel schedule-events"><div className="panel-heading"><h2>Dry-run event list</h2><div className="schedule-actions"><button onClick={() => {void exportFile('json').catch(e => setNotice(String(e)));}}><Download size={14}/>JSON</button><button onClick={() => {void exportFile('csv').catch(e => setNotice(String(e)));}}><Download size={14}/>CSV</button></div></div>
        {!detail.data.source_events.length && <div className="empty"><CalendarDays/><p>Add media to build a timed plan.</p></div>}
        {detail.data.source_events.map(source => {const planned = detail.data.events.find(e => e.id === source.id); return <div className="schedule-event-row" key={source.id}><span className={`badge ${source.kind}`}>{source.kind}</span><div><strong>{source.label || planned?.media.title || media.data?.find(m => m.id === source.media_id)?.title}</strong><small>Requested {clock(source.preferred_start, zone)}</small><small>{planned ? `Planned ${clock(planned.planned_start, zone)} → ${clock(planned.planned_end, zone)} · ${time(planned.duration_seconds)}` : 'Not placed — resolve conflict'}</small>{!!planned?.delay_seconds && <small className="warning">Moved later by {planned.delay_seconds} seconds</small>}</div><button className="icon" disabled={readonly} aria-label="Edit event" onClick={() => loadEvent(source)}><Edit3 size={16}/></button><button className="icon danger" disabled={readonly} aria-label="Delete event" onClick={() => mutation.mutate({path: `/schedules/${selected}/events/${source.id}`, method: 'DELETE'})}><Trash2 size={16}/></button></div>;})}
      </section>
      {!!detail.data.executions.length && <section className="panel settings-panel"><h2>Execution ledger</h2>{detail.data.executions.map(run => <div className="execution-row" key={run.id}><strong>{run.status}</strong><span>{clock(run.planned_start, zone)}</span><small>Command: {clock(run.command_at, zone)} · Observed: {clock(run.observed_at, zone)}</small>{run.error && <p className="warning">{run.error}</p>}</div>)}</section>}
    </>}
    <details className="panel settings-panel"><summary><Upload size={15}/> Import a schedule</summary><p className="muted">Paste version 1 JSON, or CSV with media_id and preferred_start (UTC offset required). Unknown CSV columns become custom fields. Import always creates a new schedule.</p><label>Format<select value={importFormat} onChange={e => {setImportFormat(e.target.value as 'json' | 'csv'); setImportValid(false);}}><option value="json">JSON</option><option value="csv">CSV</option></select></label><label>Import content<textarea rows={7} value={importText} onChange={e => {setImportText(e.target.value); setImportValid(false);}}/></label><div className="schedule-actions"><button disabled={!importText || busy} onClick={() => importer.mutate(false)}>Validate import</button><button className="primary" disabled={!importValid || busy} onClick={() => importer.mutate(true)}>Import as new schedule</button></div></details>
  </>;
}
