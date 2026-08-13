import numpy as np
from scipy.optimize import minimize_scalar

from .monte_carlo import MonteCarloBarrierEngine
from .validation import InputError


def single_barrier_payoff(contract, priced, points=81):
    """Return expiry payoffs for both possible historical barrier states."""
    low, high = contract.spot * 0.5, contract.spot * 1.5
    terminal = np.linspace(low, high, points)
    intrinsic = np.maximum(terminal - contract.strike, 0) if contract.option_type == "call" else np.maximum(contract.strike - terminal, 0)
    units = contract.quantity * contract.multiplier
    intrinsic *= units
    rebate = np.full(points, contract.rebate * units)
    initial = priced["total_premium"]
    states = {}
    for hit in (False, True):
        active = hit if contract.behavior == "in" else not hit
        payoff = intrinsic if active else rebate
        label = "barrier_triggered" if hit else "barrier_not_triggered"
        states[label] = [{
            "terminal_price": float(terminal[index]),
            "barrier_state": label,
            "leg_payoffs": {"option_intrinsic": float(intrinsic[index] if active else 0), "rebate": float(rebate[index] if not active else 0)},
            "total_payoff": float(payoff[index]),
            "total_pnl": float(payoff[index] - initial),
        } for index in range(points)]
    return {"chart_unit": "BRL", "scenario_range": [low, high], "states": states, "initial_investment": initial}


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
