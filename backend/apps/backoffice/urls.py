from django.urls import path

from . import views
from . import views_audit
from . import views_employees
from . import views_import_export
from . import views_jobtitles
from . import views_orgunits
from . import views_permissions
from . import views_profile
from . import views_roles
from . import views_shifts
from . import views_users

from apps.backoffice import views_approvals
from apps.backoffice import views_approvals_admin
from apps.backoffice import views_approvals_manage
from apps.backoffice import views_attendance_batch
from apps.backoffice import views_attendance_codes
from apps.backoffice import views_attendance_diff
from apps.backoffice import views_attendance_monthly
from apps.backoffice import views_attendance_roster
from apps.backoffice import views_notifications
from apps.backoffice import views_role_mapping
from apps.backoffice import views_temp_assignments

urlpatterns = [
    # Dashboard / profile
    path("", views.dashboard, name="dashboard"),
    path("profile/", views_profile.profile_view, name="profile"),

    # Users
    path("users/", views_users.user_list, name="user_list"),
    path("users/new/", views_users.user_create, name="user_create"),
    path("users/<int:user_id>/", views_users.user_edit, name="user_edit"),
    path("users/<int:user_id>/roles/", views_users.user_roles, name="user_roles"),
    path("users/<int:user_id>/deactivate/", views_users.user_deactivate, name="user_deactivate"),
    path("users/<int:user_id>/activate/", views_users.user_activate, name="user_activate"),

    # Roles / permissions / audit
    path("roles/", views_roles.role_list, name="role_list"),
    path("roles/<int:role_id>/", views_roles.role_edit, name="role_edit"),
    path("roles/<int:role_id>/delete/", views_roles.role_delete, name="role_delete"),
    path("roles/matrix/", views_permissions.permission_matrix, name="permission_matrix"),
    path("audit/", views_audit.audit_list, name="audit_list"),

    # Organization
    path("org/units/", views_orgunits.orgunit_list, name="orgunit_list"),
    path("org/units/new/", views_orgunits.orgunit_create, name="orgunit_create"),
    path("org/units/<int:pk>/", views_orgunits.orgunit_edit, name="orgunit_edit"),
    path("org/units/<int:pk>/delete/", views_orgunits.orgunit_delete, name="orgunit_delete"),
    path("org/units/<int:pk>/restore/", views_orgunits.orgunit_restore, name="orgunit_restore"),
    path("org/units/export/", views_import_export.export_orgunits, name="export_orgunits"),
    path("org/units/import/", views_import_export.import_orgunits, name="import_orgunits"),

    path("org/jobtitles/", views_jobtitles.jobtitle_list, name="jobtitle_list"),
    path("org/jobtitles/new/", views_jobtitles.jobtitle_create, name="jobtitle_create"),
    path("org/jobtitles/<int:pk>/", views_jobtitles.jobtitle_edit, name="jobtitle_edit"),
    path("org/jobtitles/<int:pk>/delete/", views_jobtitles.jobtitle_delete, name="jobtitle_delete"),
    path("org/jobtitles/<int:pk>/restore/", views_jobtitles.jobtitle_restore, name="jobtitle_restore"),
    path("org/jobtitles/export/", views_import_export.export_jobtitles, name="export_jobtitles"),
    path("org/jobtitles/import/", views_import_export.import_jobtitles, name="import_jobtitles"),

    path("org/shifts/", views_shifts.shift_list, name="shift_list"),
    path("org/shifts/new/", views_shifts.shift_create, name="shift_create"),
    path("org/shifts/<int:pk>/", views_shifts.shift_edit, name="shift_edit"),
    path("org/shifts/<int:pk>/delete/", views_shifts.shift_delete, name="shift_delete"),
    path("org/shifts/<int:pk>/restore/", views_shifts.shift_restore, name="shift_restore"),
    path("org/shifts/export/", views_import_export.export_shifts, name="export_shifts"),
    path("org/shifts/import/", views_import_export.import_shifts, name="import_shifts"),

    # HR employees
    path("hr/employees/", views_employees.employee_list, name="employee_list"),
    path("hr/employees/new/", views_employees.employee_create, name="employee_create"),
    path("hr/employees/<int:pk>/", views_employees.employee_edit, name="employee_edit"),
    path("hr/employees/<int:pk>/detail/", views_employees.employee_detail, name="employee_detail"),
    path("hr/employees/<int:pk>/create-user/", views_employees.employee_create_user, name="employee_create_user"),
    path("hr/employees/<int:pk>/deactivate/", views_employees.employee_deactivate, name="employee_deactivate"),
    path("hr/employees/<int:pk>/leave/", views_employees.employee_leave, name="employee_leave"),
    path("hr/employees/export/", views_import_export.export_employees, name="export_employees"),
    path("hr/employees/import/", views_import_export.import_employees, name="import_employees"),

    # Temporary assignments
    path("assignments/", views_temp_assignments.temp_assignment_list, name="temp_assignment_list"),
    path("assignments/create/", views_temp_assignments.temp_assignment_create, name="temp_assignment_create"),
    path("assignments/<int:pk>/edit/", views_temp_assignments.temp_assignment_edit, name="temp_assignment_edit"),
    path("assignments/<int:pk>/cancel/", views_temp_assignments.temp_assignment_cancel, name="temp_assignment_cancel"),

    # Attendance catalog/settings
    path("attendance/codes/", views_attendance_codes.attendance_code_list, name="attendance_code_list"),
    path("attendance/codes/new/", views_attendance_codes.attendance_code_create, name="attendance_code_create"),
    path("attendance/codes/<int:pk>/edit/", views_attendance_codes.attendance_code_edit, name="attendance_code_edit"),
    path("attendance/codes/<int:pk>/delete/", views_attendance_codes.attendance_code_delete, name="attendance_code_delete"),
    path("attendance/settings/", views_attendance_codes.attendance_settings_view, name="attendance_settings"),

    # Attendance batch/commit
    path("attendance/batch/", views_attendance_batch.batch_create_or_load, name="attendance_batch_create_or_load"),
    path("attendance/batch/<int:batch_id>/save/", views_attendance_batch.batch_save, name="attendance_batch_save"),
    path("attendance/batch/<int:batch_id>/commit/", views_attendance_batch.batch_commit, name="attendance_batch_commit"),
    path("attendance/batch/<int:batch_id>/refresh/", views_attendance_batch.batch_refresh_roster, name="attendance_batch_refresh"),
    path("attendance/committed/", views_attendance_batch.committed_view, name="attendance_committed_view"),
    path(
        "attendance/batch/<int:batch_id>/request-correction/",
        views_attendance_batch.attendance_correction_request_create,
        name="attendance_correction_request_create",
    ),

    # Attendance diff/roster APIs
    path("attendance/batch/diff", views_attendance_diff.batch_diff_api, name="attendance_batch_diff_api"),
    path("attendance/batch/roster/diff", views_attendance_roster.batch_roster_diff_api, name="attendance_batch_roster_diff"),
    path("attendance/batch/roster/apply", views_attendance_roster.batch_roster_apply, name="attendance_batch_roster_apply"),

    # Monthly attendance
    path("attendance/monthly/", views_attendance_monthly.monthly_view, name="attendance_monthly_view"),
    path("attendance/monthly/export/", views_attendance_monthly.monthly_export, name="attendance_monthly_export"),

    # Notifications
    path("notifications/", views_notifications.notifications_list, name="notifications_list"),

    # Approvals
    path("approvals/", views_approvals.approvals_inbox, name="approvals_inbox"),
    path("approvals/my-requests/", views_approvals.approvals_my_requests, name="approvals_my_requests"),
    path("approvals/requests/<int:request_id>/", views_approvals.approval_request_detail, name="approvals_request_detail"),
    path("approvals/requests/<int:request_id>/steps/<int:order_index>/action/", views_approvals.approval_step_action, name="approval_step_action"),
    path("approvals/requests/<int:request_id>/cancel/", views_approvals_manage.approval_request_cancel, name="approvals_request_cancel"),

    # Approvals admin / builder
    path("approvals/admin/flows/", views_approvals_admin.flow_list, name="approval_flow_list"),
    path("approvals/admin/flows/new/", views_approvals_admin.flow_create, name="approval_flow_create"),
    path("approvals/admin/flows/<int:flow_id>/", views_approvals_admin.flow_edit, name="approval_flow_edit"),
    path("approvals/admin/flows/<int:flow_id>/delete/", views_approvals_admin.flow_delete, name="approval_flow_delete"),
    path("approvals/admin/flows/<int:flow_id>/versions/", views_approvals_admin.version_list, name="approval_flow_version_list"),
    path("approvals/admin/flows/<int:flow_id>/versions/new/builder/", views_approvals_admin.version_create_builder, name="approval_flow_version_create_builder"),
    path("approvals/admin/flows/<int:flow_id>/versions/<int:version_id>/builder/", views_approvals_admin.version_edit_builder, name="approval_flow_version_edit_builder"),
    path("approvals/admin/flows/<int:flow_id>/versions/<int:version_id>/publish/", views_approvals_admin.version_publish, name="approval_flow_version_publish"),
    path("approvals/admin/flows/<int:flow_id>/versions/<int:version_id>/delete/", views_approvals_admin.version_delete, name="approval_flow_version_delete"),

    # Role title mapping
    path("approvals/role-mapping/", views_role_mapping.role_title_mapping_list, name="role_title_mapping_list"),
    path("approvals/role-mapping/new/", views_role_mapping.role_title_mapping_create, name="role_title_mapping_create"),
    path("approvals/role-mapping/<int:pk>/", views_role_mapping.role_title_mapping_edit, name="role_title_mapping_edit"),
    path("approvals/role-mapping/<int:pk>/delete/", views_role_mapping.role_title_mapping_delete, name="approval_role_title_mapping_delete"),
]
