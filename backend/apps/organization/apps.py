from django.apps import AppConfig


class OrganizationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.organization'
    verbose_name = "Cơ cấu tổ chức"

    def ready(self):
        """Đồng bộ cache phân quyền đơn vị khi cây tổ chức thay đổi."""
        from django.db.models.signals import post_delete, post_save
        from apps.organization.models import OrgUnit

        def clear_hr_org_scope_cache(sender, **kwargs):
            try:
                from apps.hr.services import clear_org_scope_cache

                clear_org_scope_cache()
            except Exception:
                # Không để lỗi dọn cache làm hỏng thao tác lưu/xóa OrgUnit.
                pass

        post_save.connect(
            clear_hr_org_scope_cache,
            sender=OrgUnit,
            dispatch_uid="organization_orgunit_clear_hr_scope_cache_save",
        )
        post_delete.connect(
            clear_hr_org_scope_cache,
            sender=OrgUnit,
            dispatch_uid="organization_orgunit_clear_hr_scope_cache_delete",
        )
