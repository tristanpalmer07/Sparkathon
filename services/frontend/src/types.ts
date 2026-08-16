export type EventStatus = "new" | "acknowledged" | "dismissed";

export interface EventItem {
  event_id: string;
  camera_id: string;
  start_time: string;
  end_time: string;
  track_ids: number[] | null;
  trigger_type: string | null;
  trigger_confidence: number | null;
  vlm_summary: string | null;
  priority: string | null;
  category: string | null;
  nemotron_reason: string | null;
  worker_summary: string | null;
  clip_reference: string | null;
  status: EventStatus;
  created_at: string;
}

export interface StatsRow {
  priority: string | null;
  status: string;
  count: number;
}

export interface StatsResponse {
  by_priority_status: StatsRow[];
}

export type VideoSource = "library" | "upload";
export type JobStatus = "queued" | "transcoding" | "ingesting" | "succeeded" | "failed";

export interface VideoEntry {
  video_id: string;
  filename: string;
  source: VideoSource;
  size_bytes: number;
  suggested_camera_id: string;
  last_job_id: string | null;
  last_status: JobStatus | null;
  last_camera_id: string | null;
}

export interface Job {
  job_id: string;
  video_id: string;
  filename: string;
  camera_id: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  log: string[];
  error: string | null;
}
