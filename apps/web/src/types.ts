export interface Media {
  id: string; title: string; kind: string; path: string; root: string; relative_path: string;
  duration_seconds: number | null; size: number; missing: boolean; error: string | null;
  tags: string[];
  metadata: { fps?: string; width?: number; height?: number; video_codec?: string; audio_codec?: string;
    possible_vfr?: boolean; chapters?: unknown[]; duration?: string };
}
export interface Item { id: string; position: number; media: Media; segment?: {label:string;in_frame:number;out_frame:number;fps_num:number;fps_den:number} | null }
export interface Status {
  engine: string; automation: boolean; error: string | null; connection_requested: boolean;
  observation: { connected: boolean; state: string; clip: string | null; position_seconds: number | null; duration_seconds: number | null; clip_in_seconds?:number;clip_duration_seconds?:number|null };
  recovery_policy?: string;
  current: Item | null; next: Item | null;
  runtime?: {state: string; managed: boolean; pid: number | null; version: string | null; error: string | null};
  scheduler?: {armed_schedule_id: string | null; active_execution_id: string | null; error: string | null;
    next: {label: string; planned_start: string; media: Media} | null; lateness_tolerance_seconds: number};
  scan?: { running: boolean; report: {indexed: number; failed: number; missing: number; unchanged: number} | null; error: string | null };
}
export interface ChannelSettings {
  name: string; timezone: string; width: number; height: number; fps_num: number; fps_den: number;
  host: string; port: number; channel: number; layer: number; media_root: string; ffprobe: string; directories: string[];
}
export interface SettingsResponse {channel: ChannelSettings; ffprobe_available: boolean; settings_apply: string}
