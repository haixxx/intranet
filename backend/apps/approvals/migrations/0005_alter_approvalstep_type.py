# Generated manually for approvals runtime hardening.

from django.db import migrations, models
from django.utils.translation import gettext_lazy as _


class Migration(migrations.Migration):

    dependencies = [
        ("approvals", "0004_approvalrequest_content_html_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="approvalstep",
            name="type",
            field=models.CharField(
                max_length=40,
                choices=[
                    ("REQUESTER", _("Người lập")),
                    ("PARTICIPANTS_LIST", _("Người tham gia")),
                    ("DEPT_HEADS_FROM_EMPLOYEE_UNIT", _("Lãnh đạo đơn vị của NSTK")),
                    ("UNIT_LEADERS", _("Lãnh đạo đơn vị")),
                    ("STATIC_ROLE", _("Chức danh cố định")),
                    ("EXPLICIT_USERS", _("Chỉ định người ký")),
                ],
            ),
        ),
    ]
