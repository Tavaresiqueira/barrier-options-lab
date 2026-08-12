import json
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import Calculation
from .services.market_data import MarketDataError, option_chain, option_quotes
from .services.monitoring import monitoring_equivalence
from .services.learning import dealer_quote, hedge_simulator, path_explorer, pnl_attribution, volatility_lab
from .services.monte_carlo import MonteCarloBarrierEngine
from .services.solver import solve_zero_cost
from .services.structures import maturity_scenarios, price_structure
from .services.validation import InputError, parse_contract


@ensure_csrf_cookie
def index(request):
    return render(request, "pricing/index.html")


def _payload(request):
    try:
        value = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        raise InputError({"body": ["Request body must be valid JSON."]}) from None
    if not isinstance(value, dict):
        raise InputError({"body": ["Request body must be a JSON object."]})
    return value


def _error(exc, status=400):
    if isinstance(exc, InputError):
        return JsonResponse({"error": {"code": "validation_error", "message": "Invalid request.", "fields": exc.errors}}, status=status)
    return JsonResponse({"error": {"code": "market_data_error", "message": str(exc), "fields": {}}}, status=502)


def _save(kind, request_data, result):
    return Calculation.objects.create(
        kind=kind,
        request_data=request_data,
        result_data=result,
        warnings=result.get("warnings", []),
        model_version=settings.APP_MODEL_VERSION,
    )


@require_POST
def price_barrier(request):
    try:
        data = _payload(request)
        contract = parse_contract(data)
        result = MonteCarloBarrierEngine().price(contract)
        calculation = _save("barrier", data, result)
        result["calculation_id"] = calculation.id
        return JsonResponse({"data": result}, status=201)
    except InputError as exc:
        return _error(exc)


@require_POST
def price_package(request):
    try:
        data = _payload(request)
        kind = data.get("kind")
        contract = parse_contract(data.get("barrier_contract", data))
        result = price_structure(kind, data, contract)
        result["scenario_analysis"] = maturity_scenarios(kind, data, contract, result)
        calculation = _save(kind, data, result)
        result["calculation_id"] = calculation.id
        return JsonResponse({"data": result}, status=201)
    except InputError as exc:
        return _error(exc)


@require_POST
def package_snapshot(request):
    """Reprice a package at an exploratory spot without persisting a calculation."""
    try:
        data = _payload(request)
        kind = data.get("kind")
        contract = parse_contract(data.get("barrier_contract", data))
        result = price_structure(kind, data, contract)
        return JsonResponse({"data": result})
    except InputError as exc:
        return _error(exc)


@require_POST
def package_monitoring_equivalence(request):
    try:
        data = _payload(request)
        contract = parse_contract(data.get("barrier_contract", data))
        result = monitoring_equivalence(data.get("kind"), data, contract, data.get("discrete_monitoring"))
        return JsonResponse({"data": result})
    except InputError as exc:
        return _error(exc)


@require_POST
def solve(request):
    try:
        data = _payload(request)
        kind = data.get("kind")
        contract = parse_contract(data.get("barrier_contract", data))
        result = solve_zero_cost(kind, data, contract)
        calculation = _save("solver", data, result)
        result["calculation_id"] = calculation.id
        return JsonResponse({"data": result}, status=201)
    except InputError as exc:
        return _error(exc)


@require_POST
def scenarios(request):
    try:
        data = _payload(request)
        kind = data.get("kind")
        contract = parse_contract(data.get("barrier_contract", data))
        structure = price_structure(kind, data, contract)
        result = maturity_scenarios(kind, data, contract, structure)
        calculation = _save("scenario", data, result)
        result["calculation_id"] = calculation.id
        return JsonResponse({"data": result}, status=201)
    except InputError as exc:
        return _error(exc)


@require_GET
def history(request):
    limit = min(max(int(request.GET.get("limit", 50)), 1), 200)
    rows = Calculation.objects.all()[:limit]
    return JsonResponse({"data": [{
        "id": row.id,
        "kind": row.kind,
        "request": row.request_data,
        "result": row.result_data,
        "warnings": row.warnings,
        "model_version": row.model_version,
        "created_at": row.created_at.isoformat(),
    } for row in rows]})


@require_http_methods(["GET", "POST"])
def chain(request):
    try:
        underlying = request.GET.get("underlying") if request.method == "GET" else _payload(request).get("underlying")
        if not underlying:
            raise InputError({"underlying": ["This field is required."]})
        return JsonResponse({"data": option_chain(str(underlying).strip())})
    except (InputError, MarketDataError) as exc:
        return _error(exc)


@require_POST
def quotes(request):
    try:
        tickers = _payload(request).get("tickers")
        if not isinstance(tickers, list) or not tickers:
            raise InputError({"tickers": ["Provide a non-empty list."]})
        return JsonResponse({"data": option_quotes(tickers)})
    except (InputError, MarketDataError) as exc:
        return _error(exc)


@require_GET
def rates(request):
    return _error(MarketDataError(
        "Yahoo Finance does not provide the BRL DI curve. Enter the annual DI rate manually."
    ))


def _learning_response(request, calculation_id, study):
    """Run a read-only educational study against one persisted calculation."""
    try:
        calculation = Calculation.objects.get(pk=calculation_id)
    except Calculation.DoesNotExist:
        return _error(InputError({"calculation_id": ["Calculation not found."]}))
    try:
        return JsonResponse({"data": study(calculation, request.GET)})
    except InputError as exc:
        return _error(exc)


@require_GET
def learning_paths(request, calculation_id):
    return _learning_response(request, calculation_id, path_explorer)


@require_GET
def learning_quote(request, calculation_id):
    return _learning_response(request, calculation_id, dealer_quote)


@require_GET
def learning_volatility(request, calculation_id):
    return _learning_response(request, calculation_id, volatility_lab)


@require_GET
def learning_hedge(request, calculation_id):
    return _learning_response(request, calculation_id, hedge_simulator)


@require_GET
def learning_attribution(request, calculation_id):
    return _learning_response(request, calculation_id, pnl_attribution)
