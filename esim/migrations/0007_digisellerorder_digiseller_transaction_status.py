# Generated by Django 5.2.3 on 2025-06-27 08:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('esim', '0006_airaloorder_digisellerorder_airalo_order_airalosim'),
    ]

    operations = [
        migrations.AddField(
            model_name='digisellerorder',
            name='digiseller_transaction_status',
            field=models.IntegerField(choices=[(1, 'Not Verified'), (2, 'Delivered'), (3, 'Delivery Confirmed'), (4, 'Refuted'), (5, 'Delivery Pending')], default=1),
        ),
    ]
