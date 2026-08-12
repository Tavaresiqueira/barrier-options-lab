import math

from scipy.stats import norm


def black_scholes(option_type: str, spot: float, strike: float, years: float, rate: float, dividend_yield: float, volatility: float) -> float:
    if years <= 0:
        return max(spot - strike, 0.0) if option_type == "call" else max(strike - spot, 0.0)
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - dividend_yield + 0.5 * volatility**2) * years) / (volatility * root_t)
    d2 = d1 - volatility * root_t
    if option_type == "call":
        return float(spot * math.exp(-dividend_yield * years) * norm.cdf(d1) - strike * math.exp(-rate * years) * norm.cdf(d2))
    return float(strike * math.exp(-rate * years) * norm.cdf(-d2) - spot * math.exp(-dividend_yield * years) * norm.cdf(-d1))


def black_scholes_cash_digital(option_type: str, spot: float, strike: float, years: float, rate: float, dividend_yield: float, volatility: float, payout: float) -> float:
    """Price a cash-or-nothing option paying ``payout`` at expiry."""
    if years <= 0:
        if option_type == "call":
            return payout if spot >= strike else 0.0
        return payout if spot <= strike else 0.0
    root_t = math.sqrt(years)
    d2 = (math.log(spot / strike) + (rate - dividend_yield - 0.5 * volatility**2) * years) / (volatility * root_t)
    probability = norm.cdf(d2) if option_type == "call" else norm.cdf(-d2)
    return float(payout * math.exp(-rate * years) * probability)
