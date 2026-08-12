from django.db import models


class Calculation(models.Model):
    KIND_CHOICES = [
        ("barrier", "Barrier option"),
        ("collar", "Collar Up-and-In"),
        ("fence", "Fence Up-and-In"),
        ("nitro", "Nitro Call Up-and-Out"),
        ("double_up_ko", "Double Up KO"),
        ("box_ko", "Box KO"),
        ("box_bullet", "Box Bullet"),
        ("bullet", "Bullet"),
        ("bullet_plus", "Bullet Plus"),
        ("golden_bullet", "Golden Bullet"),
        ("collar_kiko", "Collar KI.KO"),
        ("fence_kiko", "Fence KI.KO"),
        ("call_kiko", "Call KI.KO"),
        ("digital", "Cash digital"),
        ("solver", "Zero-cost solver"),
        ("scenario", "Scenario analysis"),
    ]

    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    request_data = models.JSONField()
    result_data = models.JSONField()
    warnings = models.JSONField(default=list)
    model_version = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
