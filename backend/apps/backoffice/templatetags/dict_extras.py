from django import template

register = template.Library()

@register.filter
def dict_get(d, key):
    """
    Lấy giá trị d[key] an toàn trong template.
    Usage: {{ my_dict|dict_get:object.id }}
    """
    if d is None:
        return ""
    try:
        return d.get(key)
    except Exception:
        return ""