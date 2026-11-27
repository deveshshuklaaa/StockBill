"""Shop logo on the Business Profile, stored in the database (Release B2).

Also carries over the logo the PDF used to read from disk
(billing/static/billing/images/logo.jpg): if a profile exists with no logo
and that file is present, it is normalised (billing.logo) and stored. Both
conditions are checked, so this is a no-op on fresh installs and stays safe
once the file is removed from the repository. Reversing simply drops the
columns.
"""

from pathlib import Path

from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

LEGACY_LOGO_PATH = Path(settings.BASE_DIR) / "billing" / "static" / "billing" / "images" / "logo.jpg"


def load_legacy_logo(apps, schema_editor):
    from billing.logo import STORED_CONTENT_TYPE, LogoError, normalize_logo

    BusinessProfile = apps.get_model("billing", "BusinessProfile")
    profile = BusinessProfile.objects.order_by("pk").first()
    if profile is None or profile.logo:
        return
    path = Path(LEGACY_LOGO_PATH)
    if not path.is_file():
        return
    try:
        png = normalize_logo(path.read_bytes())
    except LogoError:
        return  # leave the profile without a logo rather than fail the deploy
    profile.logo = png
    profile.logo_content_type = STORED_CONTENT_TYPE
    profile.logo_updated_at = timezone.now()
    profile.save(update_fields=["logo", "logo_content_type", "logo_updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0022_creditnote_destination_warehouse"),
    ]

    operations = [
        migrations.AddField(
            model_name="businessprofile",
            name="logo",
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="businessprofile",
            name="logo_content_type",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="businessprofile",
            name="logo_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(load_legacy_logo, migrations.RunPython.noop),
    ]
