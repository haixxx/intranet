from typing import List, Set
from .models import OrgUnit

def get_subtree_unit_ids(root: OrgUnit) -> List[int]:
    """
    Lấy tất cả id trong cây con (bao gồm root).
    Không dùng đệ quy SQL để tương thích SQLite dev; dùng BFS.
    """
    if not root:
        return []
    ids: List[int] = []
    queue: List[int] = [root.id]
    while queue:
        current_ids = queue[:]
        queue = []
        ids.extend(current_ids)
        children = OrgUnit.objects.filter(parent_id__in=current_ids).values_list('id', flat=True)
        queue.extend(list(children))
    return ids