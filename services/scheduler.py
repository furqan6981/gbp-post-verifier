import logging

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from database.repositories import ClientRepository
from services.workflow import VerificationWorkflow


logger = logging.getLogger(__name__)


class ClientScheduler:
    def __init__(
        self,
        clients: ClientRepository,
        workflow: VerificationWorkflow,
    ):
        self.clients = clients
        self.workflow = workflow
        self.scheduler: BlockingScheduler | None = None

    def configure(self) -> int:
        active_clients = self.clients.list_active()
        self.scheduler = BlockingScheduler(
            executors={
                "default": ThreadPoolExecutor(
                    max_workers=max(10, len(active_clients))
                )
            },
            job_defaults={"coalesce": True, "max_instances": 1},
        )
        for client in active_clients:
            if client.id is None:
                continue
            trigger = CronTrigger(
                hour=client.check_time.hour,
                minute=client.check_time.minute,
                timezone=client.timezone,
            )
            self.scheduler.add_job(
                self.workflow.run_client,
                trigger=trigger,
                args=[client],
                id=f"client-{client.id}",
                name=f"Verify GBP: {client.business_name}",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info(
                "Scheduled client %s at %s (%s)",
                client.client_name,
                client.check_time.strftime("%H:%M"),
                client.timezone,
                extra={"client_id": client.id, "event": "client_scheduled"},
            )
        return len(active_clients)

    def run(self) -> None:
        count = self.configure()
        logger.info(
            "Scheduler started with %s active client(s)",
            count,
            extra={"event": "scheduler_started"},
        )
        if self.scheduler is None:
            raise RuntimeError("Scheduler was not configured")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped", extra={"event": "scheduler_stopped"})
