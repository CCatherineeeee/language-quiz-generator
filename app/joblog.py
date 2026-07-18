"""Structured job-lifecycle logging (progress.md worker spec).

One JSON line per job transition, so any job can be traced end to end by
grepping its job_id in the deploy logs:

    JOB_ENQUEUED -> JOB_PICKED_UP -> JOB_DONE
                                  -> JOB_FAILED (retry or dead-letter)
                    JOB_REAPED (stale claim recovered by the reaper)

Lives in its own module so both the producer (services/storage.py) and the
consumer (worker.py) can import it without importing each other.
"""

import json
import logging

logger = logging.getLogger("jobs")


def log_event(event: str, **fields) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str))
