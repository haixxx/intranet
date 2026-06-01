from __future__ import annotations

import hashlib
import secrets

from django.db import models
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _
from .models_master_list import AttendanceDeviceMasterListV2  # noqa: F401,E402
from .models_manual_punch import AttendanceManualPunch  # noqa: F401,E402


class AttendanceDeviceAgentV2(models.Model):
    """
    Agent chạy trên Windows (service) dùng để pull/push dữ liệu từ thiết bị về server.

    Lưu ý:
    - Agent có thể self-register qua API, nhưng để vận hành rõ ràng, nên có màn hình backoffice
      để approve + cấp key + gán devices.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Chờ duyệt")
        ACTIVE = "ACTIVE", _("Đang hoạt động")
        DISABLED = "DISABLED", _("Vô hiệu hóa")

    name = models.CharField(max_length=128, verbose_name=_("Tên agent"))
    hostname = models.CharField(max_length=128, blank=True, default="", verbose_name=_("Hostname"))
    ip_address = models.CharField(max_length=64, blank=True, default="", verbose_name=_("IP"))
    version = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Phiên bản"))

    org_unit = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_agents_v2",
        verbose_name=_("Đơn vị/Phân xưởng (tham chiếu)"),
        help_text=_("Tham chiếu khu vực agent phụ trách (không bắt buộc)."),
    )

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, verbose_name=_("Trạng thái"))
    last_seen_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Lần online gần nhất"))

    notes = models.TextField(blank=True, default="", verbose_name=_("Ghi chú"))
    created_at = models.DateTimeField(default=dj_timezone.now, verbose_name=_("Tạo lúc"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Cập nhật lúc"))

    class Meta:
        verbose_name = _("Agent máy chấm công (v2)")
        verbose_name_plural = _("Agents máy chấm công (v2)")
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["hostname"]),
            models.Index(fields=["ip_address"]),
            models.Index(fields=["last_seen_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.hostname})"


class AttendanceDeviceAPIKeyV2(models.Model):
    """
    API key dùng để agent gọi API.
    - Dùng Bearer token: Authorization: Bearer <key>
    """

    agent = models.ForeignKey(
        AttendanceDeviceAgentV2,
        on_delete=models.CASCADE,
        related_name="api_keys",
        verbose_name=_("Agent"),
    )
    key = models.CharField(max_length=64, unique=True, verbose_name=_("API key"))
    is_active = models.BooleanField(default=True, verbose_name=_("Đang hiệu lực"))
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Hết hạn lúc"))

    created_at = models.DateTimeField(default=dj_timezone.now, verbose_name=_("Tạo lúc"))

    class Meta:
        verbose_name = _("API key của agent (v2)")
        verbose_name_plural = _("API keys của agent (v2)")
        indexes = [
            models.Index(fields=["agent", "is_active"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"Key(agent={self.agent_id}, active={self.is_active})"

    @staticmethod
    def generate_key() -> str:
        # 64 hex chars
        return secrets.token_hex(32)

    def is_valid_now(self) -> bool:
        if not self.is_active:
            return False
        if self.expires_at and dj_timezone.now() >= self.expires_at:
            return False
        # agent phải ACTIVE
        if self.agent.status != AttendanceDeviceAgentV2.Status.ACTIVE:
            return False
        return True


class AttendanceDeviceV2(models.Model):
    """
    Thiết bị máy chấm công.

    Ở v2, mapping nhân sự KHÔNG phụ thuộc device:
    - device_user_id là duy nhất toàn công ty
    - map nhân sự theo Employee.card_id
    """

    class Brand(models.TextChoices):
        ZKTECO = "ZKTeco", _("ZKTeco")
        OTHER = "Other", _("Khác")

    class ConnectMode(models.TextChoices):
        PULL = "PULL", _("Pull")
        PUSH = "PUSH", _("Push")
        IMPORT = "IMPORT", _("Import")

    class Status(models.TextChoices):
        ONLINE = "ONLINE", _("Online")
        OFFLINE = "OFFLINE", _("Offline")
        UNKNOWN = "UNKNOWN", _("Unknown")

    name = models.CharField(max_length=128, verbose_name=_("Tên thiết bị"))
    brand = models.CharField(max_length=32, choices=Brand.choices, default=Brand.ZKTECO, verbose_name=_("Hãng"))
    model = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Model"))
    serial_no = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Serial"))
    connect_mode = models.CharField(max_length=16, choices=ConnectMode.choices, default=ConnectMode.PULL, verbose_name=_("Chế độ kết nối"))

    host = models.CharField(max_length=128, verbose_name=_("Host/IP"))
    port = models.PositiveIntegerField(default=4370, verbose_name=_("Port"))

    # Field này tên "timezone" là hợp lý, nhưng phải tránh đụng tên import.
    timezone = models.CharField(max_length=64, default="Asia/Ho_Chi_Minh", verbose_name=_("Múi giờ"))

    org_unit = models.ForeignKey(
        "organization.OrgUnit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_devices_v2",
        verbose_name=_("Đơn vị/Phân xưởng"),
    )

    is_active = models.BooleanField(default=True, verbose_name=_("Hoạt động"))

    # Cấu hình SDK nếu cần
    sdk_profile = models.JSONField(blank=True, null=True, verbose_name=_("Cấu hình SDK"))
    # Cursor để agent lấy incremental
    last_cursor_json = models.JSONField(blank=True, null=True, verbose_name=_("Cursor lần cuối"))
    last_pull_at = models.DateTimeField(blank=True, null=True, verbose_name=_("Lần pull gần nhất"))

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UNKNOWN, verbose_name=_("Trạng thái"))
    notes = models.TextField(blank=True, default="", verbose_name=_("Ghi chú"))

    assigned_agent = models.ForeignKey(
        AttendanceDeviceAgentV2,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_devices",
        verbose_name=_("Agent phụ trách"),
    )

    created_at = models.DateTimeField(default=dj_timezone.now, verbose_name=_("Tạo lúc"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Cập nhật lúc"))

    class Meta:
        verbose_name = _("Thiết bị chấm công (v2)")
        verbose_name_plural = _("Thiết bị chấm công (v2)")
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["host", "port"]),
            models.Index(fields=["status"]),
            models.Index(fields=["assigned_agent"]),
            models.Index(fields=["org_unit"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.host}:{self.port})"


class AttendanceIngestLogV2(models.Model):
    """
    Log ingest để vận hành/điều tra.
    """

    device = models.ForeignKey(AttendanceDeviceV2, on_delete=models.CASCADE, related_name="ingest_logs", verbose_name=_("Thiết bị"))
    agent = models.ForeignKey(AttendanceDeviceAgentV2, on_delete=models.SET_NULL, null=True, blank=True, related_name="ingest_logs", verbose_name=_("Agent"))
    started_at = models.DateTimeField(verbose_name=_("Bắt đầu"))
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Kết thúc"))
    processed = models.PositiveIntegerField(default=0, verbose_name=_("Đã ghi"))
    duplicates = models.PositiveIntegerField(default=0, verbose_name=_("Trùng"))
    rejected = models.PositiveIntegerField(default=0, verbose_name=_("Bị loại"))
    success = models.BooleanField(default=False, verbose_name=_("Thành công"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("Lỗi"))
    accepted_cursor_snapshot = models.JSONField(blank=True, null=True, verbose_name=_("Cursor chấp nhận"))

    created_at = models.DateTimeField(default=dj_timezone.now, verbose_name=_("Tạo lúc"))

    class Meta:
        verbose_name = _("Log ingest (v2)")
        verbose_name_plural = _("Logs ingest (v2)")
        indexes = [
            models.Index(fields=["device", "started_at"]),
            models.Index(fields=["agent", "started_at"]),
            models.Index(fields=["success"]),
        ]

    def __str__(self) -> str:
        return f"IngestLog#{self.pk} dev={self.device_id} ok={self.success}"


class AttendanceRawPunchV2(models.Model):
    """
    Dữ liệu nháp/raw từ thiết bị. Đây là "nguồn sự thật" để reprocess.

    Lưu ý:
    - Không suy luận IN/OUT ở đây.
    - Không phụ thuộc vào đăng ký công.
    """

    class Method(models.TextChoices):
        FP = "FP", _("Vân tay")
        CARD = "CARD", _("Thẻ")
        FACE = "FACE", _("Khuôn mặt")
        OTHER = "OTHER", _("Khác")

    device = models.ForeignKey(AttendanceDeviceV2, on_delete=models.CASCADE, related_name="raw_punches", verbose_name=_("Thiết bị"))
    agent = models.ForeignKey(AttendanceDeviceAgentV2, on_delete=models.SET_NULL, null=True, blank=True, related_name="raw_punches", verbose_name=_("Agent"))
    batch_id = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Batch ID"))

    device_user_id = models.CharField(max_length=64, verbose_name=_("UID trên máy"))
    event_time_local = models.DateTimeField(verbose_name=_("Giờ local"))
    event_time_utc = models.DateTimeField(verbose_name=_("Giờ UTC"))

    method = models.CharField(max_length=16, choices=Method.choices, default=Method.OTHER, verbose_name=_("Phương thức"))
    device_event_id = models.CharField(max_length=128, blank=True, null=True, verbose_name=_("ID sự kiện trên thiết bị"))
    dedup_hash = models.CharField(max_length=64, verbose_name=_("Hash chống trùng"))

    meta_json = models.JSONField(blank=True, null=True, verbose_name=_("Metadata (JSON)"))
    ingested_at = models.DateTimeField(default=dj_timezone.now, verbose_name=_("Nhận lúc"))

    # Đánh dấu raw đã được chuẩn hoá hay chưa (để normalize idempotent)
    normalized_punch = models.ForeignKey(
        "attendance_devices_v2.AttendanceNormalizedPunchV2",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_raws",
        verbose_name=_("Punch chuẩn hoá"),
    )
    normalized_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Chuẩn hoá lúc"))

    class Meta:
        verbose_name = _("Punch raw (v2)")
        verbose_name_plural = _("Punches raw (v2)")
        constraints = [
            models.UniqueConstraint(
                fields=["device", "device_event_id"],
                name="uniq_v2_device_event_id",
                condition=~models.Q(device_event_id__isnull=True),
            ),
            models.UniqueConstraint(
                fields=["device", "dedup_hash"],
                name="uniq_v2_device_dedup_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["device_user_id", "event_time_utc"]),
            models.Index(fields=["device", "event_time_utc"]),
            models.Index(fields=["ingested_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.device_id}:{self.device_user_id} @{self.event_time_local}"

    @staticmethod
    def compute_dedup_hash(
        device_id: int,
        device_user_id: str,
        event_time_local_iso: str,
        method: str,
    ) -> str:
        """
        Hash chống trùng trong trường hợp không có device_event_id.
        """
        base = f"{device_id}::{device_user_id}::{event_time_local_iso}::{method}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()


class AttendanceNormalizedPunchV2(models.Model):
    """
    Punch đã chuẩn hoá:
    - Map employee theo Employee.card_id
    - Dedupe cross-device theo cluster_minutes

    Đây là đầu vào chuẩn cho compute đối chiếu AttendanceRegistration/Batch.
    """

    class Method(models.TextChoices):
        FP = "FP", _("Vân tay")
        CARD = "CARD", _("Thẻ")
        FACE = "FACE", _("Khuôn mặt")
        OTHER = "OTHER", _("Khác")

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.CASCADE,
        related_name="normalized_punches_v2",
        verbose_name=_("Nhân viên"),
    )

    canonical_time_utc = models.DateTimeField(verbose_name=_("Thời điểm chuẩn (UTC)"))

    best_device = models.ForeignKey(
        AttendanceDeviceV2,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="normalized_punches_v2",
        verbose_name=_("Thiết bị ưu tiên"),
    )

    method = models.CharField(max_length=16, choices=Method.choices, default=Method.OTHER, verbose_name=_("Phương thức"))
    source_count = models.PositiveIntegerField(default=1, verbose_name=_("Số raw đã gộp"))

    # Lưu danh sách source để debug (tạm)
    sources_json = models.JSONField(blank=True, null=True, verbose_name=_("Nguồn (JSON)"))

    created_at = models.DateTimeField(default=dj_timezone.now, verbose_name=_("Tạo lúc"))

    class Meta:
        verbose_name = _("Punch chuẩn hoá (v2)")
        verbose_name_plural = _("Punch chuẩn hoá (v2)")
        indexes = [
            models.Index(fields=["employee", "canonical_time_utc"]),
            models.Index(fields=["canonical_time_utc"]),
        ]

    def __str__(self) -> str:
        return f"Emp#{self.employee_id} @{self.canonical_time_utc}"


class AttendancePunchMatchV2(models.Model):
    """
    Audit đối chiếu punch -> mốc đăng ký.

    Mỗi lần compute/recompute tạo record mới với compute_run_id/compute_version.
    """

    class TargetField(models.TextChoices):
        IN1 = "IN1", _("IN1")
        OUT1 = "OUT1", _("OUT1")
        IN2 = "IN2", _("IN2")
        OUT2 = "OUT2", _("OUT2")

    class Status(models.TextChoices):
        MATCHED = "MATCHED", _("Khớp")
        MISSING = "MISSING", _("Thiếu")
        OUT_OF_WINDOW = "OUT_OF_WINDOW", _("Ngoài cửa sổ")
        AMBIGUOUS = "AMBIGUOUS", _("Mơ hồ (nhiều lựa chọn)")
        ONLY_ONE_PUNCH = "ONLY_ONE_PUNCH", _("Chỉ có 1 lần chấm")
        PUNCH_WHILE_NONWORK = "PUNCH_WHILE_NONWORK", _("Có chấm nhưng chế độ không đi làm")
        SHIFT_MISMATCH_SUSPECTED = "SHIFT_MISMATCH_SUSPECTED", _("Nghi sai ca/đăng ký")
        EXEMPT = "EXEMPT", _("Đặc cách (không yêu cầu chấm máy)")

    work_date = models.DateField(verbose_name=_("Ngày làm việc"))
    employee = models.ForeignKey("hr.Employee", on_delete=models.CASCADE, related_name="punch_matches_v2", verbose_name=_("Nhân viên"))

    target_field = models.CharField(max_length=8, choices=TargetField.choices, verbose_name=_("Mốc"))
    target_time_local = models.DateTimeField(verbose_name=_("Giờ mục tiêu (local)"))

    matched_punch = models.ForeignKey(
        AttendanceNormalizedPunchV2,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matches_v2",
        verbose_name=_("Punch khớp"),
    )
    matched_time_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Giờ khớp (local)"))
    delta_seconds = models.IntegerField(null=True, blank=True, verbose_name=_("Lệch (giây)"))

    status = models.CharField(max_length=32, choices=Status.choices, default=Status.MISSING, verbose_name=_("Trạng thái"))
    notes = models.TextField(blank=True, default="", verbose_name=_("Ghi chú"))

    # Versioning cho compute
    compute_run_id = models.CharField(max_length=64, blank=True, default="", verbose_name=_("Compute run id"))
    compute_version = models.PositiveIntegerField(default=1, verbose_name=_("Phiên bản"))

    created_at = models.DateTimeField(default=dj_timezone.now, verbose_name=_("Tạo lúc"))

    class Meta:
        verbose_name = _("Audit khớp punch (v2)")
        verbose_name_plural = _("Audit khớp punch (v2)")
        indexes = [
            models.Index(fields=["work_date", "employee"]),
            models.Index(fields=["employee", "work_date"]),
            models.Index(fields=["status"]),
            models.Index(fields=["compute_run_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.work_date} emp={self.employee_id} {self.target_field} {self.status}"

class AttendanceDeviceStatusReportV2(models.Model):
    """
    Báo cáo trạng thái realtime/health-check từ Attendance Agent V2.

    Agent gửi định kỳ để server/dashboard biết trạng thái thật của từng máy:
    ONLINE/OFFLINE/RECONNECTING/PAUSED_BACKFILL/PAUSED_TIME_SYNC/REALTIME_UNAVAILABLE/ERROR.
    """

    class RealtimeStatus(models.TextChoices):
        ONLINE = "ONLINE", _("Online")
        OFFLINE = "OFFLINE", _("Offline")
        RECONNECTING = "RECONNECTING", _("Đang kết nối lại")
        PAUSED_BACKFILL = "PAUSED_BACKFILL", _("Tạm dừng để backfill")
        PAUSED_TIME_SYNC = "PAUSED_TIME_SYNC", _("Tạm dừng để đồng bộ giờ")
        REALTIME_UNAVAILABLE = "REALTIME_UNAVAILABLE", _("Không hỗ trợ realtime")
        ERROR = "ERROR", _("Lỗi")

    device = models.ForeignKey(
        AttendanceDeviceV2,
        on_delete=models.CASCADE,
        related_name="status_reports_v2",
        verbose_name=_("Thiết bị"),
    )
    agent = models.ForeignKey(
        AttendanceDeviceAgentV2,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="device_status_reports_v2",
        verbose_name=_("Agent"),
    )

    realtime_status = models.CharField(
        max_length=32,
        choices=RealtimeStatus.choices,
        default=RealtimeStatus.ONLINE,
        db_index=True,
        verbose_name=_("Trạng thái realtime"),
    )
    last_realtime_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Realtime cuối"))
    last_event_time_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Event cuối trên máy"))
    last_device_seen_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name=_("Lần thấy máy"))
    pending_backfill_required = models.BooleanField(default=False, db_index=True, verbose_name=_("Cần backfill"))
    drift_seconds = models.IntegerField(null=True, blank=True, verbose_name=_("Lệch giờ máy (giây)"))
    last_error = models.TextField(blank=True, default="", verbose_name=_("Lỗi cuối"))

    payload_json = models.JSONField(blank=True, null=True, verbose_name=_("Payload gốc"))
    reported_at = models.DateTimeField(default=dj_timezone.now, db_index=True, verbose_name=_("Server nhận lúc"))

    class Meta:
        verbose_name = _("Báo cáo trạng thái thiết bị (v2)")
        verbose_name_plural = _("Báo cáo trạng thái thiết bị (v2)")
        indexes = [
            models.Index(fields=["device", "-reported_at", "-id"], name="adv2_st_dev_latest_idx"),
            models.Index(fields=["agent", "-reported_at"], name="adv2_st_agent_time_idx"),
            models.Index(fields=["realtime_status", "reported_at"], name="adv2_st_status_time_idx"),
        ]

    def __str__(self) -> str:
        return f"StatusReport#{self.pk} dev={self.device_id} {self.realtime_status}"


class AttendanceDeviceBackfillReportV2(models.Model):
    """
    Báo cáo kết quả backfill từ Attendance Agent V2.
    Lưu mỗi lần chạy window backfill để dashboard biết backfill có thành công không.
    """

    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", _("Thành công")
        PARTIAL_PENDING = "PARTIAL_PENDING", _("Một phần đang pending")
        FAILED = "FAILED", _("Thất bại")
        SKIPPED = "SKIPPED", _("Bỏ qua")

    device = models.ForeignKey(
        AttendanceDeviceV2,
        on_delete=models.CASCADE,
        related_name="backfill_reports_v2",
        verbose_name=_("Thiết bị"),
    )
    agent = models.ForeignKey(
        AttendanceDeviceAgentV2,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="backfill_reports_v2",
        verbose_name=_("Agent"),
    )

    window_name = models.CharField(max_length=64, blank=True, default="", db_index=True, verbose_name=_("Window"))
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.SUCCESS, db_index=True, verbose_name=_("Trạng thái"))
    started_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Bắt đầu"))
    finished_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name=_("Kết thúc"))
    duration_seconds = models.IntegerField(null=True, blank=True, verbose_name=_("Thời gian chạy (giây)"))

    days = models.PositiveIntegerField(default=0, verbose_name=_("Số ngày backfill"))
    from_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Từ local"))
    to_local = models.DateTimeField(null=True, blank=True, verbose_name=_("Đến local"))

    read_total = models.PositiveIntegerField(default=0, verbose_name=_("Tổng log đọc"))
    filtered = models.PositiveIntegerField(default=0, verbose_name=_("Log sau lọc"))
    sent_batches = models.PositiveIntegerField(default=0, verbose_name=_("Batch đã gửi"))
    pending_batches = models.PositiveIntegerField(default=0, verbose_name=_("Batch pending"))
    processed = models.PositiveIntegerField(default=0, verbose_name=_("Server ghi"))
    duplicates = models.PositiveIntegerField(default=0, verbose_name=_("Trùng"))
    rejected = models.PositiveIntegerField(default=0, verbose_name=_("Bị loại"))
    errors = models.PositiveIntegerField(default=0, verbose_name=_("Số lỗi"))

    error_code = models.CharField(max_length=64, blank=True, default="", db_index=True, verbose_name=_("Mã lỗi"))
    error_message = models.TextField(blank=True, default="", verbose_name=_("Thông báo lỗi"))
    need_retry = models.BooleanField(default=False, db_index=True, verbose_name=_("Cần retry"))
    need_backfill = models.BooleanField(default=False, db_index=True, verbose_name=_("Cần backfill"))

    payload_json = models.JSONField(blank=True, null=True, verbose_name=_("Payload gốc"))
    reported_at = models.DateTimeField(default=dj_timezone.now, db_index=True, verbose_name=_("Server nhận lúc"))

    class Meta:
        verbose_name = _("Báo cáo backfill thiết bị (v2)")
        verbose_name_plural = _("Báo cáo backfill thiết bị (v2)")
        indexes = [
            models.Index(fields=["device", "-reported_at", "-id"], name="adv2_bf_dev_latest_idx"),
            models.Index(fields=["agent", "-reported_at"], name="adv2_bf_agent_time_idx"),
            models.Index(fields=["status", "reported_at"], name="adv2_bf_status_time_idx"),
            models.Index(fields=["need_retry", "reported_at"], name="adv2_bf_retry_time_idx"),
        ]

    def __str__(self) -> str:
        return f"BackfillReport#{self.pk} dev={self.device_id} {self.status}"

