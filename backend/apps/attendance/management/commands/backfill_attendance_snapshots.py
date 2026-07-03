from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.attendance.models_batch import AttendanceCommitItem


SNAPSHOT_FIELDS = [
    "code_snapshot",
    "label_snapshot",
    "system_role_snapshot",
    "work_credit_snapshot",
    "paid_credit_snapshot",
    "bonus_credit_snapshot",
    "registered_hours_snapshot",
    "meal_allowance_count_snapshot",
    "is_work_snapshot",
    "registered_in1_snapshot",
    "registered_out1_snapshot",
    "registered_in2_snapshot",
    "registered_out2_snapshot",
]


@dataclass
class BackfillStats:
    scanned: int = 0
    would_update: int = 0
    updated: int = 0
    skipped_has_snapshot: int = 0
    skipped_no_code: int = 0
    warnings: int = 0
    errors: int = 0


class Command(BaseCommand):
    help = (
        "Backfill snapshot fields for AttendanceCommitItem rows. "
        "Default mode is dry-run; pass --apply to write changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write snapshot values to database. Without this option, command runs in dry-run mode.",
        )
        parser.add_argument(
            "--from-date",
            dest="from_date",
            help="Lower bound commit work_date in YYYY-MM-DD.",
        )
        parser.add_argument(
            "--to-date",
            dest="to_date",
            help="Upper bound commit work_date in YYYY-MM-DD.",
        )
        parser.add_argument(
            "--unit-id",
            dest="unit_id",
            type=int,
            help="Only process one OrgUnit id.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Rebuild snapshots even when code_snapshot already exists. "
                "Use carefully; this can change historical snapshot meaning."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional maximum number of commit items to scan. 0 means no limit.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Bulk update batch size when --apply is used.",
        )
        parser.add_argument(
            "--show-samples",
            type=int,
            default=20,
            help="Number of sample rows/warnings to print.",
        )

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        force = bool(options["force"])
        limit = int(options["limit"] or 0)
        batch_size = int(options["batch_size"] or 500)
        show_samples = int(options["show_samples"] or 20)

        if batch_size <= 0:
            raise CommandError("--batch-size must be greater than 0")

        qs = AttendanceCommitItem.objects.select_related(
            "commit",
            "commit__unit",
            "employee",
            "code",
            "bs_peer_unit",
        ).order_by("commit__work_date", "commit__unit_id", "employee_id", "id")

        from_date = self._parse_date(options.get("from_date"), "--from-date")
        to_date = self._parse_date(options.get("to_date"), "--to-date")
        if from_date:
            qs = qs.filter(commit__work_date__gte=from_date)
        if to_date:
            qs = qs.filter(commit__work_date__lte=to_date)
        if options.get("unit_id"):
            qs = qs.filter(commit__unit_id=options["unit_id"])
        if limit > 0:
            qs = qs[:limit]

        stats = BackfillStats()
        samples: list[str] = []
        warnings: list[str] = []
        to_update: list[AttendanceCommitItem] = []

        started_at = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
        self.stdout.write(self.style.MIGRATE_HEADING("Backfill AttendanceCommitItem snapshots"))
        self.stdout.write(f"Started at: {started_at}")
        self.stdout.write(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
        self.stdout.write(f"Force rebuild: {'YES' if force else 'NO'}")
        if from_date or to_date or options.get("unit_id"):
            self.stdout.write(
                "Scope: "
                f"from={from_date or '-'}; to={to_date or '-'}; unit_id={options.get('unit_id') or '-'}"
            )
        else:
            self.stdout.write("Scope: all commit items")

        iterator: Iterable[AttendanceCommitItem] = qs.iterator(chunk_size=batch_size)

        try:
            with transaction.atomic():
                for item in iterator:
                    stats.scanned += 1

                    if not item.code_id or not item.code:
                        stats.skipped_no_code += 1
                        if len(warnings) < show_samples:
                            warnings.append(self._row_label(item) + ": skipped, missing attendance code")
                        continue

                    if not force and not self._needs_backfill(item):
                        stats.skipped_has_snapshot += 1
                        continue

                    if item.bs_direction == item.BSDirection.OUT and getattr(item.code, "code", "") != "BS":
                        stats.warnings += 1
                        if len(warnings) < show_samples:
                            warnings.append(
                                self._row_label(item)
                                + f": BS OUT but code is {getattr(item.code, 'code', '')!r}; snapshot is built from current code."
                            )

                    before = self._snapshot_tuple(item)
                    self._apply_snapshot_values(item)
                    after = self._snapshot_tuple(item)

                    if before == after and not force:
                        stats.skipped_has_snapshot += 1
                        continue

                    stats.would_update += 1
                    if len(samples) < show_samples:
                        samples.append(self._sample_line(item))

                    if apply:
                        to_update.append(item)
                        if len(to_update) >= batch_size:
                            AttendanceCommitItem.objects.bulk_update(to_update, SNAPSHOT_FIELDS, batch_size=batch_size)
                            stats.updated += len(to_update)
                            to_update.clear()

                if apply and to_update:
                    AttendanceCommitItem.objects.bulk_update(to_update, SNAPSHOT_FIELDS, batch_size=batch_size)
                    stats.updated += len(to_update)
                    to_update.clear()

                if not apply:
                    # Roll back any in-memory model state never reached DB because we did not call save/bulk_update.
                    # Keep the transaction explicit so accidental writes introduced later won't persist in dry-run.
                    transaction.set_rollback(True)
        except Exception as exc:  # pragma: no cover - management command safety net
            stats.errors += 1
            raise CommandError(f"Backfill failed: {exc}") from exc

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_LABEL("Summary"))
        self.stdout.write(f"Scanned commit items: {stats.scanned}")
        self.stdout.write(f"Already had snapshot / skipped: {stats.skipped_has_snapshot}")
        self.stdout.write(f"Skipped without code: {stats.skipped_no_code}")
        self.stdout.write(f"Would update: {stats.would_update}")
        self.stdout.write(f"Updated: {stats.updated if apply else 0}")
        self.stdout.write(f"Warnings: {stats.warnings + stats.skipped_no_code}")

        if samples:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_LABEL("Sample rows"))
            for line in samples:
                self.stdout.write("- " + line)

        if warnings:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Warnings"))
            for line in warnings:
                self.stdout.write("- " + line)

        if not apply:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run only. No database rows were changed. Re-run with --apply to write snapshots."
                )
            )
        else:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Backfill completed."))

    def _parse_date(self, value: str | None, option_name: str):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError(f"{option_name} must be in YYYY-MM-DD format") from exc

    def _needs_backfill(self, item: AttendanceCommitItem) -> bool:
        """
        Only process rows that look like they never had a proper snapshot.
        Keep this conservative to avoid rewriting historical rows accidentally.
        """
        if not item.code_snapshot:
            return True
        if not item.label_snapshot:
            return True
        # If row has registered times but all registered_*_snapshot are empty, it is likely partially missing.
        has_row_marks = bool(item.in1 or item.out1 or item.in2 or item.out2)
        has_snapshot_marks = bool(
            item.registered_in1_snapshot
            or item.registered_out1_snapshot
            or item.registered_in2_snapshot
            or item.registered_out2_snapshot
        )
        if has_row_marks and not has_snapshot_marks and item.bs_direction != item.BSDirection.OUT:
            return True
        return False

    def _apply_snapshot_values(self, item: AttendanceCommitItem) -> None:
        """
        Build snapshot from current commit item + current AttendanceCode.
        This intentionally does not modify non-snapshot fields such as code, in/out, overtime, bs_direction.
        """
        item.apply_code_snapshot()

        # BS đi tại đơn vị gốc không có mốc đăng ký để đối chiếu tại đơn vị gốc.
        if item.bs_direction == item.BSDirection.OUT:
            item.registered_in1_snapshot = None
            item.registered_out1_snapshot = None
            item.registered_in2_snapshot = None
            item.registered_out2_snapshot = None

    def _snapshot_tuple(self, item: AttendanceCommitItem) -> tuple:
        return tuple(getattr(item, field) for field in SNAPSHOT_FIELDS)

    def _row_label(self, item: AttendanceCommitItem) -> str:
        unit_code = getattr(getattr(item, "commit", None), "unit", None)
        unit_text = getattr(unit_code, "code", "?")
        work_date = getattr(getattr(item, "commit", None), "work_date", "?")
        employee_code = getattr(getattr(item, "employee", None), "employee_code", None) or getattr(
            getattr(item, "employee", None), "code", None
        ) or item.employee_id
        return f"commit_item={item.id}; date={work_date}; unit={unit_text}; employee={employee_code}"

    def _sample_line(self, item: AttendanceCommitItem) -> str:
        code = item.code_snapshot or getattr(item.code, "code", "")
        return (
            self._row_label(item)
            + f"; code_snapshot={code}; "
            + f"marks=({item.registered_in1_snapshot or '-'}, {item.registered_out1_snapshot or '-'}, "
            + f"{item.registered_in2_snapshot or '-'}, {item.registered_out2_snapshot or '-'})"
        )
