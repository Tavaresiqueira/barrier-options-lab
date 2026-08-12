"""Read-only learning studies for saved barrier-option calculations.

The studies deliberately rebuild a saved request rather than accepting a new trade
definition.  This keeps an educational experiment tied to the calculation a user
has already inspected and makes the random-number provenance visible.
"""
import math
from datetime import timedelta

import numpy as np

from .calendar import observation_dates
from .monte_carlo import MonteCarloBarrierEngine
from .structures import price_structure
from .validation import InputError, parse_contract


PACKAGE_KINDS = {
    "collar", "fence", "nitro", "double_up_ko", "box_ko", "box_bullet",
    "bullet", "bullet_plus", "golden_bullet", "collar_kiko", "fence_kiko",
    "call_kiko", "digital",
}
PATH_KINDS = {"barrier", *PACKAGE_KINDS}
HEDGE_KINDS = {"barrier", "nitro"}
MAX_STUDY_PATHS = 5_000


def _number(query, name, default, minimum=None, maximum=None):
    raw = query.get(name, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise InputError({name: ["Expected a number."]}) from None
    if minimum is not None and value < minimum:
        raise InputError({name: [f"Must be at least {minimum}."]})
    if maximum is not None and value > maximum:
        raise InputError({name: [f"Must be at most {maximum}."]})
    return value


def _integer(query, name, default, minimum, maximum):
    raw = query.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise InputError({name: ["Expected an integer."]}) from None
    if not minimum <= value <= maximum:
        raise InputError({name: [f"Must be between {minimum} and {maximum}."]})
    return value


def _saved_trade(calculation):
    if calculation.kind == "barrier":
        payload = calculation.request_data
        kind = "barrier"
    elif calculation.kind in PACKAGE_KINDS:
        payload = calculation.request_data
        kind = calculation.kind
    else:
        raise InputError({"calculation_id": [
            f"Learning studies do not support saved '{calculation.kind}' calculations. Price a barrier or package calculation first."
        ]})
    return kind, payload, parse_contract(payload.get("barrier_contract", payload))


def _study_contract(contract):
    """Cap study work without changing the saved trade's market conventions."""
    return contract.changed(paths=min(contract.paths, MAX_STUDY_PATHS), calculate_greeks=False)


def _provenance(contract, steps):
    return {
        "engine": MonteCarloBarrierEngine.name,
        "seed": contract.seed,
        "paths": contract.paths,
        "steps": steps,
        "monitoring": contract.monitoring,
        "antithetic": True,
        "brownian_bridge": contract.monitoring == "continuous",
        "common_random_numbers": True,
    }


def _contract_value(kind, payload, contract):
    if kind == "barrier":
        result = MonteCarloBarrierEngine().price(contract, include_greeks=False)
        return result["model_price"] * contract.quantity * contract.multiplier, result
    result = price_structure(kind, payload, contract)
    return result["net_option_cost"], result


def _clean_value(calculation):
    if calculation.kind == "barrier":
        return calculation.result_data["total_premium"]
    return calculation.result_data["net_option_cost"]


def _path_dates(contract, steps):
    if contract.monitoring == "continuous":
        return [contract.valuation_date + timedelta(days=round((contract.expiration_date - contract.valuation_date).days * index / steps)) for index in range(steps + 1)]
    sessions = observation_dates(contract.valuation_date, contract.expiration_date, "daily_close")
    return [contract.valuation_date, *sessions]


def _simulation_cube(contract, paths):
    """Generate the engine's GBM and bridge uniforms for a small inspectable cube."""
    engine = MonteCarloBarrierEngine()
    steps = engine._steps(contract)
    dt = contract.years / steps
    z, uniforms = engine._randoms(paths, steps, contract.seed)
    increments = ((contract.rate - contract.dividend_yield - .5 * contract.volatility ** 2) * dt
                  + contract.volatility * math.sqrt(dt) * z)
    prices = contract.spot * np.exp(np.cumsum(increments, axis=1))
    prior = np.column_stack([np.full(paths, contract.spot), prices[:, :-1]])
    if contract.monitoring == "continuous":
        if contract.direction == "up":
            endpoint = (prior >= contract.barrier) | (prices >= contract.barrier)
            a, b = np.maximum(np.log(contract.barrier / prior), 0), np.maximum(np.log(contract.barrier / prices), 0)
        else:
            endpoint = (prior <= contract.barrier) | (prices <= contract.barrier)
            a, b = np.maximum(np.log(prior / contract.barrier), 0), np.maximum(np.log(prices / contract.barrier), 0)
        bridge_probability = np.exp(-2 * a * b / (contract.volatility ** 2 * dt))
        bridge = ~endpoint & (uniforms < bridge_probability)
        hit = endpoint | bridge
    else:
        sessions = observation_dates(contract.valuation_date, contract.expiration_date, "daily_close")
        observed = set(observation_dates(contract.valuation_date, contract.expiration_date, contract.monitoring))
        mask = np.array([day in observed for day in sessions])
        endpoint = np.zeros_like(prices, dtype=bool)
        endpoint[:, mask] = prices[:, mask] >= contract.barrier if contract.direction == "up" else prices[:, mask] <= contract.barrier
        bridge = np.zeros_like(endpoint)
        bridge_probability = np.zeros_like(prices)
        hit = endpoint
    return prices, endpoint, bridge, bridge_probability, hit, _path_dates(contract, steps), steps


def _path_payoff(kind, payload, contract, terminal, hit, priced_result=None):
    intrinsic = max(terminal - contract.strike, 0) if contract.option_type == "call" else max(contract.strike - terminal, 0)
    active = hit if contract.behavior == "in" else not hit
    option_value = intrinsic * active
    if not active and contract.rebate:
        option_value += contract.rebate
    units = contract.quantity * contract.multiplier
    legs = {"barrier_option": option_value * units}
    if kind == "nitro":
        units = (priced_result or {}).get("leg_quantities", {}).get("long_up_out_call_units", payload.get("option_quantity", 1) * payload.get("contract_multiplier", 1))
        legs = {"long_up_out_call": option_value * units}
    elif kind == "double_up_ko":
        quantities = (priced_result or {}).get("leg_quantities", {})
        base = quantities.get("underlying_shares", payload.get("share_quantity", 1) * payload.get("underlying_quantity_ratio", 1))
        long_quantity = quantities.get("long_up_out_call_units", payload.get("share_quantity", 1) * payload.get("long_up_out_call_quantity_ratio", payload.get("call_quantity_ratio", 1)))
        short_quantity = quantities.get("short_vanilla_call_units", payload.get("share_quantity", 1) * payload.get("short_vanilla_call_quantity_ratio", 1))
        short_strike = float(payload["short_vanilla_call_strike"])
        legs = {
            "underlying": terminal * base,
            "long_up_out_call": option_value * long_quantity,
            "short_vanilla_call": -max(terminal - short_strike, 0) * short_quantity,
        }
    return intrinsic, active, legs, sum(legs.values())


def path_explorer(calculation, query):
    kind, payload, original_contract = _saved_trade(calculation)
    count = _integer(query, "path_count", 8, 1, 20)
    selected = _integer(query, "path_index", 0, 0, 255)
    seed = _integer(query, "seed", original_contract.seed, 0, 2_147_483_647)
    contract = _study_contract(original_contract.changed(seed=seed))
    cube_paths = 256
    prices, endpoint, bridge, bridge_probability, hit, dates, steps = _simulation_cube(contract, cube_paths)
    available = []
    for index in range(count):
        first = int(np.argmax(hit[index])) if hit[index].any() else None
        available.append({"index": index, "label": f"Path {index + 1}", "state": "hit" if first is not None else "not_hit"})
    if selected >= count:
        raise InputError({"path_index": ["Choose an available path index."]})
    first = int(np.argmax(hit[selected])) if hit[selected].any() else None
    intrinsic, active, legs, payoff = _path_payoff(kind, payload, contract, float(prices[selected, -1]), first is not None, calculation.result_data)
    points = [{
        "step": step, "date": dates[step + 1].isoformat(), "spot": float(prices[selected, step]),
        "endpoint_hit": bool(endpoint[selected, step]), "bridge_crossing": bool(bridge[selected, step]),
        "event": bool(hit[selected, step]), "crossing_probability": float(bridge_probability[selected, step]),
        "barrier_state": "triggered" if hit[selected, :step + 1].any() else "not_triggered",
    } for step in range(steps)]
    disclosures = ["A bridge crossing is an intra-step event sampled from the Brownian-bridge correction; it need not be visible in either endpoint.", "Paths are risk-neutral simulations, not forecasts."]
    if kind not in {"barrier", "nitro", "double_up_ko"}:
        disclosures.append("For this multi-leg package, terminal payoff shown is the selected saved barrier contract leg rather than a synthetic package payoff; package barriers can have multiple independent events.")
    return {
        "calculation": {"id": calculation.id, "kind": kind}, "inputs": {"path_count": count, "path_index": selected, "seed": seed},
        "result": {"available_paths": available, "sample_paths": available, "selected_path": {
            "index": selected, "points": points, "barrier": contract.barrier,
            "first_hit_index": None if first is None else first + 1,
            "first_hit_date": None if first is None else dates[first + 1].isoformat(),
            "first_bridge_index": next((point["step"] for point in points if point["bridge_crossing"]), None),
            "terminal_price": float(prices[selected, -1]), "terminal_intrinsic": intrinsic,
            "active_at_expiry": active, "leg_payoffs": legs, "terminal_payoff": payoff,
            "discount_factor": math.exp(-contract.rate * contract.years),
            "discounted_value": payoff * math.exp(-contract.rate * contract.years),
        }, "provenance": _provenance(contract, steps)},
        "disclosures": disclosures,
    }


def dealer_quote(calculation, query):
    kind, payload, contract = _saved_trade(calculation)
    pricing_volatility = _number(query, "pricing_volatility", contract.volatility, .0001, 5)
    model_reserve = _number(query, "model_reserve_brl", 0)
    hedge_liquidity = _number(query, "hedging_liquidity_reserve_brl", 0)
    margin = _number(query, "dealer_margin_brl", 0)
    quote_side = query.get("quote_side", "offer")
    if quote_side not in {"offer", "bid"}:
        raise InputError({"quote_side": ["Choose offer or bid."]})
    repriced, repricing = _contract_value(kind, payload, _study_contract(contract.changed(volatility=pricing_volatility)))
    clean = repriced
    adjustments = [("Model reserve", model_reserve), ("Hedging and liquidity reserve", hedge_liquidity), ("Dealer margin", margin)]
    sign = 1 if quote_side == "offer" else -1
    items = [{"label": "Clean model PV", "value": clean, "kind": "clean"}] + [{"label": label, "value": sign * value, "kind": "adjustment"} for label, value in adjustments]
    client_quote = sum(item["value"] for item in items)
    underlying = calculation.result_data.get("underlying_value", 0)
    return {"calculation": {"id": calculation.id, "kind": kind}, "inputs": {"pricing_volatility": pricing_volatility, "quote_side": quote_side, "model_reserve_brl": model_reserve, "hedging_liquidity_reserve_brl": hedge_liquidity, "dealer_margin_brl": margin}, "result": {"clean_value": clean, "clean_model_pv": clean, "items": items, "client_quote": client_quote, "underlying_cash_notional": underlying, "unit": "BRL", "provenance": _provenance(_study_contract(contract), MonteCarloBarrierEngine()._steps(contract))}, "disclosures": ["The clean PV is the signed option premium or package net option cost; underlying notional is displayed separately.", "A bid reverses the signed quote adjustments; reserve inputs remain BRL amounts."]}


def volatility_lab(calculation, query):
    kind, payload, original_contract = _saved_trade(calculation)
    historical = _number(query, "historical_volatility", original_contract.volatility, .0001, 5)
    implied = _number(query, "implied_volatility", original_contract.volatility, .0001, 5)
    dealer = _number(query, "dealer_volatility", implied, .0001, 5)
    contract = _study_contract(original_contract)
    rows = []
    rows = [{"label": "Historical volatility", "volatility": historical, "model_value": None, "barrier_hit_probability": None, "delta": None, "descriptive_only": True}]
    for label, volatility in (("Market/implied volatility", implied), ("Dealer pricing volatility", dealer)):
        value, priced = _contract_value(kind, payload, contract.changed(volatility=volatility))
        rows.append({"label": label, "volatility": volatility, "model_value": value, "barrier_hit_probability": priced.get("barrier_diagnostics", priced).get("barrier_hit_probability"), "delta": priced.get("greeks", {}).get("delta")})
    return {"calculation": {"id": calculation.id, "kind": kind}, "inputs": {"historical_volatility": historical, "implied_volatility": implied, "dealer_volatility": dealer}, "result": {"rows": rows, "market_value": rows[1]["model_value"], "dealer_value": rows[2]["model_value"], "difference": rows[2]["model_value"] - rows[1]["model_value"], "unit": "BRL", "provenance": _provenance(contract, MonteCarloBarrierEngine()._steps(contract))}, "disclosures": ["Historical volatility is descriptive only and is not fed into the risk-neutral price.", "Every reprice uses the same seed, so differences use common random numbers."]}


def hedge_simulator(calculation, query):
    kind, payload, original_contract = _saved_trade(calculation)
    if kind not in HEDGE_KINDS:
        raise InputError({"calculation_id": [f"Hedge simulator currently supports: {', '.join(sorted(HEDGE_KINDS))}; multi-event packages need leg-specific state tracking."]})
    path_index = _integer(query, "path_index", 0, 0, 255)
    cost_bps = _number(query, "transaction_cost_bps", 0, 0, 1_000)
    requested = _integer(query, "rebalance_count", 24, 2, 60)
    contract = _study_contract(original_contract)
    prices, _, _, _, hit, dates, steps = _simulation_cube(contract, 256)
    selected_steps = sorted(set(np.linspace(0, steps - 1, requested, dtype=int).tolist() + [steps - 1]))
    scale = contract.quantity * contract.multiplier if kind == "barrier" else payload.get("option_quantity", 1) * payload.get("contract_multiplier", 1)
    shares, cash, costs = 0.0, 0.0, 0.0
    initial_value, _ = _contract_value(kind, payload, contract)
    cash = initial_value
    timeline = []
    previous_step = 0
    for step in selected_steps:
        elapsed = max(step - previous_step, 0) / steps * contract.years
        cash *= math.exp(contract.rate * elapsed)
        spot = float(prices[path_index, step])
        triggered = bool(hit[path_index, :step + 1].any())
        valuation = dates[step + 1]
        if valuation >= contract.expiration_date:
            valuation = contract.expiration_date - timedelta(days=1)
        remaining = contract.changed(spot=spot, valuation_date=valuation, barrier_status="triggered" if triggered else "not_triggered", paths=min(contract.paths, 2_000))
        unit = MonteCarloBarrierEngine().price(remaining, include_greeks=True)
        structure_value = unit["model_price"] * scale
        delta = unit["greeks"]["delta"] * scale
        # The client owns the package, so the dealer's short liability is neutralised by buying its client delta.
        target_shares = delta
        trade = target_shares - shares
        trade_cost = abs(trade) * spot * cost_bps / 10_000
        cash -= trade * spot + trade_cost
        costs += trade_cost
        shares = target_shares
        hedge_value = cash + shares * spot
        timeline.append({"step": step + 1, "date": dates[step + 1].isoformat(), "spot": spot, "barrier_state": "triggered" if triggered else "not_triggered", "structure_value": structure_value, "delta": delta, "hedge_shares": shares, "trade_shares": trade, "cash_account": cash, "transaction_cost": trade_cost, "hedge_pnl": hedge_value - initial_value, "cumulative_pnl": hedge_value - structure_value})
        previous_step = step
    intrinsic, active, legs, terminal_payoff = _path_payoff(kind, payload, contract, float(prices[path_index, -1]), bool(hit[path_index].any()), calculation.result_data)
    terminal_stock_cash = cash + shares * float(prices[path_index, -1])
    return {"calculation": {"id": calculation.id, "kind": kind}, "inputs": {"path_index": path_index, "rebalance_count": requested, "transaction_cost_bps": cost_bps}, "result": {"timeline": timeline, "summary": {"client_premium": initial_value, "terminal_liability": terminal_payoff, "terminal_stock_cash": terminal_stock_cash, "hedge_error_at_expiry": terminal_stock_cash - terminal_payoff, "transaction_costs": costs, "leg_payoffs": legs}, "provenance": _provenance(contract, steps)}, "disclosures": ["Educational discrete delta hedge of the dealer's short client option package; it is not a production hedging model.", "The path's barrier state is irreversible and every mark reuses the saved model assumptions."]}


def pnl_attribution(calculation, query):
    kind, payload, original_contract = _saved_trade(calculation)
    spot_change = _number(query, "spot_change_pct", 0, -99, 1_000) / 100
    volatility_change = _number(query, "volatility_change", 0, -original_contract.volatility + .0001, 5)
    rate_change = _number(query, "rate_change", 0, -5, 5)
    days = _integer(query, "days", 0, 0, max(0, (original_contract.expiration_date - original_contract.valuation_date).days - 1))
    contract = _study_contract(original_contract)
    base, _ = _contract_value(kind, payload, contract)
    spot_contract = contract.changed(spot=contract.spot * (1 + spot_change))
    spot_value, _ = _contract_value(kind, payload, spot_contract)
    vol_contract = spot_contract.changed(volatility=contract.volatility + volatility_change)
    vol_value, _ = _contract_value(kind, payload, vol_contract)
    rate_contract = vol_contract.changed(rate=contract.rate + rate_change)
    rate_value, _ = _contract_value(kind, payload, rate_contract)
    time_contract = rate_contract.changed(valuation_date=contract.valuation_date + timedelta(days=days))
    ending, _ = _contract_value(kind, payload, time_contract)
    spot_bump = max(contract.spot * .01, .01)
    vol_bump = .01
    rate_bump = .0001
    spot_up, _ = _contract_value(kind, payload, contract.changed(spot=contract.spot + spot_bump))
    spot_down, _ = _contract_value(kind, payload, contract.changed(spot=contract.spot - spot_bump))
    vol_up, _ = _contract_value(kind, payload, contract.changed(volatility=contract.volatility + vol_bump))
    vol_down, _ = _contract_value(kind, payload, contract.changed(volatility=max(.0001, contract.volatility - vol_bump)))
    rate_up, _ = _contract_value(kind, payload, contract.changed(rate=contract.rate + rate_bump))
    rate_down, _ = _contract_value(kind, payload, contract.changed(rate=contract.rate - rate_bump))
    theta_value, _ = _contract_value(kind, payload, contract.changed(valuation_date=contract.valuation_date + timedelta(days=1))) if contract.years > 1 / 365 else (0, None)
    greeks = {
        "delta": (spot_up - spot_down) / (2 * spot_bump),
        "gamma": (spot_up - 2 * base + spot_down) / spot_bump ** 2,
        "vega_per_1pct": (vol_up - vol_down) / 2,
        "theta_per_calendar_day": theta_value - base if contract.years > 1 / 365 else -base,
        "rho_per_1bp": (rate_up - rate_down) / 2,
    }
    spot_move = spot_contract.spot - contract.spot
    greek_rows = [
        {"label": "Delta", "value": greeks["delta"] * spot_move, "kind": "greek"},
        {"label": "Gamma", "value": .5 * greeks["gamma"] * spot_move ** 2, "kind": "greek"},
        {"label": "Vega", "value": greeks["vega_per_1pct"] * volatility_change / .01, "kind": "greek"},
        {"label": "Theta", "value": greeks["theta_per_calendar_day"] * days, "kind": "greek"},
        {"label": "Rho", "value": greeks["rho_per_1bp"] * rate_change / .0001, "kind": "greek"},
    ]
    rows = [
        {"label": "Baseline", "value": base, "kind": "level"},
        {"label": "Spot", "value": spot_value - base, "kind": "attribution"},
        {"label": "Volatility", "value": vol_value - spot_value, "kind": "attribution"},
        {"label": "Rates", "value": rate_value - vol_value, "kind": "attribution"},
        {"label": "Time", "value": ending - rate_value, "kind": "attribution"},
        {"label": "Ending", "value": ending, "kind": "level"},
    ]
    total_change = ending - base
    contributions = sum(row["value"] for row in rows if row["kind"] == "attribution")
    greek_contributions = sum(row["value"] for row in greek_rows)
    exact_residual = total_change - contributions
    return {"calculation": {"id": calculation.id, "kind": kind}, "inputs": {"spot_change_pct": spot_change * 100, "volatility_change": volatility_change, "rate_change": rate_change, "days": days}, "result": {"rows": rows, "greeks": greeks, "greek_rows": greek_rows, "total_change": total_change, "residual": exact_residual, "exact_residual": exact_residual, "greek_residual": total_change - greek_contributions, "attribution_order": ["spot", "volatility", "rates", "time"], "unit": "BRL", "provenance": _provenance(contract, MonteCarloBarrierEngine()._steps(contract))}, "disclosures": ["This is an ordered exact-repricing waterfall; the separate Greek approximation has its own residual.", "No barrier event is inferred from a spot shock; use the path explorer to study path-dependent trigger events."]}
