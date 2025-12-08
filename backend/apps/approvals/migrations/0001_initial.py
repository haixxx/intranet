from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApprovalFlow",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("flow_key", models.CharField(max_length=100, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True, default="")),
                ("status", models.CharField(max_length=20, default="DRAFT")),
                ("scope_unit_id", models.IntegerField(blank=True, null=True)),
                ("admin_unit_id", models.IntegerField(blank=True, null=True)),
                ("settings_json", models.JSONField(default=dict)),
                ("current_version", models.IntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="auth.user")),
            ],
        ),
        migrations.CreateModel(
            name="ApprovalFlowVersion",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("version", models.IntegerField()),
                ("steps_json", models.JSONField()),
                ("is_active", models.BooleanField(default=False)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True, default="")),
                ("flow", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="versions", to="approvals.approvalflow")),
                ("published_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approval_flow_versions_published", to="auth.user")),
            ],
        ),
        migrations.AlterUniqueTogether(
            name="approvalflowversion",
            unique_together={("flow", "version")},
        ),
        migrations.CreateModel(
            name="ApprovalRequest",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("object_type", models.CharField(max_length=100)),
                ("object_id", models.CharField(max_length=100)),
                ("title", models.CharField(max_length=255)),
                ("unit_id", models.IntegerField(blank=True, null=True)),
                ("status", models.CharField(max_length=20, default="DRAFT")),
                ("metadata_json", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("flow", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="requests", to="approvals.approvalflow")),
                ("flow_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="requests", to="approvals.approvalflowversion")),
                ("requester", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="approval_requests_requested", to="auth.user")),
            ],
        ),
        migrations.CreateModel(
            name="ApprovalStep",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("order_index", models.IntegerField()),
                ("type", models.CharField(max_length=40)),
                ("label", models.CharField(default="", max_length=255)),
                ("quorum", models.CharField(max_length=20, default="ALL")),
                ("resolver_config", models.JSONField(default=dict)),
                ("allow_overrides", models.BooleanField(default=False)),
                ("status", models.CharField(max_length=20, default="PENDING")),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="steps", to="approvals.approvalrequest")),
            ],
            options={"ordering": ["order_index"]},
        ),
        migrations.CreateModel(
            name="ApprovalSigner",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("role_title", models.CharField(blank=True, default="", max_length=100)),
                ("unit_id", models.IntegerField(blank=True, null=True)),
                ("group_key", models.CharField(blank=True, default="", max_length=100)),
                ("is_required", models.BooleanField(default=True)),
                ("source", models.CharField(max_length=20, default="RESOLVED")),
                ("status", models.CharField(max_length=20, default="PENDING")),
                ("acted_at", models.DateTimeField(blank=True, null=True)),
                ("step", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="signers", to="approvals.approvalstep")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="approval_signers", to="auth.user")),
                ("delegated_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approval_signers_delegated", to="auth.user")),
            ],
        ),
        migrations.CreateModel(
            name="ApprovalAction",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("action", models.CharField(max_length=20)),
                ("comment", models.TextField(blank=True, default="")),
                ("meta_json", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="approval_actions", to="auth.user")),
                ("request", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="actions", to="approvals.approvalrequest")),
                ("signer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="actions", to="approvals.approvalsigner")),
                ("step", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="actions", to="approvals.approvalstep")),
            ],
        ),
    ]