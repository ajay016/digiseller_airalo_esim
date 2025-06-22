from django.urls import path
from .import views





urlpatterns = [
    path('sync-airalo-data/', views.sync_airalo_data, name='sync_airalo_data'),
    path('api/unique_operators_count/', views.unique_operator_count, name='unique_operator_count'),
]