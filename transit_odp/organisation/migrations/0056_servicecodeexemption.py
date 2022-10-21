# Generated by Django 3.2.13 on 2022-09-08 15:46

import django.db.models.deletion
import django_extensions.db.fields
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organisation", "0055_avlcompliancecache"),
    ]

    operations = [
        migrations.CreateModel(
            name="ServiceCodeExemption",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    django_extensions.db.fields.CreationDateTimeField(
                        auto_now_add=True, verbose_name="created"
                    ),
                ),
                (
                    "modified",
                    django_extensions.db.fields.ModificationDateTimeField(
                        auto_now=True, verbose_name="modified"
                    ),
                ),
                (
                    "registration_code",
                    models.IntegerField(
                        help_text=(
                            "The part of the service code after the licence prefix"
                        )
                    ),
                ),
                (
                    "justification",
                    models.CharField(
                        blank=True,
                        help_text="Justification for exemption",
                        max_length=140,
                    ),
                ),
                (
                    "exempted_by",
                    models.ForeignKey(
                        help_text="The user that added this exemption",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="service_code_exemptions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "licence",
                    models.ForeignKey(
                        help_text="Organisation licence",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="service_code_exemptions",
                        to="organisation.licence",
                    ),
                ),
            ],
            options={
                "get_latest_by": "modified",
                "abstract": False,
            },
        ),
    ]
