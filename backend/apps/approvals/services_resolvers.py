from typing import Dict, Any, List, Optional, Tuple
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()

# NOTE: Đây là skeleton resolver. Sau khi nối với dữ liệu tổ chức thực tế,
# chúng ta sẽ thay thế các đoạn giả lập bằng truy vấn models OrgUnit/Role/Position của hệ thống.


def resolve_dept_heads_of_employee_unit(employee_user_id: int, role_chain: List[str]) -> List[Tuple[User, Dict[str, Any]]]:
    """
    Trả về danh sách signer cho đơn vị của nhân sự (NSTK).
    - role_chain: thứ tự fallback (ví dụ ["HEAD","DEPUTY","IN_CHARGE"])
    - Kết quả: danh sách (user, meta) — meta có role_title, group_key="unit:<id or code>"
    """
    # TODO: lấy unit_id của employee_user_id từ hệ thống nhân sự
    # Ví dụ giả lập: unit_id = get_unit_of_employee(employee_user_id)
    unit_id = None  # thay bằng lookup thật

    signers: List[Tuple[User, Dict[str, Any]]] = []

    # TODO: theo từng role trong chain, tìm người có role tại unit_id
    # Ví dụ giả lập: HEAD -> tìm 1 người; nếu có, thêm và dừng (ANY)
    for role in role_chain:
        # replace bằng query thật: User.objects.filter(positions__role_title=role, positions__unit_id=unit_id, is_active=True)
        qs = User.objects.none()  # giả lập
        u = qs.first()
        if u:
            signers.append((u, {"role_title": role, "group_key": f"unit:{unit_id}"}))
            break

    return signers


def resolve_explicit_users(user_ids: List[int]) -> List[Tuple[User, Dict[str, Any]]]:
    users = list(User.objects.filter(id__in=user_ids, is_active=True))
    return [(u, {"role_title": "", "group_key": ""}) for u in users]