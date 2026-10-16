"""Durable reviews, hourly cleanup and cron-style memory maintenance.
Lifecycle originally adapted from OpenPoke (MIT).
Copyright (c) 2025 OpenPoke Contributors. See third_party/openpoke/LICENSE.
"""
import asyncio
import logging
import time
from uuid import uuid4

from loke_contracts.memory import ConflictError

logger = logging.getLogger(__name__)


class ReviewScheduler:
    def __init__(self, coordinator, memory, interval=30, maintenance_interval=900):
        if not 1 <= interval <= 3600 or not 1 <= maintenance_interval <= 86400:
            raise ValueError("Scheduler intervals are outside supported bounds.")
        self.coordinator, self.memory, self.interval = coordinator, memory, interval
        self.maintenance_interval = maintenance_interval
        self.owner = str(uuid4())
        self.next_cleanup = self.next_maintenance = 0
        self.task = None

    async def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self.run(), name="loke-review-scheduler")

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    def cycle(self):
        now = time.monotonic()
        if now >= self.next_cleanup:
            self.coordinator.expire()
            self.next_cleanup = now + 3600
        maintenance_due = now >= self.next_maintenance
        for learner_id in self.memory.learner_ids():
            try:
                self.coordinator.tick(learner_id)
                if maintenance_due:
                    snapshot = self.memory.snapshot(learner_id)
                    if snapshot["storage_consent"]:
                        bucket = int(time.time() // self.maintenance_interval)
                        self.memory.enqueue_job(learner_id, snapshot["generation_id"],
                            f"memory:{bucket}", "memory", {})
            except ConflictError:
                # Another worker or reset superseded this captured generation; next tick reloads.
                continue
        if maintenance_due:
            self.next_maintenance = now + self.maintenance_interval
        for lease in self.memory.claim_jobs(self.owner, ["memory"], limit=10, lease_seconds=300):
            try:
                self.memory.maintain_memory(lease.learner_id, lease.generation_id)
                self.memory.finish_job(lease)
            except ConflictError:
                # Reset/lease replacement invalidates this job; it must not recreate records.
                continue
            except Exception:
                logger.warning("Memory maintenance failed; bounded retry is scheduled.")
                try:
                    self.memory.finish_job(lease, success=False)
                except ConflictError:
                    continue

    async def run(self):
        while True:
            work = asyncio.create_task(asyncio.to_thread(self.cycle))
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                # Finish the bounded in-flight transaction before the app disposes its engine.
                await work
                raise
            except Exception:
                logger.warning("Review cycle failed; durable work will be retried.")
            await asyncio.sleep(self.interval)
