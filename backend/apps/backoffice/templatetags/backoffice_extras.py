from django import template

register = template.Library()

@register.simple_tag
def has_perm(role_perm_ids, group_id, perm_id):
    """
    Trả về True/False nếu perm_id nằm trong tập permissions của group_id.
    role_perm_ids: dict { group_id: iterable_of_permission_ids }
    """
    perm_ids = role_perm_ids.get(group_id) or []
    try:
        return int(perm_id) in set(int(x) for x in perm_ids)
    except Exception:
        # Fall back nếu có kiểu dữ liệu khác
        return str(perm_id) in set(str(x) for x in perm_ids)