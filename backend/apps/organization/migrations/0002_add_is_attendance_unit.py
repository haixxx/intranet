from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('organization', '0001_initial'),  # Sửa lại cho đúng migration hiện có của app organization
    ]

    operations = [
        migrations.AddField(
            model_name='orgunit',
            name='is_attendance_unit',
            field=models.BooleanField(default=False),
        ),
    ]