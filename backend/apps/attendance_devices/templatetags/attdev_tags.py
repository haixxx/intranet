from django import template

register = template.Library()

@register.filter
def get_item(d, key):
    """
    Trả về d.get(key) dùng trong template: {{ dict|get_item:obj.id }}
    """
    try:
        return d.get(key)
    except Exception:
        return None