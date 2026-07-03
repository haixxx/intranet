from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from .models import (
    ApprovalFlow, ApprovalFlowVersion, ApprovalRequest,
    ApprovalStep, ApprovalSigner, ApprovalAction
)
from .content_registry import render_for_object

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
        flow.versions.exclude(pk=ver.pk).update(is_active=False)
    return ver

def create_request(flow_key: str, requester: User, object_type: str, object_id: str, title: str, unit_id: Optional[int], metadata_json: Dict[str, Any]) -> ApprovalRequest:
    flow = ApprovalFlow.objects.get(flow_key=flow_key)
    if flow.status != ApprovalFlow.Status.PUBLISHED:
        raise ValidationError("Luồng phê duyệt chưa được công bố, không thể tạo yêu cầu.")
    if not flow.current_version:
        raise ValidationError("Luồng phê duyệt chưa có phiên bản hiện hành.")

    ver = flow.versions.filter(version=flow.current_version, is_active=True).first()
    if not ver:
        raise ValidationError("Phiên bản hiện hành của luồng không tồn tại hoặc chưa active.")
    if not ver.steps_json:
        raise ValidationError("Phiên bản hiện hành chưa có cấu hình bước phê duyệt.")

    # Kiểm tra đơn vị được phép tạo yêu cầu
    settings = flow.settings_json or {}
    allowed_units = settings.get("request_units") or []
    if allowed_units and unit_id and int(unit_id) not in [int(x) for x in allowed_units]:
        raise ValueError("Đơn vị hiện tại không được phép tạo yêu cầu theo luồng này.")

    # Chuẩn bị payload_changes để render snapshot nội dung (tuỳ object_type).
    # Với attendance_correction, ưu tiên payload_json thật của ACR để không mất NOTE/ADD/REMOVE.
    # metadata.payload_changes chỉ là dữ liệu tóm tắt phục vụ thống kê, không được ghi đè payload thật.
    payload_changes: List[Dict[str, Any]] = []
    try:
        if object_type == "attendance_correction":
            from apps.attendance.models_batch import AttendanceCorrectionRequest
            acr = AttendanceCorrectionRequest.objects.filter(id=int(object_id)).first()
            if acr and isinstance(acr.payload_json, list):
                payload_changes = [x for x in acr.payload_json if isinstance(x, dict)]
        if not payload_changes and metadata_json and isinstance(metadata_json, dict) and metadata_json.get("payload_changes"):
            payload_changes = [x for x in (metadata_json.get("payload_changes") or []) if isinstance(x, dict)]
    except Exception:
        payload_changes = payload_changes or []

    content_html, content_json, content_schema_version = render_for_object(object_type, payload_changes, metadata_json or {})

    with transaction.atomic():
        req = ApprovalRequest.objects.create(
            flow=flow,
            flow_version=ver,
            object_type=object_type,
            object_id=object_id,
            title=title,
            unit_id=unit_id,
            requester=requester,
            status=ApprovalRequest.Status.SUBMITTED,
            metadata_json=metadata_json or {},
            submitted_at=timezone.now(),
            content_html=content_html,
            content_json=content_json,
            content_schema_version=content_schema_version,
        )
        for step_def in ver.steps_json:
            if not isinstance(step_def, dict) or not step_def.get("order") or not step_def.get("type"):
                raise ValidationError("Cấu hình bước phê duyệt không hợp lệ.")
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
        ApprovalAction.objects.create(
            request=req, step=None, signer=None, actor=requester,
            action=ApprovalAction.Action.SUBMIT, comment="", meta_json={}
        )
    return req


def seed_attendance_correction_flow(admin_unit_id: int, hr_user_id: int, actor: User) -> CreateFlowResult:
    """
    Seed luồng mặc định cho Phiếu đề nghị sửa chấm công.
    Bước 1: lãnh đạo đơn vị của phiếu ký ANY.
    Bước 2: HR ký đích danh.
    Có thể chạy lại nhiều lần: tạo version mới và publish version đó.
    """
    flow, _ = ApprovalFlow.objects.get_or_create(
        flow_key="attendance_correction_approval",
        defaults={
            "name": "Phê duyệt sửa chấm công",
            "description": "Luồng mặc định: lãnh đạo đơn vị duyệt, sau đó HR xác nhận.",
            "admin_unit_id": admin_unit_id,
            "created_by": actor,
            "settings_json": {},
        },
    )
    changed_fields = []
    if flow.name != "Phê duyệt sửa chấm công":
        flow.name = "Phê duyệt sửa chấm công"
        changed_fields.append("name")
    if flow.admin_unit_id != admin_unit_id:
        flow.admin_unit_id = admin_unit_id
        changed_fields.append("admin_unit_id")
    if changed_fields:
        flow.save(update_fields=changed_fields)

    steps_json = [
        {
            "order": 1,
            "type": "UNIT_LEADERS",
            "label": "Lãnh đạo đơn vị",
            "quorum": "ANY",
            "resolver": {"use_requester_unit": True, "unit_ids": [], "exclude_requester": True},
            "allow_overrides": False,
        },
        {
            "order": 2,
            "type": "EXPLICIT_USERS",
            "label": "HR xác nhận",
            "quorum": "ALL",
            "resolver": {"user_ids": [int(hr_user_id)]},
            "allow_overrides": False,
        },
    ]
    version = publish_flow_version(flow=flow, steps_json=steps_json, published_by=actor, notes="Seed mặc định sửa chấm công")
    return CreateFlowResult(flow=flow, version=version)
