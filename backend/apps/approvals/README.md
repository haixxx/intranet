# Module Phê duyệt (Approvals)

- Việt hóa đầy đủ, dùng i18n.
- Luồng "Phê duyệt sửa chấm công" (attendance_correction_approval) được seed với:
  - admin_unit_id: 12
  - Bước 1: Lãnh đạo đơn vị của NSTK (DEPT_HEADS_FROM_EMPLOYEE_UNIT, quorum=GROUP_ANY_ALL, role_chain HEAD→DEPUTY→IN_CHARGE)
  - Bước 2: HR đích danh (EXPLICIT_USERS) với user_id=649

## Sử dụng nhanh

- Seed luồng:
  - gọi `seed_attendance_correction_flow(admin_unit_id=12, hr_user_id=649, actor=request.user)`
- Tạo yêu cầu:
  - gọi `create_request(flow_key="attendance_correction_approval", requester=request.user, object_type="attendance_correction", object_id="REQ-0001", title="Đề nghị sửa chấm công", unit_id=<unit_id của NSTK>, metadata_json={...})`

## Ghi chú

- Chưa bao gồm resolver runtime, approve/reject/delegate; đây là skeleton để bạn review cấu trúc và Việt hóa.
- Sau khi xác nhận, sẽ bổ sung:
  - Resolver cho từng StepType
  - API và UI: Danh sách phê duyệt, Chi tiết yêu cầu, Flow Builder
  - Thông báo, SLA, Audit đầy đủ