from django.core.management.base import BaseCommand
from datetime import time
from apps.organization.models import JobTitle, ShiftTemplate

JOB_TITLES = [
    ("Giám Đốc", "GiamDoc"),
    ("Chủ Tịch", "ChuTich"),
    ("Phó Giám đốc", "PhoGiamDoc"),
    ("Trưởng Phòng", "TruongPhong"),
    ("Phó Trưởng Phòng", "PhoTruongPhong"),
    ("Trưởng Ban", "TruongBan"),
    ("Phó Ban", "PhoBan"),
    ("Trợ lý", "TroLy"),
    ("Nhân viên", "NhanVien"),
    ("Người lao động", "NguoiLaoDong"),
]

class Command(BaseCommand):
    help = "Seed JobTitles và ShiftTemplates mặc định"

    def handle(self, *args, **options):
        # Job titles
        for name, code in JOB_TITLES:
            JobTitle.objects.get_or_create(name=name, defaults={'code': code, 'is_active': True})

        # Shifts
        def upsert(code, name, typ, start_h, start_m, end_h, end_m, crosses=False, breaks=None):
            obj, _ = ShiftTemplate.objects.update_or_create(
                code=code,
                defaults={
                    'name': name, 'type': typ,
                    'start_time': time(start_h, start_m),
                    'end_time': time(end_h, end_m),
                    'crosses_midnight': crosses,
                    'breaks': breaks or [],
                    'is_active': True,
                }
            )

        upsert("MORNING", "Ca sáng", "MORNING", 6, 0, 13, 0, False, [])
        upsert("AFTERNOON", "Ca chiều", "AFTERNOON", 13, 0, 20, 0, False, [])
        upsert("NIGHT", "Ca tối", "NIGHT", 20, 0, 3, 0, True, [])
        upsert("DAY", "Ca ngày", "DAY", 7, 0, 17, 0, False, [{"start": "11:00", "end": "13:00"}])

        self.stdout.write(self.style.SUCCESS("Seeded JobTitles và ShiftTemplates."))