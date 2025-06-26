from django.apps import AppConfig


class AiraloConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'airalo'
    
    def ready(self):
        import airalo.tasks.airalo_tasks  # ← this ensures tasks are registered
