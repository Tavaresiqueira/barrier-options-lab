from scipy.optimize import brentq

from .structures import price_structure
from .validation import InputError


VARIABLE_FIELDS = {
    "collar": {"protective_put_strike", "call_strike", "barrier"},
    "fence": {"lower_put_strike", "upper_put_strike", "call_strike", "barrier"},
}


def solve_zero_cost(kind, data, contract):
    variable = data.get("solve_for")
    if variable not in VARIABLE_FIELDS.get(kind, set()):
        raise InputError({"solve_for": [f"Choose one of: {', '.join(sorted(VARIABLE_FIELDS.get(kind, set())))}."]})
    try:
        lower = float(data["search_lower"])
        upper = float(data["search_upper"])
        tolerance = float(data.get("zero_cost_tolerance", 0.01))
    except (KeyError, TypeError, ValueError):
        raise InputError({"search_bounds": ["Valid search_lower, search_upper and tolerance are required."]}) from None
    if not 0 < lower < upper:
        raise InputError({"search_bounds": ["Require 0 < search_lower < search_upper."]})

    evaluations = 0

    def objective(value):
        nonlocal evaluations
        evaluations += 1
        trial_data = dict(data)
        trial_data["calculate_structure_greeks"] = False
        trial_contract = contract
        if variable == "call_strike":
            trial_contract = trial_contract.changed(strike=value)
        elif variable == "barrier":
            trial_contract = trial_contract.changed(barrier=value)
        else:
            trial_data[variable] = value
        return price_structure(kind, trial_data, trial_contract)["net_option_cost"]

    low_value = objective(lower)
    high_value = objective(upper)
    if low_value * high_value > 0:
        raise InputError({"search_bounds": [f"No zero-cost solution is bracketed: residuals are {low_value:.6f} and {high_value:.6f}."]})
    root, details = brentq(objective, lower, upper, xtol=max(tolerance / 100, 1e-8), full_output=True, maxiter=100)
    residual = objective(root)
    return {
        "kind": kind,
        "solved_parameter": variable,
        "solution": root,
        "residual": residual,
        "iterations": details.iterations,
        "function_calls": evaluations,
        "converged": details.converged,
        "tolerance": tolerance,
        "bounds": [lower, upper],
    }
