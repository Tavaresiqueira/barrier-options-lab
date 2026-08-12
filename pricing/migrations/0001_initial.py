from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Calculation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("barrier", "Barrier option"), ("collar", "Collar Up-and-In"), ("fence", "Fence Up-and-In"), ("solver", "Zero-cost solver"), ("scenario", "Scenario analysis")], max_length=20)),
                ("request_data", models.JSONField()),
                ("result_data", models.JSONField()),
                ("warnings", models.JSONField(default=list)),
                ("model_version", models.CharField(max_length=30)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        )
    ]
