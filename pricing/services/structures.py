import math

import numpy as np

from .monte_carlo import MonteCarloBarrierEngine
from .validation import InputError, positive_float
from .vanilla import black_scholes, black_scholes_cash_digital


VANILLA_STRATEGY_DEFINITIONS = {
    "call_spread": [("long_call", "Long call", 1, "call", "lower_call_strike"), ("short_call", "Short call", -1, "call", "upper_call_strike")],
    "risk_reversal": [("long_call", "Long call", 1, "call", "call_strike"), ("short_put", "Short put", -1, "put", "put_strike")],
    "seagull": [("long_call", "Long call", 1, "call", "lower_call_strike"), ("short_call", "Short upper call", -1, "call", "upper_call_strike"), ("short_put", "Short put", -1, "put", "put_strike")],
    "straddle": [("long_call", "Long call", 1, "call", "common_strike"), ("long_put", "Long put", 1, "put", "common_strike")],
    "strangle": [("long_call", "Long call", 1, "call", "call_strike"), ("long_put", "Long put", 1, "put", "put_strike")],
    "reverse_condor": [("long_put", "Long outer put", 1, "put", "outer_put_strike"), ("short_put", "Short inner put", -1, "put", "inner_put_strike"), ("short_call", "Short inner call", -1, "call", "inner_call_strike"), ("long_call", "Long outer call", 1, "call", "outer_call_strike")],
    "double_up": [("long_call", "Long accelerating call", 1, "call", "lower_call_strike"), ("short_call", "Two short limiter calls", -2, "call", "upper_call_strike")],
    "double_up_hedge": [("protective_put", "Long protective put", 1, "put", "protective_put_strike"), ("long_call", "Long accelerating call", 1, "call", "lower_call_strike"), ("short_call", "Two short limiter calls", -2, "call", "upper_call_strike")],
}


def price_structure(kind, data, contract):
    if kind in VANILLA_STRATEGY_DEFINITIONS:
        result = _price_vanilla_strategy(kind, data, contract)
    elif kind == "seagull_ki":
        result = _price_seagull_ki(data, contract)
    elif kind == "nitro":
        result = _price_nitro(data, contract)
    elif kind == "double_up_ko":
        result = _price_double_up_ko(data, contract)
    elif kind == "box_ko":
        result = _price_box_ko(data, contract)
    elif kind == "box_bullet":
        result = _price_box_bullet(data, contract)
    elif kind in {"bullet", "bullet_plus", "golden_bullet"}:
        result = _price_bullet_family(kind, data, contract)
    elif kind in {"collar_kiko", "fence_kiko", "call_kiko"}:
        result = _price_kiko(kind, data, contract)
    elif kind == "digital":
        result = _price_digital(data, contract)
    else:
        result = _price_collar_or_fence(kind, data, contract)
    if data.get("calculate_structure_greeks") and "structure_greeks" not in result:
        result["structure_greeks"] = generic_structure_greeks(kind, data, contract, result)
    return result


def _price_vanilla_strategy(kind, data, contract):
    """Price a transparent, standalone package of European vanilla options."""
    quantity = positive_float(data, "option_quantity", 1) * positive_float(data, "contract_multiplier", 1)
    spot, years, rate, dividend, volatility = contract.spot, contract.years, contract.rate, contract.dividend_yield, contract.volatility
    definitions = VANILLA_STRATEGY_DEFINITIONS[kind]
    strikes = {field: positive_float(data, field) for *_, field in definitions}
    if kind in {"call_spread", "double_up", "double_up_hedge"} and not strikes["lower_call_strike"] < strikes["upper_call_strike"]:
        raise InputError({"upper_call_strike": ["Call Spread requires lower call strike < upper call strike."]})
    if kind in {"risk_reversal", "strangle"} and not strikes["put_strike"] < strikes["call_strike"]:
        raise InputError({"call_strike": [f"{kind.replace('_', ' ').title()} requires put strike < call strike."]})
    if kind == "seagull" and not strikes["put_strike"] < strikes["lower_call_strike"] < strikes["upper_call_strike"]:
        raise InputError({"upper_call_strike": ["Seagull requires put strike < lower call strike < upper call strike."]})
    if kind == "reverse_condor" and not strikes["outer_put_strike"] < strikes["inner_put_strike"] < strikes["inner_call_strike"] < strikes["outer_call_strike"]:
        raise InputError({"outer_call_strike": ["Reverse Condor requires K1 < K2 < K3 < K4."]})
    if kind == "double_up_hedge" and not strikes["protective_put_strike"] < contract.spot <= strikes["lower_call_strike"] < strikes["upper_call_strike"]:
        raise InputError({"protective_put_strike": ["Double Up Hedge requires put strike < spot <= K1 < K2."]})
    premiums, leg_quantities, premium_legs, net = {}, {}, [], 0.0
    for key, label, sign, option_type, field in definitions:
        unit_price = black_scholes(option_type, spot, strikes[field], years, rate, dividend, volatility)
        leg_units = abs(sign) * quantity
        premium = unit_price * leg_units
        premiums[key] = unit_price
        leg_quantities[f"{key}_units"] = leg_units
        net += (1 if sign > 0 else -1) * premium
        premium_legs.append({"label": label, "side": "paid" if sign > 0 else "received", "premium": premium, "units": leg_units, "unit_premium": unit_price})
    underlying_units = quantity if kind in {"double_up", "double_up_hedge"} else 0
    if underlying_units:
        leg_quantities["underlying_shares"] = underlying_units
        premium_legs.insert(0, {"label": "Long underlying", "side": "paid", "premium": spot * underlying_units, "units": underlying_units, "unit_premium": spot})
    return {
        "kind": kind, "formula": " + ".join(("" if sign > 0 else "− ") + f"{option_type.upper()}({strikes[field]:g})" for _, _, sign, option_type, field in definitions),
        "contract_snapshot": {"spot": spot, **strikes}, "net_option_cost": net,
        "total_initial_cash_requirement": net + spot * underlying_units, "underlying_value": spot * underlying_units, "unit_premiums": premiums, "leg_quantities": leg_quantities,
        "premium_legs": premium_legs, "sign_convention": "Positive net option cost is a client debit; negative is a client credit.", "warnings": [],
    }


