import { useState } from "react";
import type { Job } from "../types";
import { formatDateTime, jobStatusClass } from "../format";

export default function JobsPanel({ jobs }: { jobs: Job[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (jobs.length === 0) return null;

  return (
    <section className="jobs-section">
      <h2>Ingest jobs</h2>
      <p className="muted">Newest first. Click a job to see its log.</p>
      <ul className="job-list">
        {jobs.map((job) => {
          const isOpen = expanded === job.job_id;
          return (
            <li key={job.job_id} className="job-item">
              <button className="job-summary" onClick={() => setExpanded(isOpen ? null : job.job_id)}>
                <span className={jobStatusClass(job.status)}>{job.status}</span>
                <span className="mono job-filename">{job.filename}</span>
                <span className="muted">camera={job.camera_id}</span>
                <span className="muted job-time">{formatDateTime(job.created_at)}</span>
                <span className="disclosure">{isOpen ? "▾" : "▸"}</span>
              </button>
              {isOpen && (
                <div className="job-log">
                  {job.error && <div className="alert alert-error">{job.error}</div>}
                  <pre>{job.log.join("\n") || "(no output yet)"}</pre>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
