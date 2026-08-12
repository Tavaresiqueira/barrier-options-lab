from datetime import date

from .domain import BarrierContract


class InputError(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Invalid request")


def _required(data, name, cast):
    if name not in data or data[name] in ("", None):
        raise InputError({name: ["This field is required."]})
    try:
        return cast(data[name])
    except (TypeError, ValueError):
        raise InputError({name: [f"Expected {cast.__name__}."]}) from None


def parse_contract(data) -> BarrierContract:
    errors = {}
    values = {}
    choices = {
        "option_type": {"call", "put"},
        "direction": {"up", "down"},
        "behavior": {"in", "out"},
        "monitoring": {"continuous", "daily_close", "weekly", "monthly", "maturity_only"},
        "barrier_status": {"not_triggered", "triggered", "not_applicable"},
        "rebate_timing": {"expiry", "immediate"},
    }
    for field, allowed in choices.items():
        value = str(data.get(field, "")).lower()
        if value not in allowed:
            errors[field] = [f"Choose one of: {', '.join(sorted(allowed))}."]
        values[field] = value

    for field in ("spot", "strike", "barrier", "volatility"):
        try:
            values[field] = _required(data, field, float)
        except InputError as exc:
            errors.update(exc.errors)
    for field in ("rate", "dividend_yield"):
        try:
            values[field] = float(data.get(field, 0))
        except (TypeError, ValueError):
            errors[field] = ["Expected a number in decimal form, for example 0.12 for 12%."]
    for field, default in (("quantity", 1), ("multiplier", 1), ("rebate", 0)):
        try:
            values[field] = float(data.get(field, default))
        except (TypeError, ValueError):
            errors[field] = ["Expected a number."]
    try:
        values["paths"] = int(data.get("paths", 50_000))
        values["seed"] = int(data.get("seed", 42))
    except (TypeError, ValueError):
        errors["paths"] = ["Paths and seed must be integers."]
    for field in ("valuation_date", "expiration_date"):
        try:
            values[field] = date.fromisoformat(str(data.get(field, "")))
        except ValueError:
            errors[field] = ["Use ISO date format YYYY-MM-DD."]

    if errors:
        raise InputError(errors)
    if values["spot"] <= 0:
        errors["spot"] = ["Must be positive."]
    if values["strike"] <= 0:
        errors["strike"] = ["Must be positive."]
    if values["barrier"] <= 0:
        errors["barrier"] = ["Must be positive."]
    if values["volatility"] <= 0:
        errors["volatility"] = ["Must be positive."]
    if values["quantity"] <= 0:
        errors["quantity"] = ["Must be positive."]
    if values["multiplier"] <= 0:
        errors["multiplier"] = ["Must be positive."]
    if values["rebate"] < 0:
        errors["rebate"] = ["Must not be negative."]
    if not 5_000 <= values["paths"] <= 500_000:
        errors["paths"] = ["Must be between 5,000 and 500,000."]
    if values["expiration_date"] <= values["valuation_date"]:
        errors["expiration_date"] = ["Must be after valuation_date."]
    if values["direction"] == "up" and values["barrier"] <= values["spot"] and values["barrier_status"] == "not_triggered":
        errors["barrier"] = ["An untriggered up barrier must be above current spot."]
    if values["direction"] == "down" and values["barrier"] >= values["spot"] and values["barrier_status"] == "not_triggered":
        errors["barrier"] = ["An untriggered down barrier must be below current spot."]
    if errors:
        raise InputError(errors)
    values["calculate_greeks"] = bool(data.get("calculate_greeks", False))
    return BarrierContract(**values)


def positive_float(data, field, default=None):
    value = data.get(field, default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise InputError({field: ["Expected a number."]}) from None
    if value <= 0:
        raise InputError({field: ["Must be positive."]})
    return value
