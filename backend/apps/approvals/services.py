from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _
from .models import (
    ApprovalFlow, ApprovalFlowVersion, ApprovalRequest,
    ApprovalStep, ApprovalSigner, ApprovalAction
)

User = get_user_model()


@dataclass
class CreateFlowResult:
    flow: ApprovalFlow
    version: ApprovalFlowVersion


def publish_flow_version(flow: ApprovalFlow, steps_json: List[Dict[str, Any]], published_by: User, notes: str = "") -> ApprovalFlowVersion:
    last_version = (flow.versions.order_by("-version").first().version if flow.versions.exists() else 0)
    with transaction.atomic():
        ver = ApprovalFlowVersion.objects.create(
            flow=flow,
            version=last_version + 1,
            steps_json=steps_json,
            is_active=True,
            published_at=timezone.now(),
            published_by=published_by,
            notes=notes,
        )
        flow.current_version = ver.version
        flow.status = ApprovalFlow.Status.PUBLISHED
        flow.save(update_fields=["current_version", "status"])
        # deactivate previous active versions
        flow.versions.exclude(pk=ver.pk).update(is_active=False)
    return ver


def seed_attendance_correction_flow(admin_unit_id: int, hr_user_id: int, actor: User) -> CreateFlowResult:
    flow, _ = ApprovalFlow.objects.get_or_create(
        flow_key="attendance_correction_approval",
        defaults={
            "name": "Phê duyệt sửa chấm công",
            "description": "Luồng phê duyệt sửa chấm công gồm 2 bước: lãnh đạo đơn vị NSTK và nhân viên HR.",
            "status": ApprovalFlow.Status.DRAFT,
            "admin_unit_id": admin_unit_id,
            "settings_json": {
                "reject_policy": "REJECT_IMMEDIATE",
                "allow_overrides": False,
                "sla": {"enabled": True, "default_days": 2},
                "delegation": {
                    "enabled": True,
                    "rules": {
                        "ROOM_CHAIN": ["HEAD", "DEPUTY", "IN_CHARGE"]
                    }
                }
            },
            "created_by": actor,
        }
    )
    steps_json = [
        {
            "order": 1,
            "type": "DEPT_HEADS_FROM_EMPLOYEE_UNIT",
            "label": "Lãnh đạo đơn vị của NSTK",
            "quorum": "GROUP_ANY_ALL",
            "resolver": {
                "role_chain": ["HEAD", "DEPUTY", "IN_CHARGE"],
                "group_by": "unit",
                "required": True
            },
            "allow_overrides": True,
            "sla_days": 2
        },
        {
            "order": 2,
            "type": "EXPLICIT_USERS",
            "label": "Nhân viên phòng HR (đích danh)",
            "quorum": "ALL",
            "resolver": {
                "user_ids": [hr_user_id],
                "required": True
            },
            "allow_overrides": True,
            "sla_days": 2
        }
    ]
    ver = publish_flow_version(flow, steps_json, actor, notes="Version 1 - 2 bước: Lãnh đạo đơn vị NSTK, HR (đích danh)")
    return CreateFlowResult(flow=flow, version=ver)


def create_request(flow_key: str, requester: User, object_type: str, object_id: str, title: str, unit_id: Optional[int], metadata_json: Dict[str, Any]) -> ApprovalRequest:
    flow = ApprovalFlow.objects.get(flow_key=flow_key)
    ver = flow.versions.get(version=flow.current_version)
    req = ApprovalRequest.objects.create(
        flow=flow,
        flow_version=ver,
        object_type=object_type,
        object_id=object_id,
        title=title,
        unit_id=unit_id,
        requester=requester,
        status=ApprovalRequest.Status.SUBMITTED,
        metadata_json=metadata_json,
        submitted_at=timezone.now(),
    )
    # instantiate steps from steps_json (status=PENDING)
    for step_def in ver.steps_json:
        ApprovalStep.objects.create(
            request=req,
            order_index=step_def["order"],
            type=step_def["type"],
            label=step_def.get("label", ""),
            quorum=step_def.get("quorum", "ALL"),
            resolver_config=step_def.get("resolver", {}),
            allow_overrides=bool(step_def.get("allow_overrides", False)),
            status=ApprovalStep.Status.PENDING,
        )
    return req