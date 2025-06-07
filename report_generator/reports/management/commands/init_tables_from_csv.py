import os
import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings

# ✅ Importiere deine Modelle hier:
from reports.models import LookupCategory, LookupValue, Dataset

# 📋 Liste der zu importierenden Tabellen
TABLES = [
    (LookupCategory, "lookupcategory.csv"),
    (LookupValue, "lookupvalue.csv"),
    (Dataset, "dataset.csv"),
]

# 📁 Ordner mit den CSV-Dateien (z. B. im Projekt-Root unter 'data/')
DATA_DIR = os.path.join(settings.BASE_DIR, "db_init")


class Command(BaseCommand):
    help = "Initialisiert die Datenbanktabellen mit CSV-Daten, falls sie leer sind."

    def handle(self, *args, **options):
        for model, csv_filename in TABLES:
            model_name = model.__name__
            if model.objects.exists():
                self.stdout.write(self.style.WARNING(f"{model_name}: Tabelle ist nicht leer, überspringe."))
                continue

            csv_path = os.path.join(DATA_DIR, csv_filename)
            if not os.path.exists(csv_path):
                self.stdout.write(self.style.ERROR(f"{model_name}: CSV-Datei {csv_filename} nicht gefunden."))
                continue

            try:
                df = pd.read_csv(csv_path, sep=";", dtype={"id": "Int64", "predecessor_id": "Int64"})
                self.stdout.write(f"{model_name}: Lese {len(df)} Zeilen aus {csv_filename} ...")
                objects = [model(**row.to_dict()) for _, row in df.iterrows()]

                with transaction.atomic():
                    model.objects.bulk_create(objects)
                    self.stdout.write(self.style.SUCCESS(f"{model_name}: {len(objects)} Objekte gespeichert."))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"{model_name}: Fehler beim Import – {e}"))
