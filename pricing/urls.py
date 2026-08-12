from django.urls import path

from . import views

app_name = "pricing"
urlpatterns = [
    path("", views.index, name="index"),
    path("api/v1/barriers/price/", views.price_barrier, name="price_barrier"),
    path("api/v1/packages/price/", views.price_package, name="price_package"),
    path("api/v1/packages/snapshot/", views.package_snapshot, name="package_snapshot"),
    path("api/v1/packages/monitoring-equivalence/", views.package_monitoring_equivalence, name="package_monitoring_equivalence"),
    path("api/v1/solvers/zero-cost/", views.solve, name="solve"),
    path("api/v1/scenarios/", views.scenarios, name="scenarios"),
    path("api/v1/calculations/", views.history, name="history"),
    path("api/v1/calculations/<int:calculation_id>/learning/paths/", views.learning_paths, name="learning_paths"),
    path("api/v1/calculations/<int:calculation_id>/learning/quote/", views.learning_quote, name="learning_quote"),
    path("api/v1/calculations/<int:calculation_id>/learning/volatility/", views.learning_volatility, name="learning_volatility"),
    path("api/v1/calculations/<int:calculation_id>/learning/hedge/", views.learning_hedge, name="learning_hedge"),
    path("api/v1/calculations/<int:calculation_id>/learning/attribution/", views.learning_attribution, name="learning_attribution"),
    path("api/v1/market-data/options-chain/", views.chain, name="chain"),
    path("api/v1/market-data/quotes/", views.quotes, name="quotes"),
    path("api/v1/market-data/di-curve/", views.rates, name="rates"),
]
