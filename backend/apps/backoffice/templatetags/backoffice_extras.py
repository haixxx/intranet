from django import template

register = template.Library()


@register.simple_tag
def has_perm(role_perm_ids, group_id, perm_id):
    """
    Return True/False if perm_id is assigned to group_id.

    role_perm_ids should preferably be prepared as {group_id: set(permission_ids)} in the view.
    The fallback branches keep the tag tolerant of string/int mismatches without rebuilding sets
    for every rendered cell.
    """
    perm_ids = role_perm_ids.get(group_id) or role_perm_ids.get(str(group_id)) or set()
    if perm_id in perm_ids:
        return True
    try:
        return int(perm_id) in perm_ids
    except (TypeError, ValueError):
        return str(perm_id) in perm_ids


@register.simple_tag(takes_context=True)
def query_transform(context, **kwargs):
    """Preserve current GET parameters and replace/remove selected keys."""
    request = context.get("request")
    if request is None:
        return ""
    query = request.GET.copy()
    for key, value in kwargs.items():
        if value is None or value == "":
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()
