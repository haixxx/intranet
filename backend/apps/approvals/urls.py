from django.urls import path
from . import views

app_name = "approvals"

urlpatterns = [
    path("", views.approvals_inbox, name="inbox"),
    path("my-requests/", views.approvals_my_requests, name="my_requests"),
    path("requests/<int:request_id>/", views.approval_request_detail, name="request_detail"),
    # Các endpoint hành động sẽ bổ sung sau khi có logic nghiệp vụ:
    # path("requests/<int:request_id>/approve/", views.approval_request_approve, name="request_approve"),
    # path("requests/<int:request_id>/reject/", views.approval_request_reject, name="request_reject"),
]