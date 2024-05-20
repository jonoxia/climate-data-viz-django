# Generated by Django 4.2 on 2024-05-20 22:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('load_shifting', '0003_hourly_generation_mix_cache'),
    ]

    operations = [
        migrations.CreateModel(
            name='AllPurposeCSVCache',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cache_function_name', models.TextField()),
                ('cached_date', models.DateTimeField(verbose_name='date cached')),
                ('key_params_json', models.TextField()),
                ('start_date', models.DateTimeField()),
                ('end_date', models.DateTimeField()),
                ('raw_csv', models.TextField()),
            ],
        ),
    ]