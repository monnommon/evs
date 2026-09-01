from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("polls", "0001_initial")]

    operations = [
        migrations.AddConstraint(
            model_name="vote",
            constraint=models.UniqueConstraint(
                condition=models.Q(anonymous_session__isnull=False),
                fields=("anonymous_session",),
                name="uniq_vote_per_anonymous_session",
            ),
        ),
    ]
