from __future__ import annotations

from typing import Iterable

from django.core.paginator import Paginator


DEFAULT_PAGE_SIZE_OPTIONS = (25, 50, 100, 200)


def safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def resolve_page_size(raw_value, default: int = 50, allowed: Iterable[int] = DEFAULT_PAGE_SIZE_OPTIONS) -> int:
    allowed_values = tuple(int(v) for v in allowed)
    value = safe_int(raw_value, default)
    if value not in allowed_values:
        return default
    return value


def build_page_window(paginator: Paginator, current_page: int, *, on_each_side: int = 2, on_ends: int = 1):
    """
    Return a compact page range for template rendering.

    Using Python here avoids fragile arithmetic in Django templates and avoids looping over
    every page when a queryset has a large number of pages.
    """
    try:
        return list(paginator.get_elided_page_range(number=current_page, on_each_side=on_each_side, on_ends=on_ends))
    except AttributeError:
        # Defensive fallback for older Django versions.
        total = paginator.num_pages
        start = max(1, current_page - on_each_side)
        end = min(total, current_page + on_each_side)
        pages = list(range(start, end + 1))
        if start > 1:
            pages = [1, "…"] + pages
        if end < total:
            pages = pages + ["…", total]
        return pages


def paginate_queryset(
    request,
    queryset,
    *,
    default_page_size: int = 50,
    allowed_page_sizes: Iterable[int] = DEFAULT_PAGE_SIZE_OPTIONS,
    page_param: str = "page",
):
    """
    Server-side pagination helper for Backoffice list pages.

    Returns a context dict with items/page_obj/paginator/page_window/page_size/page_size_options/total_count/current_page.
    Keeps view code small and consistent across system-admin screens.
    """
    allowed_page_sizes = tuple(int(v) for v in allowed_page_sizes)
    page_size = resolve_page_size(request.GET.get("page_size"), default_page_size, allowed_page_sizes)
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(request.GET.get(page_param))
    current_page = page_obj.number
    return {
        "items": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "page_window": build_page_window(paginator, current_page),
        "page_size": page_size,
        "page_size_options": list(allowed_page_sizes),
        "total_count": paginator.count,
        "current_page": current_page,
    }
