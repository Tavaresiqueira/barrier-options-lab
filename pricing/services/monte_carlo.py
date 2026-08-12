import math

import numpy as np

from .calendar import observation_dates
from .domain import BarrierContract
from .vanilla import black_scholes


class MonteCarloBarrierEngine:
    name = "gbm-monte-carlo-brownian-bridge"

    def _randoms(self, paths: int, steps: int, seed: int):
        rng = np.random.default_rng(seed)
        half = (paths + 1) // 2
        base_z = rng.standard_normal((half, steps))
        base_u = rng.random((half, steps))
        z = np.concatenate([base_z, -base_z], axis=0)[:paths]
        u = np.concatenate([base_u, 1.0 - base_u], axis=0)[:paths]
        return z, u

    def _steps(self, contract: BarrierContract) -> int:
        if contract.monitoring == "continuous":
            return max(1, math.ceil(252 * contract.years))
        return max(1, len(observation_dates(contract.valuation_date, contract.expiration_date, "daily_close")))

    def _simulate(self, contract: BarrierContract):
        steps = self._steps(contract)
        dt = contract.years / steps
        z, uniforms = self._randoms(contract.paths, steps, contract.seed)
        increments = (contract.rate - contract.dividend_yield - 0.5 * contract.volatility**2) * dt + contract.volatility * math.sqrt(dt) * z
        log_paths = np.cumsum(increments, axis=1)
        prices = contract.spot * np.exp(log_paths)
        prior = np.column_stack([np.full(contract.paths, contract.spot), prices[:, :-1]])

        if contract.monitoring == "continuous":
            if contract.direction == "up":
                endpoint_hit = (prior >= contract.barrier) | (prices >= contract.barrier)
                a = np.maximum(np.log(contract.barrier / prior), 0.0)
                b = np.maximum(np.log(contract.barrier / prices), 0.0)
            else:
                endpoint_hit = (prior <= contract.barrier) | (prices <= contract.barrier)
                a = np.maximum(np.log(prior / contract.barrier), 0.0)
                b = np.maximum(np.log(prices / contract.barrier), 0.0)
            crossing_probability = np.exp(-2.0 * a * b / (contract.volatility**2 * dt))
            interval_hit = endpoint_hit | (uniforms < crossing_probability)
        else:
            session_dates = observation_dates(contract.valuation_date, contract.expiration_date, "daily_close")
            chosen_dates = observation_dates(contract.valuation_date, contract.expiration_date, contract.monitoring)
            chosen = set(chosen_dates)
            mask = np.array([session in chosen for session in session_dates], dtype=bool)
            monitored_prices = prices[:, mask]
            interval_hit = monitored_prices >= contract.barrier if contract.direction == "up" else monitored_prices <= contract.barrier

        hit = interval_hit.any(axis=1)
        first_hit = np.argmax(interval_hit, axis=1) + 1
        return prices[:, -1], hit, first_hit, steps

    def _terminal_values(self, contract: BarrierContract):
        terminal, hit, first_hit, steps = self._simulate(contract)
        intrinsic = np.maximum(terminal - contract.strike, 0.0) if contract.option_type == "call" else np.maximum(contract.strike - terminal, 0.0)
        active = hit if contract.behavior == "in" else ~hit
        discount = math.exp(-contract.rate * contract.years)
        values = discount * intrinsic * active
        rebate_event = ~active
        if contract.rebate:
            if contract.behavior == "out" and contract.rebate_timing == "immediate":
                rebate_discount = np.exp(-contract.rate * contract.years * first_hit / steps)
                values += contract.rebate * rebate_discount * rebate_event
            else:
                values += discount * contract.rebate * rebate_event
        return values, terminal, hit, active

    def price(self, contract: BarrierContract, include_greeks: bool | None = None) -> dict:
        vanilla = black_scholes(contract.option_type, contract.spot, contract.strike, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
        discount = math.exp(-contract.rate * contract.years)
        forward = contract.spot * math.exp((contract.rate - contract.dividend_yield) * contract.years)

        if contract.barrier_status == "triggered":
            if contract.behavior == "in":
                unit_price = vanilla
            else:
                unit_price = contract.rebate * (1.0 if contract.rebate_timing == "immediate" else discount)
            result = self._deterministic_result(contract, unit_price, vanilla, discount, forward)
        else:
            values, terminal, hit, active = self._terminal_values(contract)
            unit_price = float(values.mean())
            std_error = float(values.std(ddof=1) / math.sqrt(contract.paths))
            result = {
                "model_price": unit_price,
                "premium_per_unit": unit_price,
                "total_premium": unit_price * contract.quantity * contract.multiplier,
                "vanilla_equivalent_price": vanilla,
                "discount_factor": discount,
                "forward_price": forward,
                "barrier_hit_probability": float(hit.mean()),
                "probability_ending_itm": float(((terminal > contract.strike) if contract.option_type == "call" else (terminal < contract.strike)).mean()),
                "probability_active_at_expiry": float(active.mean()),
                "standard_error": std_error,
                "confidence_interval": [unit_price - 1.96 * std_error, unit_price + 1.96 * std_error],
            }

        opposite = contract.changed(behavior="out" if contract.behavior == "in" else "in", rebate=0.0, calculate_greeks=False)
        this_no_rebate = contract.changed(rebate=0.0, calculate_greeks=False)
        pair_price = self._plain_price(opposite)
        this_price = self._plain_price(this_no_rebate)
        parity_residual = vanilla - this_price - pair_price
        parity_noise = result["standard_error"] + self._plain_standard_error(opposite)
        result["parity"] = {
            "knock_in": this_price if contract.behavior == "in" else pair_price,
            "knock_out": pair_price if contract.behavior == "in" else this_price,
            "residual": parity_residual,
            "expected_noise": parity_noise,
            "warning": bool(abs(parity_residual) > 2.0 * max(parity_noise, 1e-12)),
        }
        result["simulation"] = {"engine": self.name, "paths": contract.paths, "seed": contract.seed, "monitoring": contract.monitoring, "antithetic": True}
        result["assumptions"] = ["GBM under the risk-neutral measure", "constant volatility, rate and continuous dividend yield", "no jumps, local volatility, stochastic volatility or discrete dividends"]
        result["warnings"] = self._warnings(contract, result)
        if include_greeks if include_greeks is not None else contract.calculate_greeks:
            result["greeks"] = self.greeks(contract)
        return result

    def price_cash_digital_barrier(self, contract: BarrierContract, payout: float) -> dict:
        """Price a cash payout contingent on a barrier option remaining active."""
        discount = math.exp(-contract.rate * contract.years)
        if contract.barrier_status == "triggered":
            active_probability = 1.0 if contract.behavior == "in" else 0.0
            return {
                "model_price": payout * discount * active_probability,
                "premium_per_unit": payout * discount * active_probability,
                "barrier_hit_probability": 1.0,
                "probability_active_at_expiry": active_probability,
                "standard_error": 0.0,
                "warnings": self._warnings(contract, {"parity": {}}),
            }
        _, hit, _, _ = self._simulate(contract)
        active = hit if contract.behavior == "in" else ~hit
        values = payout * discount * active
        std_error = float(values.std(ddof=1) / math.sqrt(contract.paths))
        return {
            "model_price": float(values.mean()),
            "premium_per_unit": float(values.mean()),
            "barrier_hit_probability": float(hit.mean()),
            "probability_active_at_expiry": float(active.mean()),
            "standard_error": std_error,
            "warnings": self._warnings(contract, {"parity": {}}),
        }

    def _deterministic_result(self, contract, unit_price, vanilla, discount, forward):
        return {
            "model_price": unit_price,
            "premium_per_unit": unit_price,
            "total_premium": unit_price * contract.quantity * contract.multiplier,
            "vanilla_equivalent_price": vanilla,
            "discount_factor": discount,
            "forward_price": forward,
            "barrier_hit_probability": 1.0,
            "probability_ending_itm": None,
            "probability_active_at_expiry": 1.0 if contract.behavior == "in" else 0.0,
            "standard_error": 0.0,
            "confidence_interval": [unit_price, unit_price],
        }

    def _plain_price(self, contract):
        if contract.barrier_status == "triggered":
            if contract.behavior == "in":
                return black_scholes(contract.option_type, contract.spot, contract.strike, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
            return contract.rebate * (1.0 if contract.rebate_timing == "immediate" else math.exp(-contract.rate * contract.years))
        return float(self._terminal_values(contract)[0].mean())

    def _plain_standard_error(self, contract):
        if contract.barrier_status == "triggered":
            return 0.0
        values = self._terminal_values(contract)[0]
        return float(values.std(ddof=1) / math.sqrt(contract.paths))

    def greeks(self, contract):
        spot_bump = max(contract.spot * 0.01, 0.01)
        vol_bump = 0.01
        rate_bump = 0.0001
        day = 1.0 / 365.0
        base = self._plain_price(contract)
        up = self._plain_price(contract.changed(spot=contract.spot + spot_bump))
        down = self._plain_price(contract.changed(spot=contract.spot - spot_bump))
        later_expiry_days = max(1, (contract.expiration_date - contract.valuation_date).days - 1)
        theta_contract = contract.changed(valuation_date=contract.expiration_date.fromordinal(contract.expiration_date.toordinal() - later_expiry_days))
        return {
            "delta": (up - down) / (2 * spot_bump),
            "gamma": (up - 2 * base + down) / spot_bump**2,
            "vega_per_1pct": (self._plain_price(contract.changed(volatility=contract.volatility + vol_bump)) - self._plain_price(contract.changed(volatility=max(0.0001, contract.volatility - vol_bump)))) / 2,
            "theta_per_calendar_day": self._plain_price(theta_contract) - base if contract.years > day else -base,
            "rho_per_1bp": (self._plain_price(contract.changed(rate=contract.rate + rate_bump)) - self._plain_price(contract.changed(rate=contract.rate - rate_bump))) / 2,
            "bumps": {"spot": spot_bump, "volatility": vol_bump, "rate": rate_bump, "theta_days": 1},
        }

    def vanilla_greeks(self, contract):
        """Return vanilla Greeks using the same finite-difference conventions as barriers."""
        spot_bump = max(contract.spot * 0.01, 0.01)
        vol_bump = 0.01
        rate_bump = 0.0001
        day = 1.0 / 365.0
        base = black_scholes(contract.option_type, contract.spot, contract.strike, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
        up = black_scholes(contract.option_type, contract.spot + spot_bump, contract.strike, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
        down = black_scholes(contract.option_type, contract.spot - spot_bump, contract.strike, contract.years, contract.rate, contract.dividend_yield, contract.volatility)
        later_expiry_days = max(1, (contract.expiration_date - contract.valuation_date).days - 1)
        theta_contract = contract.changed(valuation_date=contract.expiration_date.fromordinal(contract.expiration_date.toordinal() - later_expiry_days))
        return {
            "delta": (up - down) / (2 * spot_bump),
            "gamma": (up - 2 * base + down) / spot_bump**2,
            "vega_per_1pct": (black_scholes(contract.option_type, contract.spot, contract.strike, contract.years, contract.rate, contract.dividend_yield, contract.volatility + vol_bump) - black_scholes(contract.option_type, contract.spot, contract.strike, contract.years, contract.rate, contract.dividend_yield, max(0.0001, contract.volatility - vol_bump))) / 2,
            "theta_per_calendar_day": black_scholes(theta_contract.option_type, theta_contract.spot, theta_contract.strike, theta_contract.years, theta_contract.rate, theta_contract.dividend_yield, theta_contract.volatility) - base if contract.years > day else -base,
            "rho_per_1bp": (black_scholes(contract.option_type, contract.spot, contract.strike, contract.years, contract.rate + rate_bump, contract.dividend_yield, contract.volatility) - black_scholes(contract.option_type, contract.spot, contract.strike, contract.years, contract.rate - rate_bump, contract.dividend_yield, contract.volatility)) / 2,
            "bumps": {"spot": spot_bump, "volatility": vol_bump, "rate": rate_bump, "theta_days": 1},
        }

    def _warnings(self, contract, result):
        warnings = []
        if contract.direction == "up" and contract.behavior == "in" and contract.option_type == "call" and contract.monitoring == "continuous" and contract.barrier <= contract.strike:
            warnings.append("For a continuously monitored Up-and-In call with H ≤ K, every in-the-money terminal path must have crossed the barrier; its value should be approximately vanilla.")
        if result.get("parity", {}).get("warning"):
            warnings.append("The in-out parity residual exceeds twice the estimated combined Monte Carlo noise.")
        if contract.barrier_status == "not_applicable":
            warnings.append("'Not applicable' is treated as not previously triggered; no historical path was inferred from spot.")
        return warnings
