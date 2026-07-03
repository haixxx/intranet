from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction


@dataclass(frozen=True)
class PermSpec:
    app_label: str
    model: str
    actions: tuple[str, ...]


VIEW = ("view",)
ADD = ("add",)
CHANGE = ("change",)
DELETE = ("delete",)
VIEW_ADD = ("view", "add")
VIEW_CHANGE = ("view", "change")
VIEW_ADD_CHANGE = ("view", "add", "change")
CRUD = ("view", "add", "change", "delete")


def p(app_label: str, model: str, actions: Iterable[str]) -> PermSpec:
    return PermSpec(app_label=app_label, model=model, actions=tuple(actions))


# -----------------------------------------------------------------------------
# Group chuẩn vận hành
# -----------------------------------------------------------------------------
# Quy ước:
# - Group/Permission: user được làm gì.
# - AccessControl: user được xem/thao tác trong phạm vi đơn vị nào.
# - Superuser vẫn là quyền cao nhất, không thay bằng group nghiệp vụ.
#
# Command này idempotent: chạy nhiều lần được. Mặc định sẽ đồng bộ group theo đúng
# ma trận dưới đây. Nếu muốn giữ thêm quyền đã gán thủ công, dùng --keep-extra.
# -----------------------------------------------------------------------------

GROUP_DEFINITIONS: dict[str, dict] = {
    "EMPLOYEE": {
        "label": "Nhân viên",
        "description": "Nhân viên thông thường. Giai đoạn hiện tại chưa cấp quyền backoffice rộng.",
        "permissions": [],
    },

    "UNIT_STATISTICIAN": {
        "label": "Nhân viên thống kê",
        "description": "Lập/chốt công, xem nhân sự cơ bản và xử lý chấm công trong phạm vi đơn vị.",
        "permissions": [
            # Nhân sự / tổ chức cơ bản
            p("hr", "employee", VIEW),
            p("hr", "tempassignment", VIEW),
            p("organization", "orgunit", VIEW),
            p("organization", "jobtitle", VIEW),
            p("organization", "shifttemplate", VIEW),

            # Quản lý công
            p("attendance", "attendancecode", VIEW),
            p("attendance", "attendancesettings", VIEW),
            p("attendance", "attendancebatch", VIEW_ADD_CHANGE),
            p("attendance", "attendancebatchitem", VIEW_ADD_CHANGE),
            p("attendance", "attendancecommit", VIEW_ADD),
            p("attendance", "attendancecommititem", VIEW),
            p("attendance", "attendancecorrectionrequest", VIEW_ADD),
            p("attendance", "attendanceregistration", VIEW_ADD_CHANGE),

            # Phê duyệt: xem phiếu liên quan / phiếu mình gửi / phiếu trong phạm vi
            p("approvals", "approvalrequest", VIEW),
            p("approvals", "approvalstep", VIEW),
            p("approvals", "approvalsigner", VIEW),
            p("approvals", "approvalaction", VIEW),

            # Quản lý chấm công V2: xem đối chiếu, thêm dữ liệu bổ sung khi được phân công
            p("attendance_devices_v2", "attendancedevicemasterlistv2", VIEW),
            p("attendance_devices_v2", "attendancemanualpunch", VIEW_ADD),
            p("attendance_devices_v2", "attendancedailydeviceauditv2", VIEW),
            p("attendance_devices_v2", "attendancenormalizedpunchv2", VIEW),
            p("attendance_devices_v2", "attendancepunchmatchv2", VIEW),
        ],
    },

    "UNIT_COMMANDER": {
        "label": "Chỉ huy đơn vị",
        "description": "Xem tình hình đơn vị, công, chấm công và tham gia xác nhận/phê duyệt theo luồng nếu là signer.",
        "permissions": [
            p("hr", "employee", VIEW),
            p("hr", "tempassignment", VIEW),
            p("organization", "orgunit", VIEW),
            p("organization", "jobtitle", VIEW),
            p("organization", "shifttemplate", VIEW),

            p("attendance", "attendancecode", VIEW),
            p("attendance", "attendancebatch", VIEW),
            p("attendance", "attendancebatchitem", VIEW),
            p("attendance", "attendancecommit", VIEW),
            p("attendance", "attendancecommititem", VIEW),
            p("attendance", "attendancecorrectionrequest", VIEW),
            p("attendance", "attendanceregistration", VIEW),

            p("approvals", "approvalrequest", VIEW),
            p("approvals", "approvalstep", VIEW),
            p("approvals", "approvalsigner", VIEW),
            p("approvals", "approvalaction", VIEW),

            p("attendance_devices_v2", "attendancedevicemasterlistv2", VIEW),
            p("attendance_devices_v2", "attendancedailydeviceauditv2", VIEW),
        ],
    },

    "DIRECTOR": {
        "label": "Giám đốc",
        "description": "Xem tổng quan/toàn cảnh theo phạm vi AccessControl, không mặc định cấp quyền sửa dữ liệu nghiệp vụ.",
        "permissions": [
            p("hr", "employee", VIEW),
            p("hr", "tempassignment", VIEW),
            p("organization", "orgunit", VIEW),
            p("organization", "jobtitle", VIEW),
            p("organization", "shifttemplate", VIEW),

            p("attendance", "attendancecode", VIEW),
            p("attendance", "attendancesettings", VIEW),
            p("attendance", "attendancebatch", VIEW),
            p("attendance", "attendancebatchitem", VIEW),
            p("attendance", "attendancecommit", VIEW),
            p("attendance", "attendancecommititem", VIEW),
            p("attendance", "attendancecorrectionrequest", VIEW),
            p("attendance", "attendanceregistration", VIEW),

            p("approvals", "approvalrequest", VIEW),
            p("approvals", "approvalstep", VIEW),
            p("approvals", "approvalsigner", VIEW),
            p("approvals", "approvalaction", VIEW),

            p("attendance_devices_v2", "attendancedevicev2", VIEW),
            p("attendance_devices_v2", "attendancedevicestatusreportv2", VIEW),
            p("attendance_devices_v2", "attendancedevicebackfillreportv2", VIEW),
            p("attendance_devices_v2", "attendancedevicemasterlistv2", VIEW),
            p("attendance_devices_v2", "attendancedailydeviceauditv2", VIEW),
            p("attendance_devices_v2", "attendanceingestlogv2", VIEW),
        ],
    },

    "HR_MANAGER": {
        "label": "Quản lý nhân sự",
        "description": "Quản lý nhân sự, tổ chức, điều động và theo dõi công/chấm công trong phạm vi được cấp.",
        "permissions": [
            # Nhân sự / tổ chức
            p("hr", "employee", CRUD),
            p("hr", "tempassignment", CRUD),
            p("hr", "accesscontrol", VIEW),
            p("organization", "orgunit", CRUD),
            p("organization", "jobtitle", CRUD),
            p("organization", "shifttemplate", CRUD),

            # Quản lý công
            p("attendance", "attendancecode", VIEW_ADD_CHANGE),
            p("attendance", "attendancesettings", VIEW_CHANGE),
            p("attendance", "attendancebatch", VIEW_ADD_CHANGE),
            p("attendance", "attendancebatchitem", VIEW_ADD_CHANGE),
            p("attendance", "attendancecommit", VIEW_ADD_CHANGE),
            p("attendance", "attendancecommititem", VIEW_CHANGE),
            p("attendance", "attendancecorrectionrequest", VIEW_ADD_CHANGE),
            p("attendance", "attendanceregistration", VIEW_ADD_CHANGE),

            # Phê duyệt
            p("approvals", "approvalrequest", VIEW_CHANGE),
            p("approvals", "approvalstep", VIEW),
            p("approvals", "approvalsigner", VIEW),
            p("approvals", "approvalaction", VIEW),

            # Chấm công V2: xem/đối chiếu, thêm dữ liệu bổ sung; không mặc định cấu hình thiết bị
            p("attendance_devices_v2", "attendancedevicemasterlistv2", VIEW_CHANGE),
            p("attendance_devices_v2", "attendancemanualpunch", VIEW_ADD_CHANGE),
            p("attendance_devices_v2", "attendancedailydeviceauditv2", VIEW),
            p("attendance_devices_v2", "attendancenormalizedpunchv2", VIEW),
            p("attendance_devices_v2", "attendancepunchmatchv2", VIEW),
            p("attendance_devices_v2", "attendancerawpunchv2", VIEW),
            p("attendance_devices_v2", "attendancedevicev2", VIEW),
            p("attendance_devices_v2", "attendancedevicestatusreportv2", VIEW),
            p("attendance_devices_v2", "attendanceingestlogv2", VIEW),
        ],
    },

    "ATTENDANCE_DEVICE_OPERATOR": {
        "label": "Quản lý chấm công",
        "description": "Vận hành dữ liệu vân tay/thiết bị/đối chiếu chấm công trong phạm vi được cấp.",
        "permissions": [
            p("hr", "employee", VIEW),
            p("hr", "tempassignment", VIEW),
            p("organization", "orgunit", VIEW),
            p("organization", "jobtitle", VIEW),

            p("attendance", "attendancecode", VIEW),
            p("attendance", "attendancecommit", VIEW),
            p("attendance", "attendancecommititem", VIEW),
            p("attendance", "attendancebatch", VIEW),
            p("attendance", "attendancebatchitem", VIEW),

            p("attendance_devices_v2", "attendancedeviceagentv2", VIEW),
            p("attendance_devices_v2", "attendancedeviceapikeyv2", VIEW),
            p("attendance_devices_v2", "attendancedevicev2", VIEW_CHANGE),
            p("attendance_devices_v2", "attendanceingestlogv2", VIEW),
            p("attendance_devices_v2", "attendancerawpunchv2", VIEW),
            p("attendance_devices_v2", "attendancenormalizedpunchv2", VIEW),
            p("attendance_devices_v2", "attendancepunchmatchv2", VIEW),
            p("attendance_devices_v2", "attendancedevicestatusreportv2", VIEW),
            p("attendance_devices_v2", "attendancedevicebackfillreportv2", VIEW),
            p("attendance_devices_v2", "attendancedailydeviceauditv2", VIEW),
            p("attendance_devices_v2", "attendancemanualpunch", VIEW_ADD_CHANGE),
            p("attendance_devices_v2", "attendancedevicemasterlistv2", VIEW_CHANGE),
        ],
    },

    "SYSTEM_ADMIN": {
        "label": "Quản trị hệ thống",
        "description": "Quản trị user/group/permission/AccessControl/cấu hình nền. Không thay thế superuser.",
        "permissions": [
            p("core", "user", CRUD),
            p("auth", "group", CRUD),
            p("auth", "permission", VIEW),
            p("core", "appsetting", CRUD),
            p("hr", "accesscontrol", CRUD),
            p("audit", "auditlog", VIEW),

            p("approvals", "approvalflow", CRUD),
            p("approvals", "approvalflowversion", CRUD),
            p("approvals", "roletitlemapping", CRUD),
        ],
    },

    "HR_SENSITIVE_VIEWER": {
        "label": "Xem dữ liệu nhạy cảm nhân sự",
        "description": "Nhóm phụ: cho phép xem trường nhạy cảm nhân sự theo phạm vi AccessControl.",
        "permissions": [p("hr", "employee", VIEW)],
    },

    "HR_SENSITIVE_EXPORTER": {
        "label": "Xuất dữ liệu nhạy cảm nhân sự",
        "description": "Nhóm phụ: cho phép xuất Excel có trường nhạy cảm theo phạm vi AccessControl.",
        "permissions": [p("hr", "employee", VIEW)],
    },
}


