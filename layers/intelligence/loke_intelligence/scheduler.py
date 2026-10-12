"""Lifecycle adapted from OpenPoke trigger_scheduler.py (MIT).
Copyright (c) 2025 OpenPoke Contributors. See third_party/openpoke/LICENSE.
Changes: one durable review policy callback, no agent-spawning or email dispatch.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class ReviewScheduler:
    def __init__(self, coordinator, memory, interval: float = 30):
        self.coordinator, self.memory, self.interval = coordinator, memory, interval
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

    async def run(self):
        while True:
            try:
                self.coordinator.expire()
                for learner_id in self.memory.learner_ids():
                    self.coordinator.tick(learner_id)
            except Exception:
                # Do not log exception text that may include learner/provider payloads.
                logger.warning("Review tick failed; durable jobs will be retried.")
            await asyncio.sleep(self.interval)
