from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Any

from .models_config import RoleTitleMapping

try:
    from apps.organization.models import JobTitle, OrgUnit
except Exception:  # pragma: no cover
    JobTitle = None
    OrgUnit = None

try:
    from apps.hr.models import Employee
except Exception:  # pragma: no cover
    Employee = None


LEADER_ROLE_KEYS = {"HEAD", "DEPUTY", "IN_CHARGE"}
SUSPICIOUS_TITLE_KEYWORDS = (
    "nhan vien",
    "nhanvien",
    "nhan su thong ke",
    "nhan vien thong ke",
    "thong ke",
    "statistic",
    "clerk",
    "staff",
)


def _norm(text: Any) -> str:
    raw = str(text or "").strip().lower()
    raw = unicodedata.normalize("NFD", raw)
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    return raw


def _job_title_by_code():
    if JobTitle is None:
        return {}
    result = {}
    for jt in JobTitle.objects.all():
        code = str(getattr(jt, "code", "") or "").strip()
        if code:
            result[code] = jt
        result[str(jt.id)] = jt
    return result


def _job_title_label(jt) -> str:
    if not jt:
        return "—"
    code = getattr(jt, "code", "") or ""
    name = getattr(jt, "name", "") or str(jt)
    return f"{name} ({code or jt.id})"


def _employee_is_active_filter():
    status_active = getattr(getattr(Employee, "Status", None), "ACTIVE", None) if Employee else None
    return {"status": status_active} if status_active is not None else {}


def build_role_mapping_diagnostics(limit_units: int = 20, limit_employees: int = 20) -> dict[str, Any]:
    """
    Kiểm tra nhanh cấu hình Role Mapping để phát hiện các lỗi vận hành thường gặp.

    Không thay đổi dữ liệu. Hàm này dùng được cho UI và management command.
    """
    active_mappings = list(RoleTitleMapping.objects.filter(is_active=True).order_by("role_key", "title_code"))
    all_mappings = list(RoleTitleMapping.objects.all().order_by("role_key", "title_code"))
    jt_by_code = _job_title_by_code()

    issues: list[dict[str, Any]] = []
    counts = Counter(m.role_key for m in active_mappings)

    if not active_mappings:
        issues.append({
            "severity": "danger",
            "title": "Chưa có Role Mapping active",
            "message": "Bước Lãnh đạo đơn vị sẽ không xác định được người ký nếu không có mapping hoặc fallback được bật rõ.",
        })

    for m in active_mappings:
        role_key = (m.role_key or "").strip()
        title_code = (m.title_code or "").strip()
        jt = jt_by_code.get(title_code)

        if role_key not in LEADER_ROLE_KEYS:
            issues.append({
                "severity": "warning",
                "title": "Role key chưa chuẩn",
                "message": f"Mapping {role_key}:{title_code} không nằm trong nhóm HEAD/DEPUTY/IN_CHARGE.",
            })

        if not jt:
            issues.append({
                "severity": "danger",
                "title": "Không tìm thấy chức danh",
                "message": f"Mapping {role_key}:{title_code} không khớp JobTitle.code đang có.",
            })
            continue

        if hasattr(jt, "is_active") and not bool(jt.is_active):
            issues.append({
                "severity": "warning",
                "title": "Chức danh đã inactive",
                "message": f"{_job_title_label(jt)} đang inactive nhưng vẫn nằm trong Role Mapping active.",
            })

        label_norm = _norm(f"{getattr(jt, 'name', '')} {getattr(jt, 'code', '')}")
        if any(key in label_norm for key in SUSPICIOUS_TITLE_KEYWORDS):
            issues.append({
                "severity": "warning",
                "title": "Chức danh có vẻ không phải lãnh đạo",
                "message": f"{_job_title_label(jt)} đang được map vào {role_key}. Cần kiểm tra để tránh nhân viên thống kê/nhân viên thường được quyền duyệt.",
            })

    units_without_leader = []
    employees_without_user = []
    if Employee is not None and JobTitle is not None:
        active_codes = {m.title_code for m in active_mappings if (m.role_key or "").strip() in LEADER_ROLE_KEYS}
        emp_filter = _employee_is_active_filter()

        if active_codes:
            qs = Employee.objects.select_related("job_title", "user", "unit").filter(job_title__code__in=active_codes, **emp_filter)
            for emp in qs:
                user = getattr(emp, "user", None)
                if not user or not getattr(user, "is_active", True):
                    employees_without_user.append(emp)
                    if len(employees_without_user) >= limit_employees:
                        break

        if OrgUnit is not None and active_codes:
            unit_qs = OrgUnit.objects.filter(is_active=True, is_attendance_unit=True).order_by("symbol", "name")
            for unit in unit_qs:
                exists = Employee.objects.filter(
                    unit_id=unit.id,
                    job_title__code__in=active_codes,
                    user__isnull=False,
                    user__is_active=True,
                    **emp_filter,
                ).exists()
                if not exists:
                    units_without_leader.append(unit)
                    if len(units_without_leader) >= limit_units:
                        break

    if employees_without_user:
        samples = ", ".join(
            f"{getattr(e, 'full_name', e)} - {_job_title_label(getattr(e, 'job_title', None))}"
            for e in employees_without_user[:5]
        )
        issues.append({
            "severity": "warning",
            "title": "Lãnh đạo có chức danh mapping nhưng chưa liên kết user active",
            "message": samples + ("..." if len(employees_without_user) > 5 else ""),
        })

    if units_without_leader:
        samples = ", ".join((getattr(u, "symbol", "") or getattr(u, "name", "") or str(u)) for u in units_without_leader[:8])
        issues.append({
            "severity": "warning",
            "title": "Một số đơn vị chưa tìm thấy lãnh đạo ký",
            "message": samples + ("..." if len(units_without_leader) > 8 else ""),
        })

    severity_order = {"danger": 0, "warning": 1, "info": 2, "success": 3}
    issues.sort(key=lambda x: severity_order.get(x.get("severity"), 9))

    return {
        "active_count": len(active_mappings),
        "total_count": len(all_mappings),
        "counts_by_role": dict(counts),
        "issue_count": len(issues),
        "danger_count": sum(1 for x in issues if x.get("severity") == "danger"),
        "warning_count": sum(1 for x in issues if x.get("severity") == "warning"),
        "issues": issues,
        "units_without_leader_count": len(units_without_leader),
        "employees_without_user_count": len(employees_without_user),
    }
