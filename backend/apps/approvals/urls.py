from django.urls import path
from .views import approvals_inbox, approvals_my_requests, approval_request_detail, approval_action_approve, approval_action_reject

app_name = "approvals"

urlpatterns = [
    path("", approvals_inbox, name="inbox"),
    path("my-requests/", approvals_my_requests, name="my_requests"),
    path("requests/<int:request_id>/", approval_request_detail, name="request_detail"),
    path("requests/<int:request_id>/steps/<int:step_id>/signers/<int:signer_id>/approve/", approval_action_approve, name="approve"),
    path("requests/<int:request_id>/steps/<int:step_id>/signers/<int:signer_id>/reject/", approval_action_reject, name="reject"),
]