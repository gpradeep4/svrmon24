"""Aggregate ITSM API router under ``/api/itsm``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...auth import require_user
from . import (
    activities,
    approvals,
    assignment_groups,
    attachments,
    changes,
    dashboard,
    incidents,
    jobs,
    knowledge,
    notifications,
    problems,
    reports,
    sla,
    workflows,
)

router = APIRouter(
    prefix="/api/itsm",
    tags=["itsm"],
    dependencies=[Depends(require_user)],
)

# Register static prefixes before the polymorphic /{ticket_type}/... activity routes.
router.include_router(incidents.router)
router.include_router(changes.router)
router.include_router(problems.router)
router.include_router(approvals.router)
router.include_router(workflows.router)
router.include_router(sla.router)
router.include_router(knowledge.router)
router.include_router(notifications.router)
router.include_router(jobs.router)
router.include_router(dashboard.router)
router.include_router(reports.router)
router.include_router(assignment_groups.router)
router.include_router(attachments.router)
router.include_router(activities.router)
