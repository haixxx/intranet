from typing import Dict, Set
from apps.approvals.models_config import RoleTitleMapping

def get_role_title_map() -> Dict[str, Set[str]]:
    """
    Đọc cấu hình từ DB, trả về dict: role_key -> set(title_code).
    Nếu không có cấu hình → trả về map rỗng.
    """
    res: Dict[str, Set[str]] = {}
    qs = RoleTitleMapping.objects.filter(is_active=True)
    for m in qs:
        role_key = (m.role_key or "").strip()
        title_code = (m.title_code or "").strip()
        if not role_key or not title_code:
            continue
        res.setdefault(role_key, set()).add(title_code)
    return res