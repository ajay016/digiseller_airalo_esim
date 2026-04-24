import os
import sys
from io import StringIO
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.conf import settings

class Command(BaseCommand):
    help = 'Dumps database to esim_clean.json in UTF-8, excluding system models.'

    def handle(self, *args, **options):
        # 1. Define the output file path (Project Root)
        output_file = os.path.join(settings.BASE_DIR, 'digiseller_db.json')

        # 2. List of models to exclude (Standard clean dump practice)
        # Using excludes here is much faster than filtering the JSON later
        excludes = [
            "contenttypes.contenttype",
            "admin.logentry",
            "auth.permission",
            "sessions.session"
        ]

        self.stdout.write("⏳ Starting database dump...")

        # 3. Capture the data in memory (StringIO) instead of a temp file
        out = StringIO()
        
        try:
            # We call Django's native dumpdata but pipe the output to our variable 'out'
            call_command(
                'dumpdata',
                exclude=excludes, # This does the filtering for us!
                indent=4,
                stdout=out
            )

            # 4. Get the string content
            json_content = out.getvalue()

            # 5. Write to file forcing UTF-8 encoding
            # ensure_ascii=False is handled naturally by writing the string in utf-8 mode
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(json_content)

            self.stdout.write(self.style.SUCCESS(f"✅ Cleaned fixture written to: {output_file}"))
            self.stdout.write(self.style.SUCCESS(f"🚀 You can now run: python manage.py loaddata digiseller_db.json"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error during dump: {str(e)}"))
            sys.exit(1)