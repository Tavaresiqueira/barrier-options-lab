from django.urls import include, path

urlpatterns = [path("", include("pricing.urls"))]