# Nhóm cũ giữ để tương thích với code/dữ liệu cũ. Command sẽ tạo và gán quyền tương ứng.
LEGACY_GROUP_ALIASES = {
    "HR_ADMIN": "HR_MANAGER",
    "EMPLOYEE_VIEWER": "EMPLOYEE",
    "BACKOFFICE_STAFF": "UNIT_STATISTICIAN",
    "BACKOFFICE_MANAGER": "UNIT_COMMANDER",
    # SUPERADMIN là group cũ từng được dùng như all-permissions. Giai đoạn mới ưu tiên superuser.
    # Vẫn tạo group để tránh lỗi dữ liệu cũ, nhưng không khuyến nghị gán cho user mới.
    "SUPERADMIN": "SYSTEM_ADMIN",
}


class Command(BaseCommand):
    help = "Tạo/cập nhật các nhóm quyền backoffice chuẩn và gán permission nền."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Chỉ in thay đổi dự kiến, không ghi database.",
        )
        parser.add_argument(
            "--keep-extra",
            action="store_true",
            help="Giữ lại các quyền đã gán thủ công ngoài ma trận chuẩn thay vì set chính xác.",
        )
        parser.add_argument(
            "--skip-legacy",
            action="store_true",
            help="Không tạo/cập nhật các nhóm tương thích cũ như HR_ADMIN/BACKOFFICE_STAFF.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        keep_extra = bool(options.get("keep_extra"))
        skip_legacy = bool(options.get("skip_legacy"))

        missing: list[str] = []
        updated_count = 0

        canonical_perms: dict[str, set[Permission]] = {}
        for group_name, cfg in GROUP_DEFINITIONS.items():
            perms = self._resolve_permissions(cfg.get("permissions", []), missing)
            canonical_perms[group_name] = perms
            self._sync_group(group_name, perms, keep_extra=keep_extra, dry_run=dry_run, label=cfg.get("label", ""))
            updated_count += 1

        if not skip_legacy:
            for legacy_name, target_name in LEGACY_GROUP_ALIASES.items():
                target_perms = canonical_perms.get(target_name, set())
                self._sync_group(
                    legacy_name,
                    target_perms,
                    keep_extra=keep_extra,
                    dry_run=dry_run,
                    label=f"Tương thích cũ → {target_name}",
                )
                updated_count += 1

        if missing:
            self.stdout.write(self.style.WARNING("Một số permission chưa tồn tại, đã bỏ qua:"))
            for item in sorted(set(missing)):
                self.stdout.write(self.style.WARNING(f"  - {item}"))
            self.stdout.write(self.style.WARNING("Hãy chắc chắn đã chạy migrate trước khi seed group."))

        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: chưa ghi database. {updated_count} group được kiểm tra."))
            transaction.set_rollback(True)
        else:
            self.stdout.write(self.style.SUCCESS(f"Đã tạo/cập nhật {updated_count} group quyền backoffice."))
            self.stdout.write(self.style.SUCCESS("Lưu ý: AccessControl vẫn cần gán riêng cho từng user để xác định phạm vi đơn vị."))

    def _resolve_permissions(self, specs: Iterable[PermSpec], missing: list[str]) -> set[Permission]:
        resolved: set[Permission] = set()
        for spec in specs:
            try:
                ct = ContentType.objects.get(app_label=spec.app_label, model=spec.model)
            except ContentType.DoesNotExist:
                for action in spec.actions:
                    missing.append(f"{spec.app_label}.{action}_{spec.model} (missing content type)")
                continue

            for action in spec.actions:
                codename = f"{action}_{spec.model}"
                perm = Permission.objects.filter(content_type=ct, codename=codename).first()
                if perm:
                    resolved.add(perm)
                else:
                    missing.append(f"{spec.app_label}.{codename}")
        return resolved

    def _sync_group(self, name: str, perms: set[Permission], *, keep_extra: bool, dry_run: bool, label: str = ""):
        group, created = Group.objects.get_or_create(name=name)
        current_ids = set(group.permissions.values_list("id", flat=True))
        target_ids = {perm.id for perm in perms}

        if keep_extra:
            final_ids = current_ids | target_ids
        else:
            final_ids = target_ids

        verb = "Tạo" if created else "Cập nhật"
        extra_note = " + giữ quyền cũ" if keep_extra else ""
        label_note = f" ({label})" if label else ""
        self.stdout.write(f"{verb} group {name}{label_note}: {len(final_ids)} permission{extra_note}")

        if not dry_run:
            group.permissions.set(final_ids)
            group.save()
