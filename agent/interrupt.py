"""Interrupt handler. Phase 1: simple polling + Ctrl+C.

Phase 2 will add: interrupt vector table, priority queue, signal mask.
"""

import asyncio
import signal
from typing import Optional

import structlog

from .errors import InterruptSignal

logger = structlog.get_logger()


class InterruptHandler:
    """Simple polling interrupt handler. 类比: polling interrupt controller.

    Phase 1: catches SIGINT (Ctrl+C) and allows the event loop
    to check for pending interrupts between steps.
    """

    def __init__(self):
        self._interrupted = False
        self._paused = False
        self._original_sigint = None

    def setup(self) -> None:
        """Register signal handlers."""
        self._original_sigint = signal.signal(signal.SIGINT, self._on_sigint)
        logger.info("interrupt_handler_setup", mode="polling")

    def teardown(self) -> None:
        """Restore original signal handlers."""
        if self._original_sigint:
            signal.signal(signal.SIGINT, self._original_sigint)

    def _on_sigint(self, signum, frame) -> None:
        """Handle Ctrl+C."""
        logger.info("sigint_received", message="User interrupt detected")
        self._interrupted = True
        # Restore default handler so double Ctrl+C works
        if self._original_sigint:
            signal.signal(signal.SIGINT, self._original_sigint)

    async def check(self) -> None:
        """Check if an interrupt was requested. Call between steps.

        Raises InterruptSignal if interrupted.
        """
        if self._interrupted:
            self._interrupted = False
            raise InterruptSignal("Interrupted by user (Ctrl+C)")

    def request_pause(self) -> None:
        """Request a pause. Not yet implemented in phase 1."""
        self._paused = True
        logger.info("pause_requested")

    def request_resume(self) -> None:
        """Resume from pause."""
        self._paused = False
        logger.info("resume_requested")

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def is_interrupted(self) -> bool:
        return self._interrupted
