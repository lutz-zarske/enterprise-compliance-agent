"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { JobSnapshot } from "../types/api";

/** Abfragetakt: laufende Jobs alle 1,2 s, sonst alle 8 s; ohne Backend wird nicht gefragt. */
const ACTIVE_POLL_MS = 1200;
const IDLE_POLL_MS = 8000;

/**
 * Warteschlange der Analyse-Jobs für Kopfzeile und Arbeitsbereich.
 *
 * Meldet jeden Job genau einmal über ``onFinished``, sobald er die Warteschlange
 * verlässt (fertig, abgebrochen oder fehlgeschlagen) - die Seite lädt dann
 * Liste, Kennzahlen und den geöffneten Beleg neu.  Keep-Alive: Der Hook lebt in
 * der Seite, ein Ansichtswechsel bricht nichts ab.
 */
export function useJobs(online: boolean, onFinished: (job: JobSnapshot) => void) {
  const [jobs, setJobs] = useState<JobSnapshot[]>([]);
  const known = useRef(new Map<string, JobSnapshot>());
  const reported = useRef(new Set<string>());
  const finishedRef = useRef(onFinished);
  finishedRef.current = onFinished;
  const [nonce, setNonce] = useState(0);

  const report = useCallback((job: JobSnapshot) => {
    if (reported.current.has(job.job_id)) return;
    reported.current.add(job.job_id);
    finishedRef.current(job);
  }, []);

  useEffect(() => {
    if (!online) {
      setJobs([]);
      return;
    }
    let stop = false;
    let timer: number | undefined;
    const tick = async () => {
      let active = false;
      try {
        const response = await api.jobs(true);
        if (stop) return;
        const open = response.jobs;
        active = open.length > 0;
        const openIds = new Set(open.map((job) => job.job_id));
        // Verschwundene Jobs: Endstand holen und genau einmal melden (erst nach Erfolg aus known streichen).
        for (const [jobId] of Array.from(known.current.entries())) {
          if (openIds.has(jobId)) continue;
          const final = await api.job(jobId).catch(() => null);
          if (stop) return;
          known.current.delete(jobId);
          if (final) report(final);
        }
        open.forEach((job) => known.current.set(job.job_id, job));
        setJobs(open);
      } catch {
        /* Backend kurz weg - der Offline-Hinweis zeigt das bereits */
      }
      if (!stop) timer = window.setTimeout(() => void tick(), active ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    };
    void tick();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [online, nonce, report]);

  /** Gerade angenommenen Job sofort zeigen und den Takt beschleunigen. */
  const track = useCallback((job: JobSnapshot) => {
    if (job.status === "done" || job.status === "failed" || job.status === "cancelled") {
      report(job);
      return;
    }
    known.current.set(job.job_id, job);
    setJobs((all) => (all.some((item) => item.job_id === job.job_id) ? all : [...all, job]));
    setNonce((n) => n + 1);
  }, [report]);

  const cancel = useCallback(async (jobId: string) => {
    try {
      await api.cancelJob(jobId);
    } catch {
      /* Job kann im selben Moment bereits beendet worden sein */
    } finally {
      setNonce((n) => n + 1);
    }
  }, []);

  return { jobs, track, cancel };
}
