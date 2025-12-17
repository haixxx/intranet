from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.utils.translation import gettext as _
from django.db.models import Q

# Chưa có models cho approvals. Skeleton UI dữ liệu giả lập để bạn duyệt khung.
# Khi chốt mô hình, các query sẽ thay bằng models thực tế (ApprovalRequest, ApprovalStep, ...)

# Dummy dữ liệu để render khung UI (sẽ thay thế bằng query thật)
class DummyRequest:
    def __init__(self, id, title, flow_name, status, submitted_at, requester_username):
        self.id = id
        self.title = title
        self.flow = type("Flow", (), {"name": flow_name})
        self.status = status
        self.submitted_at = submitted_at
        self.requester = type("User", (), {"username": requester_username})
        self.flow_version = type("Ver", (), {"version": 1})

def _dummy_requests_for_user(user):
    from datetime import datetime, timedelta
    now = datetime.now()
    # Demo 3 yêu cầu
    return [
        DummyRequest(101, "Đề nghị sửa chấm công 2025-12-05", "Phê duyệt sửa chấm công", "IN_PROGRESS", now - timedelta(hours=4), user.username),
        DummyRequest(102, "Nghiệm thu thiết bị A", "Phê duyệt nghiệm thu", "APPROVED", now - timedelta(days=2), user.username),
        DummyRequest(103, "Đề nghị OT ngày 2025-12-09", "Phê duyệt OT", "REJECTED", now - timedelta(days=1), user.username),
    ]

@login_required
def approvals_inbox(request):
    """
    Danh sách phê duyệt: Tôi phải phê duyệt.
    Skeleton: render danh sách 'signers' giả lập. Sau này sẽ truy vấn theo signer assigned.
    """
    # Demo signers: mỗi item gắn với DummyRequest
    dummy_reqs = _dummy_requests_for_user(request.user)
    signers = [
        {
            "request": dummy_reqs[0],
            "step_label": "Lãnh đạo đơn vị của NSTK",
            "step_status": "ACTIVE",
            "activated_at": dummy_reqs[0].submitted_at,
        }
    ]
    return render(request, "backoffice/approvals/inbox.html", {"signers": signers})

@login_required
def approvals_my_requests(request):
    """
    Danh sách yêu cầu do tôi lập.
    Skeleton: dùng dummy list, hỗ trợ lọc cơ bản theo trạng thái và từ khóa.
    """
    qs = _dummy_requests_for_user(request.user)
    status = request.GET.get("status", "").strip()
    q = request.GET.get("q", "").strip()

    if status:
        qs = [it for it in qs if it.status == status]
    if q:
        qs = [it for it in qs if (q.lower() in it.title.lower()) or (q.lower() in str(it.id))]

    return render(request, "backoffice/approvals/my_requests.html", {"requests": qs, "status": status, "q": q})

@login_required
def approval_request_detail(request, request_id: int):
    """
    Chi tiết yêu cầu: hiển thị metadata, timeline bước, người ký, thao tác.
    Skeleton: render bằng dummy dữ liệu.
    """
    # tìm dummy request theo id
    req = None
    for it in _dummy_requests_for_user(request.user):
        if it.id == request_id:
            req = it
            break
    if not req:
        # Không dùng get_object_or_404 vì đây là dummy; render trang rỗng
        return render(request, "backoffice/approvals/request_detail.html", {"req": None, "steps": []})

    # Dummy steps
    steps = [
        {
            "order_index": 1,
            "label": "Lãnh đạo đơn vị của NSTK",
            "quorum_display": "Theo nhóm: mỗi nhóm ký 1 người, tất cả nhóm hoàn thành",
            "status_display": "Đang ký" if req.status == "IN_PROGRESS" else "Hoàn tất",
            "signers": [
                {"user_display": "truong_phong", "status_display": "Chờ ký", "role_title": "HEAD", "group_key": "unit:PX01"}
            ],
        },
        {
            "order_index": 2,
            "label": "Nhân viên phòng HR (đích danh)",
            "quorum_display": "Tất cả phải ký",
            "status_display": "Chờ kích hoạt" if req.status == "IN_PROGRESS" else ("Hoàn tất" if req.status == "APPROVED" else "Bị từ chối"),
            "signers": [
                {"user_display": "hr649", "status_display": "Chờ ký", "role_title": "", "group_key": ""}
            ],
        }
    ]
    # metadata snapshot
    metadata_json = {
        "flow": req.flow.name,
        "object_type": "attendance_correction",
        "object_id": "REQ-0001",
        "employee_user": request.user.username,
        "note": "Ví dụ demo skeleton",
    }

    return render(request, "backoffice/approvals/request_detail.html", {"req": req, "steps": steps, "metadata_json": metadata_json})