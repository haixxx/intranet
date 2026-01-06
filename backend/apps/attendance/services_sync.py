from typing import Optional
from datetime import date as dt_date
from django.db import transaction
from apps.attendance.models_batch import (
    AttendanceBatch, AttendanceBatchItem,
    AttendanceCommit, AttendanceCommitItem
)

def sync_batch_with_commit(unit_id: int, work_date: dt_date) -> dict:
    """
    Đồng bộ AttendanceBatchItem theo AttendanceCommitItem của cùng unit/date.
    - Nếu chưa có Batch: tạo mới LOCKED_DRAFT và fill theo commit.
    - Nếu đã có: cập nhật/điền đủ các dòng nhân sự theo commit, thay thế toàn bộ fields phản ánh công đã chốt.
    - DELETE EXTRAS: XÓA các dòng nháp không còn trong commit (để nháp phản ánh đúng công đã chốt).
    Trả về: {"created": x, "updated": y, "deleted": z}
    """
    commit = AttendanceCommit.objects.filter(unit_id=unit_id, work_date=work_date).first()
    if not commit:
        return {"created": 0, "updated": 0, "deleted": 0}

    batch, _ = AttendanceBatch.objects.get_or_create(
        unit_id=unit_id, work_date=work_date,
        defaults={"status": AttendanceBatch.Status.LOCKED_DRAFT}
    )

    created, updated, deleted = 0, 0, 0
    with transaction.atomic():
        # Map hiện có trong batch và commit
        batch_items_map = {bi.employee_id: bi for bi in batch.items.all()}
        commit_items_map = {ci.employee_id: ci for ci in commit.items.select_related("employee", "code")}

        # Xóa các dòng nháp không còn trong commit
        extra_emp_ids = set(batch_items_map.keys()) - set(commit_items_map.keys())
        if extra_emp_ids:
            qs_del = batch.items.filter(employee_id__in=list(extra_emp_ids))
            deleted = qs_del.count()
            qs_del.delete()

        # Cập nhật/điền đủ theo commit
        for emp_id, ci in commit_items_map.items():
            bi = batch_items_map.get(emp_id)
            if not bi:
                bi = AttendanceBatchItem(batch=batch, employee=ci.employee)
                created += 1
            else:
                updated += 1

            bi.code = ci.code
            bi.shift = ci.shift
            bi.in1 = ci.in1
            bi.out1 = ci.out1
            bi.in2 = ci.in2
            bi.out2 = ci.out2
            bi.notes = ci.notes
            bi.bs_direction = ci.bs_direction
            bi.bs_peer_unit = ci.bs_peer_unit
            bi.include_in_unit = ci.include_in_unit
            bi.save()

        # Đặt trạng thái batch là LOCKED_DRAFT để phân biệt với danh sách đang thao tác
        if batch.status != AttendanceBatch.Status.LOCKED_DRAFT:
            batch.status = AttendanceBatch.Status.LOCKED_DRAFT
            batch.save(update_fields=["status"])

    return {"created": created, "updated": updated, "deleted": deleted}