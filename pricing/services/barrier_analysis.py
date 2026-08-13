import numpy as np
from scipy.optimize import minimize_scalar

from .monte_carlo import MonteCarloBarrierEngine
from .validation import InputError
from .vanilla import black_scholes


def single_barrier_mark_curve(contract, priced, points_per_branch=25):
    """Reprice the option today across spot, splitting the curve at the barrier event."""
    low = min(contract.spot * 0.5, contract.barrier * 0.9)
    high = max(contract.spot * 1.5, contract.barrier * 1.1)
    epsilon = max(contract.spot * 0.0001, 0.0001)
    if contract.direction == "up":
        branches = {
            "pre_barrier": (np.linspace(low, contract.barrier - epsilon, points_per_branch), "not_triggered"),
            "post_trigger": (np.linspace(contract.barrier, high, points_per_branch), "triggered"),
        }
    else:
        branches = {
            "post_trigger": (np.linspace(low, contract.barrier, points_per_branch), "triggered"),
            "pre_barrier": (np.linspace(contract.barrier + epsilon, high, points_per_branch), "not_triggered"),
        }
    units = contract.quantity * contract.multiplier
    initial = priced["total_premium"]
    engine = MonteCarloBarrierEngine()
    curve_contract = contract.changed(paths=min(contract.paths, 8_000), calculate_greeks=False)
    states = {}
    delta_sign_flips = []
    for label, (spots, barrier_status) in branches.items():
        rows = []
        for spot in spots:
            unit_value = engine._plain_price(curve_contract.changed(spot=float(spot), barrier_status=barrier_status))
            vanilla_value = black_scholes(contract.option_type, float(spot), contract.strike, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
            total_value = unit_value * units
            rows.append({
                "spot": float(spot), "barrier_state": barrier_status,
                "unit_model_value": unit_value, "total_model_value": total_value,
                "vanilla_unit_value": vanilla_value, "unit_premium_difference": vanilla_value - unit_value,
                "total_pnl_since_trade": total_value - initial,
            })
        local_deltas = np.gradient([row["unit_model_value"] for row in rows], spots)
        local_gammas = np.gradient(local_deltas, spots)
        vanilla_deltas = np.gradient([row["vanilla_unit_value"] for row in rows], spots)
        vanilla_gammas = np.gradient(vanilla_deltas, spots)
        for row, delta, gamma, vanilla_gamma in zip(rows, local_deltas, local_gammas, vanilla_gammas):
            row["local_delta"] = float(delta)
            row["local_gamma"] = float(gamma)
            row["vanilla_local_gamma"] = float(vanilla_gamma)
        for index in range(1, len(rows)):
            left_delta, right_delta = local_deltas[index - 1], local_deltas[index]
            if left_delta * right_delta >= 0 or abs(left_delta - right_delta) < 1e-8:
                continue
            zero_weight = abs(left_delta) / (abs(left_delta) + abs(right_delta))
            zero_spot = spots[index - 1] + zero_weight * (spots[index] - spots[index - 1])
            zero_value = rows[index - 1]["unit_model_value"] + zero_weight * (rows[index]["unit_model_value"] - rows[index - 1]["unit_model_value"])
            delta_sign_flips.append({
                "branch": label,
                "barrier_state": barrier_status,
                "spot": float(zero_spot),
                "unit_model_value": float(zero_value),
                "direction": "positive_to_negative" if left_delta > 0 else "negative_to_positive",
                "delta_before": float(left_delta),
                "delta_after": float(right_delta),
            })
        states[label] = rows
    expiry_spots = np.linspace(low, high, points_per_branch * 2)
    vanilla_expiry = np.maximum(expiry_spots - contract.strike, 0) if contract.option_type == "call" else np.maximum(contract.strike - expiry_spots, 0)
    expiry_states = {}
    for label, barrier_status in (("barrier_not_triggered", "not_triggered"), ("barrier_triggered", "triggered")):
        active = (barrier_status == "triggered") if contract.behavior == "in" else (barrier_status == "not_triggered")
        exotic_payoff = vanilla_expiry if active else np.full_like(expiry_spots, contract.rebate)
        rows = []
        for index, spot in enumerate(expiry_spots):
            state_possible = True
            if barrier_status == "not_triggered":
                state_possible = spot < contract.barrier if contract.direction == "up" else spot > contract.barrier
            rows.append({
                "terminal_price": float(spot), "barrier_state": barrier_status, "state_possible": bool(state_possible),
                "exotic_payoff_per_unit": float(exotic_payoff[index]),
                "exotic_pnl_per_unit": float(exotic_payoff[index] - priced["premium_per_unit"]),
                "vanilla_payoff_per_unit": float(vanilla_expiry[index]),
                "vanilla_pnl_per_unit": float(vanilla_expiry[index] - priced["vanilla_equivalent_price"]),
            })
        expiry_states[label] = rows
    return {
        "chart_unit": "BRL", "curve_type": "valuation_date_mark_to_market",
        "scenario_range": [low, high], "states": states, "initial_premium": initial,
        "valuation_date": contract.valuation_date.isoformat(),
        "expiration_date": contract.expiration_date.isoformat(),
        "days_to_expiry": (contract.expiration_date - contract.valuation_date).days,
        "barrier": contract.barrier, "paths_used": curve_contract.paths,
        "delta_sign_flips": delta_sign_flips,
        "expiry_states": expiry_states,
        "initial_exotic_premium_per_unit": priced["premium_per_unit"],
        "initial_vanilla_premium_per_unit": priced["vanilla_equivalent_price"],
        "initial_premium_discount_per_unit": priced["vanilla_equivalent_price"] - priced["premium_per_unit"],
    }


def single_barrier_monitoring_equivalence(contract, discrete_monitoring):
    if discrete_monitoring not in {"daily_close", "weekly", "monthly", "maturity_only"}:
        raise InputError({"discrete_monitoring": ["Choose daily_close, weekly, monthly or maturity_only."]})
    if contract.barrier_status == "triggered":
        raise InputError({"barrier_status": ["Monitoring equivalence applies only before the barrier has triggered."]})
    engine = MonteCarloBarrierEngine()
    base = contract.changed(paths=min(contract.paths, 12_000), calculate_greeks=False, barrier_status="not_triggered")
    target = engine.price(base.changed(monitoring=discrete_monitoring), include_greeks=False)["model_price"]
    continuous_original = engine.price(base.changed(monitoring="continuous"), include_greeks=False)["model_price"]
    original = base.barrier
    bounds = (original, max(original * 2, base.spot * 3)) if base.direction == "up" else (max(base.spot * .05, .01), original)
    evaluations = 0

    def objective(barrier):
        nonlocal evaluations
        evaluations += 1
        return abs(engine.price(base.changed(monitoring="continuous", barrier=float(barrier)), include_greeks=False)["model_price"] - target)

    solved = minimize_scalar(objective, bounds=bounds, method="bounded", options={"xatol": max(base.spot * .0001, .001), "maxiter": 28})
    equivalent = float(solved.x)
    equivalent_price = engine.price(base.changed(monitoring="continuous", barrier=equivalent), include_greeks=False)["model_price"]
    shift = equivalent - original
    return {
        "discrete_monitoring": discrete_monitoring, "original_barrier": original,
        "continuous_price_at_original_barrier": continuous_original, "discrete_price_at_original_barrier": target,
        "price_difference": target - continuous_original, "equivalent_continuous_barrier": equivalent,
        "equivalent_continuous_price": equivalent_price, "matching_residual": equivalent_price - target,
        "barrier_shift_brl": shift, "barrier_shift_pct_of_spot": shift / base.spot * 100,
        "paths_used": base.paths, "evaluations": evaluations, "converged": bool(solved.success),
    }
