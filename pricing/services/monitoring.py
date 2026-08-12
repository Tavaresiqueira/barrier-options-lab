from scipy.optimize import minimize_scalar

from .structures import price_structure
from .validation import InputError


DISCRETE_MONITORING = {"daily_close", "weekly", "monthly", "maturity_only"}


def monitoring_equivalence(kind, data, contract, discrete_monitoring):
    """Match a discrete package PV with a more distant continuously monitored barrier."""
    if discrete_monitoring not in DISCRETE_MONITORING:
        raise InputError({"discrete_monitoring": ["Choose daily_close, weekly, monthly or maturity_only."]})
    if contract.barrier_status == "triggered":
        raise InputError({"barrier_status": ["Monitoring equivalence applies only before the barrier has triggered."]})

    # Keep the interactive solve responsive while preserving common random numbers.
    solve_paths = min(contract.paths, 12_000)
    base = contract.changed(paths=solve_paths, calculate_greeks=False, barrier_status="not_triggered")
    original_barrier = base.barrier
    discrete_contract = base.changed(monitoring=discrete_monitoring)
    target = price_structure(kind, data, discrete_contract)["net_option_cost"]
    continuous_original = price_structure(kind, data, base.changed(monitoring="continuous"))["net_option_cost"]

    if base.direction == "up":
        lower, upper = original_barrier, max(original_barrier * 2.0, base.spot * 3.0)
    else:
        lower, upper = max(base.spot * 0.05, 0.01), original_barrier

    evaluations = []

    def objective(barrier):
        try:
            value = price_structure(kind, data, base.changed(monitoring="continuous", barrier=float(barrier)))["net_option_cost"]
        except InputError:
            return 1e50
        evaluations.append((float(barrier), value))
        return abs(value - target)

    solved = minimize_scalar(objective, bounds=(lower, upper), method="bounded", options={"xatol": max(base.spot * 0.0001, 0.001), "maxiter": 28})
    equivalent_barrier = float(solved.x)
    equivalent_price = price_structure(kind, data, base.changed(monitoring="continuous", barrier=equivalent_barrier))["net_option_cost"]
    shift = equivalent_barrier - original_barrier
    return {
        "kind": kind,
        "discrete_monitoring": discrete_monitoring,
        "original_barrier": original_barrier,
        "continuous_price_at_original_barrier": continuous_original,
        "discrete_price_at_original_barrier": target,
        "price_difference": target - continuous_original,
        "equivalent_continuous_barrier": equivalent_barrier,
        "equivalent_continuous_price": equivalent_price,
        "matching_residual": equivalent_price - target,
        "barrier_shift_brl": shift,
        "barrier_shift_pct_of_original": shift / original_barrier * 100,
        "barrier_shift_pct_of_spot": shift / base.spot * 100,
        "direction": base.direction,
        "behavior": base.behavior,
        "paths_used": solve_paths,
        "converged": bool(solved.success),
        "evaluations": len(evaluations),
        "interpretation": "A discrete barrier has fewer observation opportunities. Its continuously monitored price is matched by moving an up barrier higher or a down barrier lower.",
    }