def _price_seagull_ki(data, contract):
    """Price C(K2) - C(K3) - P_DI(K1,B), with a shared lower activation barrier."""
    put_strike = positive_float(data, "put_strike")
    lower_call = positive_float(data, "lower_call_strike")
    upper_call = positive_float(data, "upper_call_strike")
    barrier = positive_float(data, "down_in_barrier")
    if not barrier < put_strike < lower_call < upper_call:
        raise InputError({"down_in_barrier": ["Seagull KI requires B < K1 < K2 < K3."]})
    quantity = positive_float(data, "option_quantity", 1) * positive_float(data, "contract_multiplier", 1)
    engine = MonteCarloBarrierEngine()
    barrier_contract = contract.changed(option_type="put", direction="down", behavior="in", strike=put_strike, barrier=barrier, quantity=1, multiplier=1)
    unit_put = engine.price(barrier_contract, include_greeks=False)
    unit_long_call = black_scholes("call", contract.spot, lower_call, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
    unit_short_call = black_scholes("call", contract.spot, upper_call, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
    net = (unit_long_call - unit_short_call - unit_put["model_price"]) * quantity
    return {
        "kind": "seagull_ki", "formula": "C(K2) − C(K3) − P_DI(K1,B)",
        "contract_snapshot": {"spot": contract.spot, "put_strike": put_strike, "lower_call_strike": lower_call, "upper_call_strike": upper_call, "down_in_barrier": barrier},
        "net_option_cost": net, "total_initial_cash_requirement": net,
        "unit_premiums": {"long_call": unit_long_call, "short_call": unit_short_call, "down_in_put": unit_put["model_price"]},
        "leg_quantities": {"long_call_units": quantity, "short_call_units": quantity, "short_down_in_put_units": quantity},
        "premium_legs": [
            {"label": "Long call", "side": "paid", "premium": unit_long_call * quantity, "units": quantity, "unit_premium": unit_long_call},
            {"label": "Short upper call", "side": "received", "premium": unit_short_call * quantity, "units": quantity, "unit_premium": unit_short_call},
            {"label": "Short Down-and-In put", "side": "received", "premium": unit_put["model_price"] * quantity, "units": quantity, "unit_premium": unit_put["model_price"]},
        ],
        "barrier_diagnostics": unit_put, "warnings": list(unit_put["warnings"]),
        "sign_convention": "The downside put obligation activates only after the lower barrier is touched.",
    }


def _price_collar_or_fence(kind, data, contract):
    if contract.option_type != "call" or contract.direction != "up" or contract.behavior != "in":
        raise InputError({"barrier_leg": ["Collar and Fence templates require an Up-and-In call."]})
    engine = MonteCarloBarrierEngine()
    call_ratio = positive_float(data, "call_quantity_ratio", 1)
    underlying_ratio = positive_float(data, "underlying_quantity_ratio", 1)
    portfolio_value = positive_float(data, "portfolio_value", 10_000_000)
    if "position_allocation_pct" in data:
        allocation_pct = positive_float(data, "position_allocation_pct")
        if allocation_pct > 100:
            raise InputError({"position_allocation_pct": ["Position allocation cannot exceed 100% of the portfolio."]})
        target_position_value = portfolio_value * allocation_pct / 100
        base_quantity = math.floor(target_position_value / (contract.spot * underlying_ratio))
        if base_quantity < 1:
            raise InputError({"position_allocation_pct": ["This allocation is too small to purchase one underlying share."]})
    else:
        base_quantity = positive_float(data, "share_quantity", 1)
        target_position_value = contract.spot * base_quantity * underlying_ratio
        allocation_pct = target_position_value / portfolio_value * 100
    underlying_quantity = base_quantity * underlying_ratio
    call_quantity = base_quantity * call_ratio
    call_price = engine.price(contract.changed(quantity=1, multiplier=1), include_greeks=False)
    vanilla_call = call_price["vanilla_equivalent_price"]
    years = contract.years
    common = {
        "kind": kind,
        "contract_snapshot": {"spot": contract.spot, "call_strike": contract.strike, "barrier": contract.barrier},
        "base_share_quantity": base_quantity,
        "portfolio_context": {
            "portfolio_value": portfolio_value,
            "target_allocation_pct": allocation_pct,
            "target_position_value": target_position_value,
            "actual_position_value": contract.spot * underlying_quantity,
            "actual_allocation_pct": contract.spot * underlying_quantity / portfolio_value * 100,
            "chart_unit": "basis_points_of_portfolio",
        },
        "underlying_value": contract.spot * underlying_quantity,
        "up_in_call_premium": call_price["model_price"] * call_quantity,
        "equivalent_vanilla_call_premium": vanilla_call * call_quantity,
        "vanilla_barrier_premium_difference": (vanilla_call - call_price["model_price"]) * call_quantity,
        "unit_premiums": {
            "up_in_call": call_price["model_price"],
            "equivalent_vanilla_call": vanilla_call,
        },
        "leg_quantities": {
            "underlying_shares": underlying_quantity,
            "short_up_in_call_units": call_quantity,
        },
        "barrier_diagnostics": call_price,
        "sign_convention": "Positive net option cost is a client debit; negative is a client credit.",
    }
    warnings = list(call_price["warnings"])
    if kind == "collar":
        put_strike = positive_float(data, "protective_put_strike")
        put_ratio = positive_float(data, "protective_put_quantity_ratio", 1)
        put_quantity = base_quantity * put_ratio
        if put_strike >= contract.spot:
            warnings.append("The protective put strike is at or above spot; this is not the typical commercial collar configuration.")
        unit_put = black_scholes("put", contract.spot, put_strike, years, contract.rate, contract.dividend_yield, contract.volatility)
        put = unit_put * put_quantity
        net = put - call_price["model_price"] * call_quantity
        common["unit_premiums"]["protective_put"] = unit_put
        common["leg_quantities"]["protective_put_units"] = put_quantity
        common.update({
            "protective_put_premium": put,
            "net_option_cost": net,
            "total_initial_cash_requirement": contract.spot * underlying_quantity + net,
            "maximum_protected_level_at_maturity": put_strike,
            "upside_if_never_touched": "Underlying upside remains uncapped; the Up-and-In call expires inactive.",
            "upside_if_touched": f"Short call payoff begins above strike {contract.strike:g}, scaled by ratio {call_ratio:g}.",
        })
    elif kind == "fence":
        upper = positive_float(data, "upper_put_strike")
        lower = positive_float(data, "lower_put_strike")
        upper_ratio = positive_float(data, "upper_put_quantity_ratio", 1)
        lower_ratio = positive_float(data, "lower_put_quantity_ratio", 1)
        upper_quantity = base_quantity * upper_ratio
        lower_quantity = base_quantity * lower_ratio
        if not lower < upper < contract.spot:
            raise InputError({"lower_put_strike": ["Fence requires lower_put_strike < upper_put_strike < spot."]})
        unit_upper_put = black_scholes("put", contract.spot, upper, years, contract.rate, contract.dividend_yield, contract.volatility)
        unit_lower_put = black_scholes("put", contract.spot, lower, years, contract.rate, contract.dividend_yield, contract.volatility)
        upper_put = unit_upper_put * upper_quantity
        lower_put = unit_lower_put * lower_quantity
        net = upper_put - lower_put - call_price["model_price"] * call_quantity
        common["unit_premiums"].update({"upper_put": unit_upper_put, "lower_put": unit_lower_put})
        common["leg_quantities"].update({"upper_put_units": upper_quantity, "short_lower_put_units": lower_quantity})
        common.update({
            "long_put_premium": upper_put,
            "short_put_premium": lower_put,
            "net_option_cost": net,
            "total_initial_cash_requirement": contract.spot * underlying_quantity + net,
            "protection_interval": [lower, upper],
            "losses_resume_below": lower,
            "upside_if_never_touched": "Underlying upside remains uncapped; the Up-and-In call expires inactive.",
            "upside_if_touched": f"Short call payoff begins above strike {contract.strike:g}, scaled by ratio {call_ratio:g}.",
        })
    else:
        raise InputError({"kind": ["Choose collar or fence."]})
    tolerance = float(data.get("zero_cost_tolerance", 0.01))
    common["zero_cost"] = abs(common["net_option_cost"]) <= tolerance
    common["zero_cost_tolerance"] = tolerance
    if data.get("calculate_structure_greeks"):
        common["structure_greeks"] = structure_greeks(
            kind,
            contract,
            underlying_quantity,
            call_quantity,
            put_quantity if kind == "collar" else upper_quantity,
            None if kind == "collar" else lower_quantity,
            put_strike if kind == "collar" else upper,
            None if kind == "collar" else lower,
        )
    if any(abs(ratio - 1) > 1e-12 for ratio in [underlying_ratio, call_ratio] + ([put_ratio] if kind == "collar" else [upper_ratio, lower_ratio])):
        warnings.append("Non-1:1 leg ratios change the standard protection and participation interpretation.")
    common["warnings"] = warnings
    return common


def _require_up_out_call(contract, template_name):
    if contract.option_type != "call" or contract.direction != "up" or contract.behavior != "out":
        raise InputError({"barrier_leg": [f"{template_name} requires an Up-and-Out call."]})


def _price_nitro(data, contract):
    """Price the standalone long Up-and-Out call sold as Nitro."""
    _require_up_out_call(contract, "Nitro")
    if not contract.spot < contract.strike < contract.barrier:
        raise InputError({"barrier_leg": ["Nitro requires spot < strike < barrier."]})
    option_quantity = positive_float(data, "option_quantity", 1)
    contract_multiplier = positive_float(data, "contract_multiplier", 1)
    option_units = option_quantity * contract_multiplier
    unit_contract = contract.changed(quantity=1, multiplier=1)
    call_price = MonteCarloBarrierEngine().price(unit_contract, include_greeks=False)
    unit_price = call_price["model_price"]
    vanilla_unit_price = call_price["vanilla_equivalent_price"]
    net_option_cost = unit_price * option_units
    return {
        "kind": "nitro",
        "contract_snapshot": {
            "spot": contract.spot,
            "up_out_call_strike": contract.strike,
            "barrier": contract.barrier,
            "option_quantity": option_quantity,
            "contract_multiplier": contract_multiplier,
        },
        "option_quantity": option_quantity,
        "contract_multiplier": contract_multiplier,
        "up_out_call_premium": net_option_cost,
        "equivalent_vanilla_call_premium": vanilla_unit_price * option_units,
        "vanilla_barrier_premium_difference": (vanilla_unit_price - unit_price) * option_units,
        "net_option_cost": net_option_cost,
        "total_initial_cash_requirement": net_option_cost,
        "unit_premiums": {
            "up_out_call": unit_price,
            "vanilla_call": vanilla_unit_price,
        },
        "leg_quantities": {
            "long_up_out_call_contracts": option_quantity,
            "contract_multiplier": contract_multiplier,
            "long_up_out_call_units": option_units,
        },
        "barrier_diagnostics": call_price,
        "sign_convention": "Positive net option cost is a client debit; Nitro is long the Up-and-Out call.",
        "warnings": list(call_price["warnings"]),
    }


def _underlying_position(data, contract):
    underlying_ratio = positive_float(data, "underlying_quantity_ratio", 1)
    portfolio_value = positive_float(data, "portfolio_value", 10_000_000)
    if "position_allocation_pct" in data:
        allocation_pct = positive_float(data, "position_allocation_pct")
        if allocation_pct > 100:
            raise InputError({"position_allocation_pct": ["Position allocation cannot exceed 100% of the portfolio."]})
        target_position_value = portfolio_value * allocation_pct / 100
        base_quantity = math.floor(target_position_value / (contract.spot * underlying_ratio))
        if base_quantity < 1:
            raise InputError({"position_allocation_pct": ["This allocation is too small to purchase one underlying share."]})
    else:
        base_quantity = positive_float(data, "share_quantity", 1)
        target_position_value = contract.spot * base_quantity * underlying_ratio
        allocation_pct = target_position_value / portfolio_value * 100
    underlying_quantity = base_quantity * underlying_ratio
    return base_quantity, underlying_ratio, underlying_quantity, {
        "portfolio_value": portfolio_value,
        "target_allocation_pct": allocation_pct,
        "target_position_value": target_position_value,
        "actual_position_value": contract.spot * underlying_quantity,
        "actual_allocation_pct": contract.spot * underlying_quantity / portfolio_value * 100,
        "chart_unit": "basis_points_of_portfolio",
    }


def _price_double_up_ko(data, contract):
    """Price S + long C_UO(K1, H) - q C(K2), with K1 < K2 < H."""
    _require_up_out_call(contract, "Double Up KO")
    short_vanilla_call_strike = positive_float(data, "short_vanilla_call_strike")
    if not contract.spot < contract.strike < short_vanilla_call_strike < contract.barrier:
        raise InputError({"short_vanilla_call_strike": ["Double Up KO requires spot < K1 < K2 < barrier."]})
    base_quantity, underlying_ratio, underlying_quantity, portfolio_context = _underlying_position(data, contract)
    long_ratio = positive_float(data, "long_up_out_call_quantity_ratio", data.get("call_quantity_ratio", 1))
    short_ratio = positive_float(data, "short_vanilla_call_quantity_ratio", 1)
    long_quantity = base_quantity * long_ratio
    short_quantity = base_quantity * short_ratio
    unit_contract = contract.changed(quantity=1, multiplier=1)
    barrier_call = MonteCarloBarrierEngine().price(unit_contract, include_greeks=False)
    up_out_unit_price = barrier_call["model_price"]
    vanilla_unit_price = black_scholes(
        "call", contract.spot, short_vanilla_call_strike, contract.years,
        contract.rate, contract.dividend_yield, contract.volatility,
    )
    long_up_out_call_premium = up_out_unit_price * long_quantity
    short_vanilla_call_premium = vanilla_unit_price * short_quantity
    net_option_cost = long_up_out_call_premium - short_vanilla_call_premium
    warnings = list(barrier_call["warnings"])
    if any(abs(ratio - 1) > 1e-12 for ratio in (underlying_ratio, long_ratio, short_ratio)):
        warnings.append("Non-1:1 leg ratios change the standard leverage and participation interpretation.")
    return {
        "kind": "double_up_ko",
        "contract_snapshot": {
            "spot": contract.spot,
            "up_out_call_strike": contract.strike,
            "short_vanilla_call_strike": short_vanilla_call_strike,
            "barrier": contract.barrier,
        },
        "base_share_quantity": base_quantity,
        "portfolio_context": portfolio_context,
        "underlying_value": contract.spot * underlying_quantity,
        "up_out_call_premium": long_up_out_call_premium,
        "long_up_out_call_premium": long_up_out_call_premium,
        "short_vanilla_call_premium": short_vanilla_call_premium,
        "equivalent_vanilla_call_premium": barrier_call["vanilla_equivalent_price"] * long_quantity,
        "vanilla_barrier_premium_difference": (barrier_call["vanilla_equivalent_price"] - up_out_unit_price) * long_quantity,
        "net_option_cost": net_option_cost,
        "total_initial_cash_requirement": contract.spot * underlying_quantity + net_option_cost,
        "unit_premiums": {
            "up_out_call": up_out_unit_price,
            "vanilla_call": vanilla_unit_price,
        },
        "leg_quantities": {
            "underlying_shares": underlying_quantity,
            "long_up_out_call_units": long_quantity,
            "short_vanilla_call_units": short_quantity,
        },
        "barrier_diagnostics": barrier_call,
        "sign_convention": "Positive net option cost is a client debit; the vanilla call premium is received because that leg is short.",
        "warnings": warnings,
    }


def _require_down_out(contract, template_name):
    if contract.direction != "down" or contract.behavior != "out":
        raise InputError({"barrier_leg": [f"{template_name} requires a Down-and-Out lower barrier."]})
    if not contract.barrier < contract.spot:
        raise InputError({"barrier_leg": [f"{template_name} requires lower barrier < spot."]})
    if contract.rebate:
        raise InputError({"rebate": [f"{template_name} v1 requires a zero rebate so the stated payoff remains auditable."]})


def _down_out_pair(contract):
    engine = MonteCarloBarrierEngine()
    unit = contract.changed(quantity=1, multiplier=1, rebate=0.0, calculate_greeks=False)
    put = engine.price(unit.changed(option_type="put"), include_greeks=False)
    call = engine.price(unit.changed(option_type="call"), include_greeks=False)
    return put, call


def _holding_result(kind, contract, data):
    base_quantity, _, underlying_quantity, portfolio_context = _underlying_position(data, contract)
    if abs(underlying_quantity - base_quantity) > 1e-12:
        raise InputError({"underlying_quantity_ratio": [f"{kind} requires one underlying share per base structure unit."]})
    return base_quantity, underlying_quantity, portfolio_context


def _price_box_ko(data, contract):
    """Price S + P_DO(K, B) - C_DO(K, B), with one shared lower KO event."""
    _require_down_out(contract, "Box KO")
    shared_ratio = positive_float(data, "option_quantity_ratio", 1)
    if abs(shared_ratio - 1) > 1e-12:
        raise InputError({"option_quantity_ratio": ["Box KO requires a 1:1 put/call ratio to preserve the fixed survivor payoff."]})
    put, call = _down_out_pair(contract)
    base_quantity, underlying_quantity, portfolio_context = _holding_result("box_ko", contract, data)
    put_premium = put["model_price"] * base_quantity
    call_premium = call["model_price"] * base_quantity
    net_option_cost = put_premium - call_premium
    return {
        "kind": "box_ko",
        "formula": "S + P_DO(K, B) - C_DO(K, B)",
        "contract_snapshot": {"spot": contract.spot, "strike": contract.strike, "lower_barrier": contract.barrier},
        "base_share_quantity": base_quantity,
        "portfolio_context": portfolio_context,
        "underlying_value": contract.spot * underlying_quantity,
        "long_down_out_put_premium": put_premium,
        "short_down_out_call_premium": call_premium,
        "net_option_cost": net_option_cost,
        "total_initial_cash_requirement": contract.spot * underlying_quantity + net_option_cost,
        "unit_premiums": {"down_out_put": put["model_price"], "down_out_call": call["model_price"]},
        "leg_quantities": {"underlying_shares": underlying_quantity, "long_down_out_put_units": base_quantity, "short_down_out_call_units": base_quantity},
        "premium_legs": [
            {"label": "Long Down-and-Out put", "side": "paid", "premium": put_premium, "units": base_quantity, "unit_premium": put["model_price"]},
            {"label": "Short Down-and-Out call", "side": "received", "premium": call_premium, "units": base_quantity, "unit_premium": call["model_price"]},
        ],
        "barrier_diagnostics": {"down_out_put": put, "down_out_call": call},
        "sign_convention": "Positive net option cost is a client debit; both barrier options share the same lower knockout event.",
        "warnings": list(dict.fromkeys(put["warnings"] + call["warnings"])),
    }


def _price_box_bullet(data, contract):
    """Price S + Q 1{S_T >= B} - C(B), observed at maturity only."""
    bullet_level = positive_float(data, "bullet_level")
    payout = positive_float(data, "digital_payout")
    if bullet_level >= contract.spot:
        raise InputError({"bullet_level": ["Box Bullet requires bullet_level < spot."]})
    base_quantity, underlying_quantity, portfolio_context = _holding_result("box_bullet", contract, data)
    digital_unit = black_scholes_cash_digital("call", contract.spot, bullet_level, contract.years, contract.rate, contract.dividend_yield, contract.volatility, payout)
    call_unit = black_scholes("call", contract.spot, bullet_level, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
    digital_premium = digital_unit * base_quantity
    call_premium = call_unit * base_quantity
    net_option_cost = digital_premium - call_premium
    return {
        "kind": "box_bullet",
        "formula": "S + Q·1{S_T ≥ B} - C(B) = S_T below B; B + Q at or above B",
        "contract_snapshot": {"spot": contract.spot, "bullet_level": bullet_level, "digital_payout": payout, "monitoring": "maturity_only"},
        "base_share_quantity": base_quantity,
        "portfolio_context": portfolio_context,
        "underlying_value": contract.spot * underlying_quantity,
        "long_digital_call_premium": digital_premium,
        "short_vanilla_call_premium": call_premium,
        "net_option_cost": net_option_cost,
        "total_initial_cash_requirement": contract.spot * underlying_quantity + net_option_cost,
        "unit_premiums": {"cash_digital_call": digital_unit, "vanilla_call": call_unit},
        "leg_quantities": {"underlying_shares": underlying_quantity, "long_digital_call_units": base_quantity, "short_vanilla_call_units": base_quantity},
        "premium_legs": [
            {"label": "Long cash digital call", "side": "paid", "premium": digital_premium, "units": base_quantity, "unit_premium": digital_unit},
            {"label": "Short vanilla call", "side": "received", "premium": call_premium, "units": base_quantity, "unit_premium": call_unit},
        ],
        "sign_convention": "Positive net option cost is a client debit. The digital condition is checked at maturity only.",
        "warnings": [],
    }


def _price_bullet_family(kind, data, contract):
    """Price auditable v1 Bullet variants with a vanilla forward that remains after a lower KO."""
    _require_down_out(contract, kind.replace("_", " ").title())
    forward_strike = positive_float(data, "forward_strike", contract.strike)
    coupon = positive_float(data, "coupon_payout")
    if contract.barrier >= contract.spot:
        raise InputError({"barrier_leg": ["Bullet requires lower barrier < spot."]})
    base_quantity, underlying_quantity, portfolio_context = _holding_result(kind, contract, data)
    engine = MonteCarloBarrierEngine()
    lower_contract = contract.changed(option_type="put", quantity=1, multiplier=1, rebate=0.0, calculate_greeks=False)
    coupon_price = engine.price_cash_digital_barrier(lower_contract, coupon)
    forward_unit = contract.spot * math.exp(-contract.dividend_yield * contract.years) - forward_strike * math.exp(-contract.rate * contract.years)
    coupon_premium = coupon_price["model_price"] * base_quantity
    forward_premium = forward_unit * base_quantity
    net_option_cost = forward_premium + coupon_premium
    result = {
        "kind": kind,
        "formula": "S_T - K_F + Q·L, where L=1 if the lower Down-and-Out barrier survives.",
        "contract_snapshot": {"spot": contract.spot, "forward_strike": forward_strike, "lower_barrier": contract.barrier, "coupon_payout": coupon},
        "base_share_quantity": base_quantity,
        "portfolio_context": portfolio_context,
        "underlying_value": contract.spot * underlying_quantity,
        "forward_component_premium": forward_premium,
        "lower_barrier_coupon_premium": coupon_premium,
        "net_option_cost": net_option_cost,
        "total_initial_cash_requirement": net_option_cost,
        "unit_premiums": {"forward_component": forward_unit, "lower_barrier_coupon": coupon_price["model_price"]},
        "leg_quantities": {"underlying_shares": underlying_quantity, "forward_units": base_quantity, "lower_barrier_coupon_units": base_quantity},
        "premium_legs": [
            {"label": "Long prepaid forward", "side": "paid" if forward_premium >= 0 else "received", "premium": abs(forward_premium), "units": base_quantity, "unit_premium": abs(forward_unit)},
            {"label": "Lower-barrier cash coupon", "side": "paid", "premium": coupon_premium, "units": base_quantity, "unit_premium": coupon_price["model_price"]},
        ],
        "barrier_diagnostics": {"lower_coupon": coupon_price},
        "sign_convention": "Positive net option cost is a client debit. The prepaid forward remains active after the lower barrier is hit.",
        "warnings": list(coupon_price["warnings"]),
    }
    if kind == "bullet_plus":
        upper_strike = positive_float(data, "up_out_call_strike")
        upper_barrier = positive_float(data, "up_out_barrier")
        upper_ratio = positive_float(data, "up_out_call_quantity_ratio", 1)
        if not contract.spot < upper_strike < upper_barrier:
            raise InputError({"up_out_call_strike": ["Bullet Plus requires spot < up_out_call_strike < up_out_barrier."]})
        upper_contract = contract.changed(option_type="call", direction="up", behavior="out", strike=upper_strike, barrier=upper_barrier, quantity=1, multiplier=1, rebate=0.0, calculate_greeks=False)
        upper = engine.price(upper_contract, include_greeks=False)
        upper_units = base_quantity * upper_ratio
        upper_premium = upper["model_price"] * upper_units
        result.update({
            "formula": "S_T - K_F + Q·L + n(S_T-K_U)^+·(1-U), with lower survival L and upper-hit event U.",
            "contract_snapshot": {**result["contract_snapshot"], "up_out_call_strike": upper_strike, "upper_barrier": upper_barrier},
            "long_up_out_call_premium": upper_premium,
            "net_option_cost": net_option_cost + upper_premium,
            "total_initial_cash_requirement": net_option_cost + upper_premium,
            "unit_premiums": {**result["unit_premiums"], "up_out_call": upper["model_price"]},
            "leg_quantities": {**result["leg_quantities"], "long_up_out_call_units": upper_units},
            "premium_legs": result["premium_legs"] + [{"label": "Long Up-and-Out call", "side": "paid", "premium": upper_premium, "units": upper_units, "unit_premium": upper["model_price"]}],
            "barrier_diagnostics": {**result["barrier_diagnostics"], "up_out_call": upper},
            "warnings": list(dict.fromkeys(result["warnings"] + upper["warnings"])),
        })
    if kind == "golden_bullet":
        put_strike = positive_float(data, "protective_put_strike")
        put_ratio = positive_float(data, "protective_put_quantity_ratio", 1)
        if not contract.barrier < put_strike < contract.spot:
            raise InputError({"protective_put_strike": ["Golden Bullet requires lower_barrier < protective_put_strike < spot."]})
        put_contract = lower_contract.changed(strike=put_strike)
        put = engine.price(put_contract, include_greeks=False)
        put_units = base_quantity * put_ratio
        put_premium = put["model_price"] * put_units
        result.update({
            "formula": "S_T - K_F + [Q + n(K_P-S_T)^+]·L, where L=1 if the lower barrier survives.",
            "contract_snapshot": {**result["contract_snapshot"], "protective_put_strike": put_strike},
            "long_down_out_put_premium": put_premium,
            "net_option_cost": net_option_cost + put_premium,
            "total_initial_cash_requirement": net_option_cost + put_premium,
            "unit_premiums": {**result["unit_premiums"], "down_out_put": put["model_price"]},
            "leg_quantities": {**result["leg_quantities"], "long_down_out_put_units": put_units},
            "premium_legs": result["premium_legs"] + [{"label": "Long Down-and-Out put", "side": "paid", "premium": put_premium, "units": put_units, "unit_premium": put["model_price"]}],
            "barrier_diagnostics": {**result["barrier_diagnostics"], "down_out_put": put},
            "warnings": list(dict.fromkeys(result["warnings"] + put["warnings"])),
        })
    return result


def _price_kiko(kind, data, contract):
    """Price the common-event KI.KO package: long C_UO(K1,H), short C_UI(K2,H)."""
    _require_up_out_call(contract, kind.replace("_", " ").upper())
    if contract.rebate:
        raise InputError({"rebate": ["KI.KO v1 requires a zero rebate so the common-event transformation is exact."]})
    short_strike = positive_float(data, "short_up_in_call_strike")
    if not contract.spot < contract.strike < short_strike < contract.barrier:
        raise InputError({"short_up_in_call_strike": ["KI.KO requires spot < K1 < K2 < upper barrier."]})
    base_quantity, underlying_quantity, portfolio_context = _holding_result(kind, contract, data)
    long_ratio = positive_float(data, "long_up_out_call_quantity_ratio", 1)
    short_ratio = positive_float(data, "short_up_in_call_quantity_ratio", 1)
    engine = MonteCarloBarrierEngine()
    upper_out = engine.price(contract.changed(quantity=1, multiplier=1, rebate=0.0), include_greeks=False)
    upper_in = engine.price(contract.changed(behavior="in", strike=short_strike, quantity=1, multiplier=1, rebate=0.0), include_greeks=False)
    long_units = base_quantity * long_ratio
    short_units = base_quantity * short_ratio
    long_premium = upper_out["model_price"] * long_units
    short_premium = upper_in["model_price"] * short_units
    net_option_cost = long_premium - short_premium
    result = {
        "kind": kind,
        "formula": "S + C_UO(K1, H) - C_UI(K2, H), with one shared upper barrier event.",
        "contract_snapshot": {"spot": contract.spot, "up_out_call_strike": contract.strike, "short_up_in_call_strike": short_strike, "upper_barrier": contract.barrier},
        "base_share_quantity": base_quantity,
        "portfolio_context": portfolio_context,
        "underlying_value": contract.spot * underlying_quantity,
        "long_up_out_call_premium": long_premium,
        "short_up_in_call_premium": short_premium,
        "net_option_cost": net_option_cost,
        "total_initial_cash_requirement": contract.spot * underlying_quantity + net_option_cost,
        "unit_premiums": {"up_out_call": upper_out["model_price"], "up_in_call": upper_in["model_price"]},
        "leg_quantities": {"underlying_shares": underlying_quantity, "long_up_out_call_units": long_units, "short_up_in_call_units": short_units},
        "premium_legs": [
            {"label": "Long Up-and-Out call", "side": "paid", "premium": long_premium, "units": long_units, "unit_premium": upper_out["model_price"]},
            {"label": "Short Up-and-In call", "side": "received", "premium": short_premium, "units": short_units, "unit_premium": upper_in["model_price"]},
        ],
        "barrier_diagnostics": {"up_out_call": upper_out, "up_in_call": upper_in},
        "sign_convention": "Positive net option cost is a client debit. When H is hit, the Up-and-Out call disappears and the Up-and-In call activates.",
        "warnings": list(dict.fromkeys(upper_out["warnings"] + upper_in["warnings"])),
    }
    if kind == "collar_kiko":
        put_strike = positive_float(data, "protective_put_strike")
        if not put_strike < contract.spot:
            raise InputError({"protective_put_strike": ["Collar KI.KO requires protective_put_strike < spot."]})
        put_units = base_quantity * positive_float(data, "protective_put_quantity_ratio", 1)
        put_unit = black_scholes("put", contract.spot, put_strike, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
        put_premium = put_unit * put_units
        result.update({
            "formula": "S + P(KP) + C_UO(K1,H) - C_UI(K2,H)",
            "contract_snapshot": {**result["contract_snapshot"], "protective_put_strike": put_strike},
            "long_protective_put_premium": put_premium,
            "net_option_cost": net_option_cost + put_premium,
            "total_initial_cash_requirement": contract.spot * underlying_quantity + net_option_cost + put_premium,
            "unit_premiums": {**result["unit_premiums"], "protective_put": put_unit},
            "leg_quantities": {**result["leg_quantities"], "long_protective_put_units": put_units},
            "premium_legs": result["premium_legs"] + [{"label": "Long protective put", "side": "paid", "premium": put_premium, "units": put_units, "unit_premium": put_unit}],
        })
    if kind == "fence_kiko":
        upper_put = positive_float(data, "upper_put_strike")
        lower_put = positive_float(data, "lower_put_strike")
        if not lower_put < upper_put < contract.spot:
            raise InputError({"lower_put_strike": ["Fence KI.KO requires lower_put_strike < upper_put_strike < spot."]})
        upper_units = base_quantity * positive_float(data, "upper_put_quantity_ratio", 1)
        lower_units = base_quantity * positive_float(data, "lower_put_quantity_ratio", 1)
        upper_unit = black_scholes("put", contract.spot, upper_put, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
        lower_unit = black_scholes("put", contract.spot, lower_put, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
        upper_premium = upper_unit * upper_units
        lower_premium = lower_unit * lower_units
        result.update({
            "formula": "S + P(KP) - P(KL) + C_UO(K1,H) - C_UI(K2,H)",
            "contract_snapshot": {**result["contract_snapshot"], "upper_put_strike": upper_put, "lower_put_strike": lower_put},
            "long_upper_put_premium": upper_premium,
            "short_lower_put_premium": lower_premium,
            "net_option_cost": net_option_cost + upper_premium - lower_premium,
            "total_initial_cash_requirement": contract.spot * underlying_quantity + net_option_cost + upper_premium - lower_premium,
            "unit_premiums": {**result["unit_premiums"], "upper_put": upper_unit, "lower_put": lower_unit},
            "leg_quantities": {**result["leg_quantities"], "long_upper_put_units": upper_units, "short_lower_put_units": lower_units},
            "premium_legs": result["premium_legs"] + [
                {"label": "Long upper put", "side": "paid", "premium": upper_premium, "units": upper_units, "unit_premium": upper_unit},
                {"label": "Short lower put", "side": "received", "premium": lower_premium, "units": lower_units, "unit_premium": lower_unit},
            ],
        })
    return result


def _price_digital(data, contract):
    option_type = str(data.get("digital_option_type", contract.option_type)).lower()
    if option_type not in {"call", "put"}:
        raise InputError({"digital_option_type": ["Choose call or put."]})
    payout = positive_float(data, "digital_payout")
    option_quantity = positive_float(data, "option_quantity", 1)
    contract_multiplier = positive_float(data, "contract_multiplier", 1)
    units = option_quantity * contract_multiplier
    unit_price = black_scholes_cash_digital(option_type, contract.spot, contract.strike, contract.years, contract.rate, contract.dividend_yield, contract.volatility, payout)
    premium = unit_price * units
    return {
        "kind": "digital",
        "formula": f"{payout:g}·1{{S_T {'≥' if option_type == 'call' else '≤'} K}}",
        "contract_snapshot": {"spot": contract.spot, "strike": contract.strike, "option_type": option_type, "digital_payout": payout, "monitoring": "maturity_only"},
        "option_quantity": option_quantity,
        "contract_multiplier": contract_multiplier,
        "digital_premium": premium,
        "net_option_cost": premium,
        "total_initial_cash_requirement": premium,
        "unit_premiums": {f"cash_digital_{option_type}": unit_price},
        "leg_quantities": {f"long_cash_digital_{option_type}_units": units},
        "premium_legs": [{"label": f"Long cash digital {option_type}", "side": "paid", "premium": premium, "units": units, "unit_premium": unit_price}],
        "sign_convention": "Positive net option cost is a client debit. The fixed cash payoff is checked at maturity only.",
        "warnings": ["Digital delta and gamma become highly concentrated near the strike as expiry approaches."],
    }


def structure_greeks(kind, contract, underlying_quantity, call_quantity, long_put_quantity, short_put_quantity, long_put_strike, short_put_strike):
    """Compose signed full-package sensitivities for the barrier and vanilla call alternatives."""
    engine = MonteCarloBarrierEngine()
    unit_contract = contract.changed(quantity=1, multiplier=1, calculate_greeks=False)
    barrier_call = engine.greeks(unit_contract)
    vanilla_call = engine.vanilla_greeks(unit_contract)
    long_put = engine.vanilla_greeks(unit_contract.changed(option_type="put", strike=long_put_strike))
    short_put = (
        engine.vanilla_greeks(unit_contract.changed(option_type="put", strike=short_put_strike))
        if short_put_strike is not None
        else None
    )
    names = ("delta", "gamma", "vega_per_1pct", "theta_per_calendar_day", "rho_per_1bp")
    underlying = {name: (underlying_quantity if name == "delta" else 0.0) for name in names}

    def signed_leg(label, signed_quantity, unit_greeks):
        return {
            "label": label,
            "signed_quantity": signed_quantity,
            "unit_greeks": {name: unit_greeks[name] for name in names},
            "contribution": {name: signed_quantity * unit_greeks[name] for name in names},
        }

    common_legs = [
        {
            "label": "Long underlying",
            "signed_quantity": underlying_quantity,
            "unit_greeks": {name: (1.0 if name == "delta" else 0.0) for name in names},
            "contribution": underlying,
        },
        signed_leg("Long protective put" if kind == "collar" else "Long upper put", long_put_quantity, long_put),
    ]
    if short_put is not None:
        common_legs.append(signed_leg("Short lower put", -short_put_quantity, short_put))
    barrier_legs = common_legs + [signed_leg("Short Up-and-In call", -call_quantity, barrier_call)]
    vanilla_legs = common_legs + [signed_leg("Short vanilla call", -call_quantity, vanilla_call)]

    def total(legs):
        return {name: sum(leg["contribution"][name] for leg in legs) for name in names}

    return {
        "barrier_structure": {"legs": barrier_legs, "total": total(barrier_legs)},
        "vanilla_structure": {"legs": vanilla_legs, "total": total(vanilla_legs)},
        "conventions": {
            "delta": "BRL change in full package value for a R$1 spot move.",
            "gamma": "Change in full-package delta for a R$1 spot move.",
            "vega_per_1pct": "BRL change in full package value for a 1 percentage-point volatility move.",
            "theta_per_calendar_day": "BRL change in full package value after one calendar day passes.",
            "rho_per_1bp": "BRL change in full package value for a 1 bp parallel rate move.",
            "method": "Barrier call uses bump-and-revalue Monte Carlo with the same seed, antithetic paths and Brownian-bridge uniforms for every bump; vanilla legs use the same bump sizes on Black-Scholes values.",
        },
        "bumps": barrier_call["bumps"],
    }


def generic_structure_greeks(kind, data, contract, base_result):
    """Compose full-package Greeks from the structure's actual signed trade legs."""
    engine = MonteCarloBarrierEngine()
    unit = contract.changed(quantity=1, multiplier=1, calculate_greeks=False)
    quantities = base_result["leg_quantities"]
    snapshot = base_result["contract_snapshot"]
    names = ("delta", "gamma", "vega_per_1pct", "theta_per_calendar_day", "rho_per_1bp")
    legs = []

    def add(label, signed_quantity, unit_greeks):
        leg = {
            "label": label,
            "signed_quantity": signed_quantity,
            "unit_greeks": {name: unit_greeks[name] for name in names},
        }
        leg["contribution"] = {name: signed_quantity * leg["unit_greeks"][name] for name in names}
        legs.append(leg)

    def underlying(label="Long underlying"):
        add(label, quantities["underlying_shares"], {name: 1.0 if name == "delta" else 0.0 for name in names})

    def barrier(label, signed_quantity, **changes):
        add(label, signed_quantity, engine.greeks(unit.changed(**changes)))

    def vanilla(label, signed_quantity, option_type, strike):
        add(label, signed_quantity, engine.vanilla_greeks(unit.changed(option_type=option_type, strike=strike)))

    def cash_digital(label, signed_quantity, option_type, strike, payout):
        add(label, signed_quantity, _finite_difference_greeks(
            unit, lambda bumped: black_scholes_cash_digital(
                option_type, bumped.spot, strike, bumped.years, bumped.rate,
                bumped.dividend_yield, bumped.volatility, payout,
            ),
        ))

    def barrier_cash_digital(label, signed_quantity, payout):
        add(label, signed_quantity, _finite_difference_greeks(
            unit, lambda bumped: engine.price_cash_digital_barrier(bumped, payout)["model_price"],
        ))

    if kind == "nitro":
        barrier("Long Up-and-Out call", quantities["long_up_out_call_units"])
    elif kind == "double_up_ko":
        underlying()
        barrier("Long Up-and-Out call", quantities["long_up_out_call_units"])
        vanilla("Short vanilla call", -quantities["short_vanilla_call_units"], "call", snapshot["short_vanilla_call_strike"])
    elif kind == "box_ko":
        underlying()
        barrier("Long Down-and-Out put", quantities["long_down_out_put_units"], option_type="put")
        barrier("Short Down-and-Out call", -quantities["short_down_out_call_units"], option_type="call")
    elif kind == "box_bullet":
        underlying()
        cash_digital("Long cash digital call", quantities["long_digital_call_units"], "call", snapshot["bullet_level"], snapshot["digital_payout"])
        vanilla("Short vanilla call", -quantities["short_vanilla_call_units"], "call", snapshot["bullet_level"])
    elif kind in {"bullet", "bullet_plus", "golden_bullet"}:
        add("Long prepaid forward", quantities["forward_units"], _finite_difference_greeks(
            unit, lambda bumped: bumped.spot * math.exp(-bumped.dividend_yield * bumped.years)
            - snapshot["forward_strike"] * math.exp(-bumped.rate * bumped.years),
        ))
        barrier_cash_digital("Long lower-barrier cash coupon", quantities["lower_barrier_coupon_units"], snapshot["coupon_payout"])
        if kind == "bullet_plus":
            upper_contract = unit.changed(option_type="call", direction="up", behavior="out", strike=snapshot["up_out_call_strike"], barrier=snapshot["upper_barrier"])
            add("Long Up-and-Out call", quantities["long_up_out_call_units"], engine.greeks(upper_contract))
        elif kind == "golden_bullet":
            barrier("Long Down-and-Out put", quantities["long_down_out_put_units"], option_type="put", strike=snapshot["protective_put_strike"])
    elif kind in {"collar_kiko", "fence_kiko", "call_kiko"}:
        underlying()
        barrier("Long Up-and-Out call", quantities["long_up_out_call_units"])
        barrier("Short Up-and-In call", -quantities["short_up_in_call_units"], behavior="in", strike=snapshot["short_up_in_call_strike"])
        if kind == "collar_kiko":
            vanilla("Long protective put", quantities["long_protective_put_units"], "put", snapshot["protective_put_strike"])
        elif kind == "fence_kiko":
            vanilla("Long upper put", quantities["long_upper_put_units"], "put", snapshot["upper_put_strike"])
            vanilla("Short lower put", -quantities["short_lower_put_units"], "put", snapshot["lower_put_strike"])
    elif kind == "digital":
        option_type = snapshot["option_type"]
        cash_digital(f"Long cash digital {option_type}", quantities[f"long_cash_digital_{option_type}_units"], option_type, snapshot["strike"], snapshot["digital_payout"])
    elif kind in VANILLA_STRATEGY_DEFINITIONS:
        if kind in {"double_up", "double_up_hedge"}:
            underlying()
        definitions = {
            "call_spread": [("Long call", 1, "call", "lower_call_strike", "long_call_units"), ("Short call", -1, "call", "upper_call_strike", "short_call_units")],
            "risk_reversal": [("Long call", 1, "call", "call_strike", "long_call_units"), ("Short put", -1, "put", "put_strike", "short_put_units")],
            "seagull": [("Long call", 1, "call", "lower_call_strike", "long_call_units"), ("Short upper call", -1, "call", "upper_call_strike", "short_call_units"), ("Short put", -1, "put", "put_strike", "short_put_units")],
            "straddle": [("Long call", 1, "call", "common_strike", "long_call_units"), ("Long put", 1, "put", "common_strike", "long_put_units")],
            "strangle": [("Long call", 1, "call", "call_strike", "long_call_units"), ("Long put", 1, "put", "put_strike", "long_put_units")],
            "reverse_condor": [("Long outer put", 1, "put", "outer_put_strike", "long_put_units"), ("Short inner put", -1, "put", "inner_put_strike", "short_put_units"), ("Short inner call", -1, "call", "inner_call_strike", "short_call_units"), ("Long outer call", 1, "call", "outer_call_strike", "long_call_units")],
            "double_up": [("Long accelerating call", 1, "call", "lower_call_strike", "long_call_units"), ("Two short limiter calls", -1, "call", "upper_call_strike", "short_call_units")],
            "double_up_hedge": [("Long protective put", 1, "put", "protective_put_strike", "protective_put_units"), ("Long accelerating call", 1, "call", "lower_call_strike", "long_call_units"), ("Two short limiter calls", -1, "call", "upper_call_strike", "short_call_units")],
        }[kind]
        for label, sign, option_type, strike_key, quantity_key in definitions:
            vanilla(label, sign * quantities[quantity_key], option_type, snapshot[strike_key])
    elif kind == "seagull_ki":
        vanilla("Long call", quantities["long_call_units"], "call", snapshot["lower_call_strike"])
        vanilla("Short upper call", -quantities["short_call_units"], "call", snapshot["upper_call_strike"])
        barrier("Short Down-and-In put", -quantities["short_down_in_put_units"], option_type="put", direction="down", behavior="in", strike=snapshot["put_strike"], barrier=snapshot["down_in_barrier"])
    totals = {name: sum(leg["contribution"][name] for leg in legs) for name in names}
    return {
        "barrier_structure": {"legs": legs, "total": totals},
        "conventions": {
            "delta": "BRL change in full package value for a R$1 spot move.",
            "gamma": "Change in full-package delta for a R$1 spot move.",
            "vega_per_1pct": "BRL change in full package value for a 1 percentage-point volatility move.",
            "theta_per_calendar_day": "BRL change in full package value after one calendar day passes.",
            "rho_per_1bp": "BRL change in full package value for a 1 bp parallel rate move.",
            "method": "Signed leg sensitivities are composed using fixed trade quantities; Monte Carlo barrier legs reuse common random numbers for their bumps.",
        },
        "bumps": {"spot": max(contract.spot * 0.01, 0.01), "volatility": 0.01, "rate": 0.0001, "theta_days": 1},
    }


def _finite_difference_greeks(contract, value):
    """Apply the shared Greek bump convention to an arbitrary unit leg pricer."""
    spot_bump = max(contract.spot * 0.01, 0.01)
    vol_bump = 0.01
    rate_bump = 0.0001
    base = value(contract)
    up = value(contract.changed(spot=contract.spot + spot_bump))
    down = value(contract.changed(spot=contract.spot - spot_bump))
    remaining_days = (contract.expiration_date - contract.valuation_date).days
    theta_contract = contract.changed(valuation_date=contract.valuation_date.fromordinal(contract.valuation_date.toordinal() + 1))
    return {
        "delta": (up - down) / (2 * spot_bump),
        "gamma": (up - 2 * base + down) / spot_bump**2,
        "vega_per_1pct": (value(contract.changed(volatility=contract.volatility + vol_bump)) - value(contract.changed(volatility=max(0.0001, contract.volatility - vol_bump)))) / 2,
        "theta_per_calendar_day": value(theta_contract) - base if remaining_days > 1 else -base,
        "rho_per_1bp": (value(contract.changed(rate=contract.rate + rate_bump)) - value(contract.changed(rate=contract.rate - rate_bump))) / 2,
    }


def maturity_scenarios(kind, data, contract, structure_result):
    if kind in VANILLA_STRATEGY_DEFINITIONS:
        return _vanilla_strategy_maturity_scenarios(kind, data, contract, structure_result)
    if kind == "seagull_ki":
        return _seagull_ki_maturity_scenarios(data, contract, structure_result)
    if kind == "nitro":
        return _nitro_maturity_scenarios(data, contract, structure_result)
    if kind == "double_up_ko":
        return _double_up_ko_maturity_scenarios(data, contract, structure_result)
    if kind == "box_ko":
        return _box_ko_maturity_scenarios(data, contract, structure_result)
    if kind == "box_bullet":
        return _box_bullet_maturity_scenarios(data, contract, structure_result)
    if kind in {"bullet", "bullet_plus", "golden_bullet"}:
        return _bullet_family_maturity_scenarios(kind, data, contract, structure_result)
    if kind in {"collar_kiko", "fence_kiko", "call_kiko"}:
        return _kiko_maturity_scenarios(kind, data, contract, structure_result)
    if kind == "digital":
        return _digital_maturity_scenarios(data, contract, structure_result)
    low = float(data.get("scenario_min", contract.spot * 0.5))
    high = float(data.get("scenario_max", contract.spot * 1.5))
    points = int(data.get("scenario_points", 61))
    terminal = np.linspace(low, high, points)
    underlying_ratio = float(data.get("underlying_quantity_ratio", 1))
    call_ratio = float(data.get("call_quantity_ratio", 1))
    base_quantity = structure_result["base_share_quantity"]
    portfolio_value = structure_result["portfolio_context"]["portfolio_value"]
    underlying_quantity = base_quantity * underlying_ratio
    call_quantity = base_quantity * call_ratio
    initial = structure_result["underlying_value"] + structure_result["net_option_cost"]
    states = {}
    outcome_summary = {}
    premium_basis = abs(structure_result["net_option_cost"])
    for label, triggered in (("barrier_never_triggered", False), ("barrier_triggered", True)):
        underlying_payoff = terminal * underlying_quantity
        call_payoff = -np.maximum(terminal - contract.strike, 0) * call_quantity if triggered else np.zeros(points)
        if kind == "collar":
            put_payoff = np.maximum(float(data["protective_put_strike"]) - terminal, 0) * base_quantity * float(data.get("protective_put_quantity_ratio", 1))
            total = underlying_payoff + put_payoff + call_payoff
            legs = {"underlying": underlying_payoff, "protective_put": put_payoff, "up_in_call": call_payoff}
        else:
            long_put = np.maximum(float(data["upper_put_strike"]) - terminal, 0) * base_quantity * float(data.get("upper_put_quantity_ratio", 1))
            short_put = -np.maximum(float(data["lower_put_strike"]) - terminal, 0) * base_quantity * float(data.get("lower_put_quantity_ratio", 1))
            total = underlying_payoff + long_put + short_put + call_payoff
            legs = {"underlying": underlying_payoff, "long_put": long_put, "short_put": short_put, "up_in_call": call_payoff}
        states[label] = [{
            "terminal_price": float(terminal[i]),
            "underlying_pnl": float(underlying_payoff[i] - contract.spot * underlying_quantity),
            "underlying_pnl_bps": float((underlying_payoff[i] - contract.spot * underlying_quantity) / portfolio_value * 10_000),
            "leg_payoffs": {name: float(values[i]) for name, values in legs.items()},
            "total_payoff": float(total[i]),
            "total_pnl": float(total[i] - initial),
            "total_pnl_bps": float((total[i] - initial) / portfolio_value * 10_000),
        } for i in range(points)]
        best_pnl = float(np.max(total - initial))
        worst_pnl = float(np.min(total - initial))
        downside_payoff_at_zero = float(total[0]) if low == 0 else (
            float(data["protective_put_strike"]) * base_quantity * float(data.get("protective_put_quantity_ratio", 1))
            if kind == "collar"
            else float(data["upper_put_strike"]) * base_quantity * float(data.get("upper_put_quantity_ratio", 1))
            - float(data["lower_put_strike"]) * base_quantity * float(data.get("lower_put_quantity_ratio", 1))
        )
        downside_pnl_at_zero = downside_payoff_at_zero - initial
        residual_upside_ratio = underlying_quantity - (call_quantity if triggered else 0)
        if residual_upside_ratio > 0:
            maximum_payoff = "Unlimited"
            upside_explanation = f"Net upside participation remains {residual_upside_ratio:g} underlying unit(s) above the call strike."
        elif residual_upside_ratio == 0:
            maximum_payoff = contract.strike * call_quantity
            upside_explanation = f"Payoff is capped once terminal price is above the call strike {contract.strike:g}."
        else:
            maximum_payoff = float(np.max(total))
            upside_explanation = "The short-call ratio exceeds the underlying ratio, so losses can resume as the asset rises."
        outcome_summary[label] = {
            "maximum_payoff": maximum_payoff,
            "best_pnl_in_chart_range": best_pnl,
            "worst_pnl_in_chart_range": worst_pnl,
            "downside_payoff_at_zero": downside_payoff_at_zero,
            "downside_pnl_at_zero": downside_pnl_at_zero,
            "best_pnl_to_net_premium_multiple": None if premium_basis <= 1e-9 else best_pnl / premium_basis,
            "worst_pnl_to_net_premium_multiple": None if premium_basis <= 1e-9 else worst_pnl / premium_basis,
            "net_option_premium_basis": premium_basis,
            "multiple_note": "Undefined for a zero-cost package." if premium_basis <= 1e-9 else "Multiples use the absolute net option premium, not the total underlying investment.",
            "upside_explanation": upside_explanation,
        }
    return {
        "kind": kind,
        "initial_investment": initial,
        "net_option_cost": structure_result["net_option_cost"],
        "portfolio_context": structure_result["portfolio_context"],
        "scenario_range": [low, high],
        "states": states,
        "outcome_summary": outcome_summary,
    }


def _nitro_maturity_scenarios(data, contract, structure_result):
    low = float(data.get("scenario_min", contract.spot * 0.5))
    high = float(data.get("scenario_max", contract.spot * 1.5))
    points = int(data.get("scenario_points", 61))
    terminal = np.linspace(low, high, points)
    option_units = structure_result["leg_quantities"]["long_up_out_call_units"]
    initial = structure_result["net_option_cost"]
    no_hit_payoff = np.maximum(terminal - contract.strike, 0) * option_units
    knockout_payoff = np.full(points, contract.rebate * option_units)

    def rows(payoff, label, leg_name):
        return [{
            "terminal_price": float(terminal[i]),
            "barrier_state": label,
            "leg_payoffs": {leg_name: float(payoff[i])},
            "total_payoff": float(payoff[i]),
            "total_pnl": float(payoff[i] - initial),
            "total_pnl_to_initial_premium_multiple": None if initial <= 1e-9 else float((payoff[i] - initial) / initial),
        } for i in range(points)]

    states = {
        "knockout_not_triggered": rows(no_hit_payoff, "not_triggered", "long_up_out_call"),
        "knockout_triggered": rows(knockout_payoff, "triggered", "knockout_rebate"),
    }
    return {
        "kind": "nitro",
        "initial_investment": initial,
        "net_option_cost": initial,
        "scenario_range": [low, high],
        "chart_unit": "BRL",
        "states": states,
        "outcome_summary": {
            "knockout_not_triggered": {
                "maximum_payoff_in_chart_range": float(np.max(no_hit_payoff)),
                "best_pnl_in_chart_range": float(np.max(no_hit_payoff - initial)),
                "worst_pnl_in_chart_range": float(np.min(no_hit_payoff - initial)),
                "description": "The Up-and-Out call remains alive and pays its call intrinsic value at expiry.",
            },
            "knockout_triggered": {
                "maximum_payoff_in_chart_range": float(contract.rebate * option_units),
                "best_pnl_in_chart_range": float(contract.rebate * option_units - initial),
                "worst_pnl_in_chart_range": float(contract.rebate * option_units - initial),
                "description": "The Up-and-Out call has been eliminated; only the contractual rebate remains, if any.",
            },
        },
    }


def _double_up_ko_maturity_scenarios(data, contract, structure_result):
    low = float(data.get("scenario_min", contract.spot * 0.5))
    high = float(data.get("scenario_max", contract.spot * 1.5))
    points = int(data.get("scenario_points", 61))
    terminal = np.linspace(low, high, points)
    portfolio_value = structure_result["portfolio_context"]["portfolio_value"]
    quantities = structure_result["leg_quantities"]
    underlying_quantity = quantities["underlying_shares"]
    long_quantity = quantities["long_up_out_call_units"]
    short_quantity = quantities["short_vanilla_call_units"]
    short_strike = structure_result["contract_snapshot"]["short_vanilla_call_strike"]
    initial = structure_result["total_initial_cash_requirement"]
    underlying_payoff = terminal * underlying_quantity
    long_up_out_payoff = np.maximum(terminal - contract.strike, 0) * long_quantity
    short_vanilla_payoff = -np.maximum(terminal - short_strike, 0) * short_quantity

    def rows(label, up_out_payoff):
        total = underlying_payoff + up_out_payoff + short_vanilla_payoff
        return [{
            "terminal_price": float(terminal[i]),
            "barrier_state": label,
            "underlying_pnl": float(underlying_payoff[i] - contract.spot * underlying_quantity),
            "underlying_pnl_bps": float((underlying_payoff[i] - contract.spot * underlying_quantity) / portfolio_value * 10_000),
            "leg_payoffs": {
                "underlying": float(underlying_payoff[i]),
                "long_up_out_call": float(up_out_payoff[i]),
                "short_vanilla_call": float(short_vanilla_payoff[i]),
            },
            "total_payoff": float(total[i]),
            "total_pnl": float(total[i] - initial),
            "total_pnl_bps": float((total[i] - initial) / portfolio_value * 10_000),
        } for i in range(points)], total

    no_hit_rows, no_hit_total = rows("not_triggered", long_up_out_payoff)
    knockout_rows, knockout_total = rows("triggered", np.zeros(points))
    return {
        "kind": "double_up_ko",
        "initial_investment": initial,
        "net_option_cost": structure_result["net_option_cost"],
        "portfolio_context": structure_result["portfolio_context"],
        "scenario_range": [low, high],
        "states": {
            "knockout_not_triggered": no_hit_rows,
            "knockout_triggered": knockout_rows,
        },
        "outcome_summary": {
            "knockout_not_triggered": {
                "best_pnl_in_chart_range": float(np.max(no_hit_total - initial)),
                "worst_pnl_in_chart_range": float(np.min(no_hit_total - initial)),
                "description": "The Up-and-Out call remains alive: S + C_UO(K1, H) - qC(K2).",
            },
            "knockout_triggered": {
                "best_pnl_in_chart_range": float(np.max(knockout_total - initial)),
                "worst_pnl_in_chart_range": float(np.min(knockout_total - initial)),
                "description": "The Up-and-Out call has been eliminated: S - qC(K2).",
            },
        },
    }


def _scenario_terminal(data, contract):
    low = float(data.get("scenario_min", contract.spot * 0.5))
    high = float(data.get("scenario_max", contract.spot * 1.5))
    points = int(data.get("scenario_points", 61))
    return low, high, np.linspace(low, high, points)


def _holding_rows(terminal, payoff, initial, structure_result, leg_payoffs, barrier_state):
    portfolio_value = structure_result["portfolio_context"]["portfolio_value"]
    underlying_quantity = structure_result["leg_quantities"]["underlying_shares"]
    spot = structure_result["contract_snapshot"]["spot"]
    return [{
        "terminal_price": float(terminal[i]),
        "barrier_state": barrier_state,
        "underlying_pnl": float(terminal[i] * underlying_quantity - spot * underlying_quantity),
        "underlying_pnl_bps": float((terminal[i] * underlying_quantity - spot * underlying_quantity) / portfolio_value * 10_000),
        "leg_payoffs": {name: float(values[i]) for name, values in leg_payoffs.items()},
        "total_payoff": float(payoff[i]),
        "total_pnl": float(payoff[i] - initial),
        "total_pnl_bps": float((payoff[i] - initial) / portfolio_value * 10_000),
    } for i in range(len(terminal))]


def _outcome(payoff, initial, description):
    return {
        "best_pnl_in_chart_range": float(np.max(payoff - initial)),
        "worst_pnl_in_chart_range": float(np.min(payoff - initial)),
        "description": description,
    }


def _box_ko_maturity_scenarios(data, contract, structure_result):
    low, high, terminal = _scenario_terminal(data, contract)
    quantity = structure_result["leg_quantities"]["underlying_shares"]
    initial = structure_result["total_initial_cash_requirement"]
    survive = np.full(len(terminal), contract.strike * quantity)
    triggered = terminal * quantity
    return {
        "kind": "box_ko", "chart_unit": "basis_points_of_portfolio", "initial_investment": initial,
        "net_option_cost": structure_result["net_option_cost"], "portfolio_context": structure_result["portfolio_context"], "scenario_range": [low, high],
        "states": {
            "lower_barrier_not_triggered": _holding_rows(terminal, survive, initial, structure_result, {"underlying": terminal * quantity, "long_down_out_put": np.maximum(contract.strike-terminal, 0)*quantity, "short_down_out_call": -np.maximum(terminal-contract.strike, 0)*quantity}, "lower_not_triggered"),
            "lower_barrier_triggered": _holding_rows(terminal, triggered, initial, structure_result, {"underlying": triggered, "long_down_out_put": np.zeros(len(terminal)), "short_down_out_call": np.zeros(len(terminal))}, "lower_triggered"),
        },
        "outcome_summary": {
            "lower_barrier_not_triggered": _outcome(survive, initial, "Both Down-and-Out options survive, so put-call parity fixes the terminal package value at K."),
            "lower_barrier_triggered": _outcome(triggered, initial, "Both options have knocked out; the client remains exposed to the underlying."),
        },
    }


def _box_bullet_maturity_scenarios(data, contract, structure_result):
    low, high, terminal = _scenario_terminal(data, contract)
    quantity = structure_result["leg_quantities"]["underlying_shares"]
    level = structure_result["contract_snapshot"]["bullet_level"]
    payout = structure_result["contract_snapshot"]["digital_payout"]
    initial = structure_result["total_initial_cash_requirement"]
    digital = np.where(terminal >= level, payout * quantity, 0.0)
    short_call = -np.maximum(terminal - level, 0) * quantity
    payoff = terminal * quantity + digital + short_call
    return {
        "kind": "box_bullet", "chart_unit": "basis_points_of_portfolio", "initial_investment": initial,
        "net_option_cost": structure_result["net_option_cost"], "portfolio_context": structure_result["portfolio_context"], "scenario_range": [low, high],
        "states": {"maturity_observation": _holding_rows(terminal, payoff, initial, structure_result, {"underlying": terminal*quantity, "cash_digital_call": digital, "short_vanilla_call": short_call}, "maturity_observation")},
        "outcome_summary": {"maturity_observation": _outcome(payoff, initial, "Below B the package pays S_T; at or above B it pays B plus the fixed digital payout.")},
    }


def _bullet_family_maturity_scenarios(kind, data, contract, structure_result):
    low, high, terminal = _scenario_terminal(data, contract)
    quantity = structure_result["leg_quantities"]["underlying_shares"]
    forward_strike = structure_result["contract_snapshot"]["forward_strike"]
    coupon = structure_result["contract_snapshot"]["coupon_payout"]
    initial = structure_result["total_initial_cash_requirement"]
    forward = (terminal - forward_strike) * quantity
    coupon_payoff = np.full(len(terminal), coupon * quantity)

    def lower_payoff(survives):
        return forward + (coupon_payoff if survives else 0.0)

    if kind == "golden_bullet":
        put_strike = structure_result["contract_snapshot"]["protective_put_strike"]
        put = np.maximum(put_strike-terminal, 0) * structure_result["leg_quantities"]["long_down_out_put_units"]
        survivor = lower_payoff(True) + put
        knocked = lower_payoff(False)
        survivor_legs = {"prepaid_forward": forward, "lower_barrier_coupon": coupon_payoff, "long_down_out_put": put}
        knocked_legs = {"prepaid_forward": forward, "lower_barrier_coupon": np.zeros(len(terminal)), "long_down_out_put": np.zeros(len(terminal))}
    else:
        survivor = lower_payoff(True)
        knocked = lower_payoff(False)
        survivor_legs = {"prepaid_forward": forward, "lower_barrier_coupon": coupon_payoff}
        knocked_legs = {"prepaid_forward": forward, "lower_barrier_coupon": np.zeros(len(terminal))}
    states = {
        "lower_barrier_not_triggered": _holding_rows(terminal, survivor, initial, structure_result, survivor_legs, "lower_not_triggered"),
        "lower_barrier_triggered": _holding_rows(terminal, knocked, initial, structure_result, knocked_legs, "lower_triggered"),
    }
    summary = {
        "lower_barrier_not_triggered": _outcome(survivor, initial, "The lower barrier survives, so the coupon and any Down-and-Out put remain active."),
        "lower_barrier_triggered": _outcome(knocked, initial, "The lower coupon and Down-and-Out protection disappear, but the prepaid forward remains active."),
    }
    if kind == "bullet_plus":
        upper_strike = structure_result["contract_snapshot"]["up_out_call_strike"]
        upper_call = np.maximum(terminal-upper_strike, 0) * structure_result["leg_quantities"]["long_up_out_call_units"]
        expanded = {}
        expanded_summary = {}
        for lower_label, lower_payoff_value, lower_legs in (("not_triggered", survivor, survivor_legs), ("triggered", knocked, knocked_legs)):
            for upper_label, upper_payoff in (("not_triggered", upper_call), ("triggered", np.zeros(len(terminal)))):
                key = f"lower_barrier_{lower_label}_upper_barrier_{upper_label}"
                payoff = lower_payoff_value + upper_payoff
                expanded[key] = _holding_rows(terminal, payoff, initial, structure_result, {**lower_legs, "long_up_out_call": upper_payoff}, f"lower_{lower_label}; upper_{upper_label}")
                expanded_summary[key] = _outcome(payoff, initial, "The lower coupon state and upper Up-and-Out call state are shown independently.")
        states, summary = expanded, expanded_summary
    return {
        "kind": kind, "chart_unit": "basis_points_of_portfolio", "initial_investment": initial,
        "net_option_cost": structure_result["net_option_cost"], "portfolio_context": structure_result["portfolio_context"], "scenario_range": [low, high],
        "states": states, "outcome_summary": summary,
    }


def _kiko_maturity_scenarios(kind, data, contract, structure_result):
    low, high, terminal = _scenario_terminal(data, contract)
    quantities = structure_result["leg_quantities"]
    underlying = terminal * quantities["underlying_shares"]
    k1 = structure_result["contract_snapshot"]["up_out_call_strike"]
    k2 = structure_result["contract_snapshot"]["short_up_in_call_strike"]
    initial = structure_result["total_initial_cash_requirement"]
    live_out = np.maximum(terminal-k1, 0) * quantities["long_up_out_call_units"]
    live_in = -np.maximum(terminal-k2, 0) * quantities["short_up_in_call_units"]
    protection = np.zeros(len(terminal))
    protection_legs = {}
    if kind == "collar_kiko":
        protection = np.maximum(structure_result["contract_snapshot"]["protective_put_strike"]-terminal, 0) * quantities["long_protective_put_units"]
        protection_legs = {"long_protective_put": protection}
    if kind == "fence_kiko":
        upper_put = np.maximum(structure_result["contract_snapshot"]["upper_put_strike"]-terminal, 0) * quantities["long_upper_put_units"]
        lower_put = -np.maximum(structure_result["contract_snapshot"]["lower_put_strike"]-terminal, 0) * quantities["short_lower_put_units"]
        protection = upper_put + lower_put
        protection_legs = {"long_upper_put": upper_put, "short_lower_put": lower_put}
    not_triggered = underlying + protection + live_out
    triggered = underlying + protection + live_in
    return {
        "kind": kind, "chart_unit": "basis_points_of_portfolio", "initial_investment": initial,
        "net_option_cost": structure_result["net_option_cost"], "portfolio_context": structure_result["portfolio_context"], "scenario_range": [low, high],
        "states": {
            "upper_barrier_not_triggered": _holding_rows(terminal, not_triggered, initial, structure_result, {"underlying": underlying, **protection_legs, "long_up_out_call": live_out, "short_up_in_call": np.zeros(len(terminal))}, "upper_not_triggered"),
            "upper_barrier_triggered": _holding_rows(terminal, triggered, initial, structure_result, {"underlying": underlying, **protection_legs, "long_up_out_call": np.zeros(len(terminal)), "short_up_in_call": live_in}, "upper_triggered"),
        },
        "outcome_summary": {
            "upper_barrier_not_triggered": _outcome(not_triggered, initial, "The Up-and-Out call survives and the Up-and-In call remains inactive."),
            "upper_barrier_triggered": _outcome(triggered, initial, "The Up-and-Out call is eliminated and the short Up-and-In call has activated."),
        },
    }


def _digital_maturity_scenarios(data, contract, structure_result):
    low, high, terminal = _scenario_terminal(data, contract)
    snapshot = structure_result["contract_snapshot"]
    units = next(iter(structure_result["leg_quantities"].values()))
    payoff = np.where(terminal >= snapshot["strike"], snapshot["digital_payout"], 0.0) if snapshot["option_type"] == "call" else np.where(terminal <= snapshot["strike"], snapshot["digital_payout"], 0.0)
    payoff *= units
    initial = structure_result["total_initial_cash_requirement"]
    label = f"long_cash_digital_{snapshot['option_type']}"
    rows = [{
        "terminal_price": float(terminal[i]), "barrier_state": "maturity_observation",
        "leg_payoffs": {label: float(payoff[i])}, "total_payoff": float(payoff[i]), "total_pnl": float(payoff[i] - initial),
    } for i in range(len(terminal))]
    return {
        "kind": "digital", "chart_unit": "BRL", "initial_investment": initial, "net_option_cost": initial, "scenario_range": [low, high],
        "states": {"maturity_observation": rows},
        "outcome_summary": {"maturity_observation": _outcome(payoff, initial, "The cash payout is received only if the terminal price finishes on the selected side of strike.")},
    }


def _vanilla_strategy_maturity_scenarios(kind, data, contract, structure_result):
    low, high, terminal = _scenario_terminal(data, contract)
    snapshot, quantities = structure_result["contract_snapshot"], structure_result["leg_quantities"]
    definitions = {
        "call_spread": [("long_call", 1, "call", "lower_call_strike", "long_call_units"), ("short_call", -1, "call", "upper_call_strike", "short_call_units")],
        "risk_reversal": [("long_call", 1, "call", "call_strike", "long_call_units"), ("short_put", -1, "put", "put_strike", "short_put_units")],
        "seagull": [("long_call", 1, "call", "lower_call_strike", "long_call_units"), ("short_call", -1, "call", "upper_call_strike", "short_call_units"), ("short_put", -1, "put", "put_strike", "short_put_units")],
        "straddle": [("long_call", 1, "call", "common_strike", "long_call_units"), ("long_put", 1, "put", "common_strike", "long_put_units")],
        "strangle": [("long_call", 1, "call", "call_strike", "long_call_units"), ("long_put", 1, "put", "put_strike", "long_put_units")],
        "reverse_condor": [("long_outer_put", 1, "put", "outer_put_strike", "long_put_units"), ("short_inner_put", -1, "put", "inner_put_strike", "short_put_units"), ("short_inner_call", -1, "call", "inner_call_strike", "short_call_units"), ("long_outer_call", 1, "call", "outer_call_strike", "long_call_units")],
        "double_up": [("long_accelerating_call", 1, "call", "lower_call_strike", "long_call_units"), ("short_limiter_calls", -1, "call", "upper_call_strike", "short_call_units")],
        "double_up_hedge": [("protective_put", 1, "put", "protective_put_strike", "protective_put_units"), ("long_accelerating_call", 1, "call", "lower_call_strike", "long_call_units"), ("short_limiter_calls", -1, "call", "upper_call_strike", "short_call_units")],
    }[kind]
    leg_payoffs = {}
    if kind in {"double_up", "double_up_hedge"}:
        leg_payoffs["underlying"] = terminal * quantities["underlying_shares"]
    for label, sign, option_type, strike_key, quantity_key in definitions:
        intrinsic = np.maximum(terminal - snapshot[strike_key], 0) if option_type == "call" else np.maximum(snapshot[strike_key] - terminal, 0)
        leg_payoffs[label] = sign * intrinsic * quantities[quantity_key]
    payoff = sum(leg_payoffs.values())
    initial = structure_result["total_initial_cash_requirement"]
    rows = [{"terminal_price": float(terminal[i]), "barrier_state": "maturity", "leg_payoffs": {key: float(value[i]) for key, value in leg_payoffs.items()}, "total_payoff": float(payoff[i]), "total_pnl": float(payoff[i] - initial)} for i in range(len(terminal))]
    return {"kind": kind, "chart_unit": "BRL", "initial_investment": initial, "net_option_cost": initial, "scenario_range": [low, high], "states": {"maturity_payoff": rows}, "outcome_summary": {"maturity_payoff": _outcome(payoff, initial, "European vanilla legs are observed at expiry; use the leg toggles to isolate each contribution.")}}


def _seagull_ki_maturity_scenarios(data, contract, structure_result):
    low, high, terminal = _scenario_terminal(data, contract)
    snapshot, quantities = structure_result["contract_snapshot"], structure_result["leg_quantities"]
    long_call = np.maximum(terminal - snapshot["lower_call_strike"], 0) * quantities["long_call_units"]
    short_call = -np.maximum(terminal - snapshot["upper_call_strike"], 0) * quantities["short_call_units"]
    initial = structure_result["net_option_cost"]
    states = {}
    for state, triggered in (("lower_barrier_not_triggered", False), ("lower_barrier_triggered", True)):
        short_put = -np.maximum(snapshot["put_strike"] - terminal, 0) * quantities["short_down_in_put_units"] if triggered else np.zeros_like(terminal)
        legs = {"long_call": long_call, "short_upper_call": short_call, "short_down_in_put": short_put}
        payoff = sum(legs.values())
        states[state] = [{"terminal_price": float(terminal[i]), "barrier_state": state, "leg_payoffs": {key: float(value[i]) for key, value in legs.items()}, "total_payoff": float(payoff[i]), "total_pnl": float(payoff[i] - initial)} for i in range(len(terminal))]
    return {"kind": "seagull_ki", "chart_unit": "BRL", "initial_investment": initial, "net_option_cost": initial, "scenario_range": [low, high], "states": states, "outcome_summary": {key: _outcome(np.array([row["total_payoff"] for row in rows]), initial, "The short put contributes only after the lower barrier has activated it.") for key, rows in states.items()}}
