from django.urls import path
from . import views
from . import views_users, views_roles, views_permissions, views_audit
from . import views_orgunits, views_jobtitles, views_shifts, views_employees, views_import_export, views_profile
from apps.backoffice import views_temp_assignments
from apps.backoffice import views_attendance_codes
# BỎ đăng ký công (cá nhân)
from apps.backoffice import views_attendance_batch

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('profile/', views_profile.profile_view, name='profile'),
    # Users
    path('users/', views_users.user_list, name='user_list'),
    path('users/new/', views_users.user_create, name='user_create'),
    path('users/<int:user_id>/', views_users.user_edit, name='user_edit'),
    path('users/<int:user_id>/roles/', views_users.user_roles, name='user_roles'),
    path('users/<int:user_id>/deactivate/', views_users.user_deactivate, name='user_deactivate'),
    path('users/<int:user_id>/activate/', views_users.user_activate, name='user_activate'),
    # Roles / Permissions / Audit
    path('roles/', views_roles.role_list, name='role_list'),
    path('roles/<int:role_id>/', views_roles.role_edit, name='role_edit'),
    path('roles/<int:role_id>/delete/', views_roles.role_delete, name='role_delete'),
    path('roles/matrix/', views_permissions.permission_matrix, name='permission_matrix'),
    path('audit/', views_audit.audit_list, name='audit_list'),
    # Organization
    path('org/units/', views_orgunits.orgunit_list, name='orgunit_list'),
    path('org/units/new/', views_orgunits.orgunit_create, name='orgunit_create'),
    path('org/units/<int:pk>/', views_orgunits.orgunit_edit, name='orgunit_edit'),
    path('org/units/<int:pk>/delete/', views_orgunits.orgunit_delete, name='orgunit_delete'),
    path('org/units/export/', views_import_export.export_orgunits, name='export_orgunits'),
    path('org/units/import/', views_import_export.import_orgunits, name='import_orgunits'),
    path('org/jobtitles/', views_jobtitles.jobtitle_list, name='jobtitle_list'),
    path('org/jobtitles/new/', views_jobtitles.jobtitle_create, name='jobtitle_create'),
    path('org/jobtitles/<int:pk>/', views_jobtitles.jobtitle_edit, name='jobtitle_edit'),
    path('org/jobtitles/<int:pk>/delete/', views_jobtitles.jobtitle_delete, name='jobtitle_delete'),
    path('org/jobtitles/export/', views_import_export.export_jobtitles, name='export_jobtitles'),
    path('org/jobtitles/import/', views_import_export.import_jobtitles, name='import_jobtitles'),
    path('org/shifts/', views_shifts.shift_list, name='shift_list'),
    path('org/shifts/new/', views_shifts.shift_create, name='shift_create'),
    path('org/shifts/<int:pk>/', views_shifts.shift_edit, name='shift_edit'),
    path('org/shifts/<int:pk>/delete/', views_shifts.shift_delete, name='shift_delete'),
    path('org/shifts/export/', views_import_export.export_shifts, name='export_shifts'),
    path('org/shifts/import/', views_import_export.import_shifts, name='import_shifts'),
    # HR Employees
    path('hr/employees/', views_employees.employee_list, name='employee_list'),
    path('hr/employees/new/', views_employees.employee_create, name='employee_create'),
    path('hr/employees/<int:pk>/', views_employees.employee_edit, name='employee_edit'),
    path('hr/employees/<int:pk>/detail/', views_employees.employee_detail, name='employee_detail'),
    path('hr/employees/<int:pk>/create-user/', views_employees.employee_create_user, name='employee_create_user'),
    path('hr/employees/<int:pk>/deactivate/', views_employees.employee_deactivate, name='employee_deactivate'),
    path('hr/employees/<int:pk>/leave/', views_employees.employee_leave, name='employee_leave'),
    path('hr/employees/export/', views_import_export.export_employees, name='export_employees'),
    path('hr/employees/import/', views_import_export.import_employees, name='import_employees'),
    # Temp assignments
    path('assignments/', views_temp_assignments.temp_assignment_list, name='temp_assignment_list'),
    path('assignments/create/', views_temp_assignments.temp_assignment_create, name='temp_assignment_create'),
    path('assignments/<int:pk>/cancel/', views_temp_assignments.temp_assignment_cancel, name='temp_assignment_cancel'),
    # Attendance Codes Catalog
    path('attendance/codes/', views_attendance_codes.attendance_code_list, name='attendance_code_list'),
    path('attendance/codes/new/', views_attendance_codes.attendance_code_create, name='attendance_code_create'),
    path('attendance/codes/<int:pk>/edit/', views_attendance_codes.attendance_code_edit, name='attendance_code_edit'),
    path('attendance/codes/<int:pk>/delete/', views_attendance_codes.attendance_code_delete, name='attendance_code_delete'),
    # Global settings for attendance reconciliation
    path('attendance/settings/', views_attendance_codes.attendance_settings_view, name='attendance_settings'),
    # Bỏ Attendance Registration (NTSK - cá nhân)
    # Batch chấm công
    path('attendance/batch/', views_attendance_batch.batch_create_or_load, name='attendance_batch_create_or_load'),
    path('attendance/batch/<int:batch_id>/save/', views_attendance_batch.batch_save, name='attendance_batch_save'),
    path('attendance/batch/<int:batch_id>/commit/', views_attendance_batch.batch_commit, name='attendance_batch_commit'),
    path('attendance/committed/', views_attendance_batch.committed_view, name='attendance_committed_view'),
]