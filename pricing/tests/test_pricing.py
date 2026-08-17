import math
from datetime import date, timedelta
from unittest.mock import patch

from django.test import SimpleTestCase

from pricing.services.domain import BarrierContract
from pricing.services.monte_carlo import MonteCarloBarrierEngine
from pricing.services.monitoring import monitoring_equivalence
from pricing.services.structures import maturity_scenarios, price_structure
from pricing.services.validation import InputError, parse_contract
from pricing.services.vanilla import black_scholes, black_scholes_cash_digital


def contract(**changes):
    values = {
        "option_type": "call",
        "direction": "up",
        "behavior": "in",
        "spot": 100.0,
        "strike": 105.0,
        "barrier": 120.0,
        "valuation_date": date(2026, 1, 2),
        "expiration_date": date(2027, 1, 2),
        "rate": 0.10,
        "dividend_yield": 0.03,
        "volatility": 0.25,
        "paths": 20_000,
        "seed": 7,
    }
    values.update(changes)
    return BarrierContract(**values)


class VanillaTests(SimpleTestCase):
    def test_black_scholes_known_benchmark(self):
        self.assertAlmostEqual(black_scholes("call", 100, 100, 1, 0.05, 0, 0.2), 10.4506, places=3)
        self.assertAlmostEqual(black_scholes("put", 100, 100, 1, 0.05, 0, 0.2), 5.5735, places=3)

    def test_cash_digital_black_scholes_known_probability_price(self):
        expected = 10 * math.exp(-.05) * 0.5596177
        self.assertAlmostEqual(black_scholes_cash_digital("call", 100, 100, 1, .05, 0, .2, 10), expected, places=3)


class BarrierTests(SimpleTestCase):
    engine = MonteCarloBarrierEngine()

    @patch.dict("os.environ", {"MAX_MONTE_CARLO_PATHS": "12000"})
    def test_deployment_path_limit_is_configurable(self):
        payload = contract(paths=20_000).as_dict()
        with self.assertRaises(InputError) as error:
            parse_contract(payload)
        self.assertIn("12,000", error.exception.errors["paths"][0])

    @patch("pricing.services.monitoring.price_structure")
    def test_monitoring_equivalence_moves_up_barrier_farther(self, mocked_price):
        c = contract(behavior="out", barrier=130, monitoring="continuous", paths=5_000)

        def synthetic_price(kind, data, trial):
            value = trial.barrier if trial.monitoring == "continuous" else 142.0
            return {"net_option_cost": value}

        mocked_price.side_effect = synthetic_price
        result = monitoring_equivalence("nitro", {}, c, "monthly")
        self.assertAlmostEqual(result["equivalent_continuous_barrier"], 142, places=2)
        self.assertGreater(result["barrier_shift_brl"], 0)
        self.assertAlmostEqual(result["matching_residual"], 0, places=2)

    def test_in_out_parity(self):
        result = self.engine.price(contract())
        self.assertLess(abs(result["parity"]["residual"]), 2 * result["parity"]["expected_noise"])

    def test_triggered_knock_in_is_vanilla(self):
        result = self.engine.price(contract(barrier_status="triggered"))
        self.assertAlmostEqual(result["model_price"], result["vanilla_equivalent_price"], places=12)

    def test_triggered_knock_out_is_rebate(self):
        result = self.engine.price(contract(behavior="out", barrier_status="triggered", rebate=2))
        self.assertAlmostEqual(result["model_price"], 2 * result["discount_factor"], places=12)
        zero = self.engine.price(contract(behavior="out", barrier_status="triggered"))
        self.assertEqual(zero["model_price"], 0)

    def test_up_in_call_not_above_vanilla(self):
        result = self.engine.price(contract())
        self.assertLessEqual(result["model_price"], result["vanilla_equivalent_price"])

    def test_down_out_not_above_vanilla(self):
        result = self.engine.price(contract(direction="down", behavior="out", barrier=70))
        self.assertLessEqual(result["model_price"], result["vanilla_equivalent_price"])

    def test_distant_knock_out_approaches_vanilla(self):
        result = self.engine.price(contract(behavior="out", barrier=1000))
        self.assertLess(abs(result["model_price"] - result["vanilla_equivalent_price"]), 3 * result["standard_error"] + 0.1)

    def test_close_knock_out_approaches_zero(self):
        result = self.engine.price(contract(behavior="out", barrier=100.01))
        self.assertLess(result["model_price"], 0.3)

    def test_discrete_in_no_more_than_continuous(self):
        continuous = self.engine.price(contract(monitoring="continuous"))["model_price"]
        discrete = self.engine.price(contract(monitoring="monthly"))["model_price"]
        self.assertLessEqual(discrete, continuous + 1e-12)

    def test_discrete_out_no_less_than_continuous(self):
        continuous = self.engine.price(contract(behavior="out", monitoring="continuous"))["model_price"]
        discrete = self.engine.price(contract(behavior="out", monitoring="monthly"))["model_price"]
        self.assertGreaterEqual(discrete, continuous - 1e-12)

    def test_seed_reproducibility_and_confidence_interval(self):
        first = self.engine.price(contract())
        second = self.engine.price(contract())
        self.assertEqual(first["model_price"], second["model_price"])
        self.assertLess(first["confidence_interval"][0], first["model_price"])
        self.assertGreater(first["confidence_interval"][1], first["model_price"])
        self.assertGreater(first["standard_error"], 0)

    def test_special_up_in_warning(self):
        result = self.engine.price(contract(strike=120, barrier=115))
        self.assertTrue(any("H ≤ K" in warning for warning in result["warnings"]))

    def test_greeks_and_bumps(self):
        result = self.engine.price(contract(paths=5_000, calculate_greeks=True))
        self.assertEqual(set(result["greeks"]["bumps"]), {"spot", "volatility", "rate", "theta_days"})


class StructureTests(SimpleTestCase):
    def test_nitro_decomposition_uses_option_contract_units(self):
        c = contract(behavior="out", paths=5_000, rebate=1.5)
        data = {"option_quantity": 2, "contract_multiplier": 100}
        result = price_structure("nitro", data, c)
        unit_price = MonteCarloBarrierEngine().price(c.changed(quantity=1, multiplier=1))["model_price"]

        self.assertAlmostEqual(result["unit_premiums"]["up_out_call"], unit_price)
        self.assertAlmostEqual(result["up_out_call_premium"], unit_price * 200)
        self.assertAlmostEqual(result["net_option_cost"], result["up_out_call_premium"])
        self.assertAlmostEqual(result["total_initial_cash_requirement"], result["net_option_cost"])
        self.assertEqual(result["leg_quantities"]["long_up_out_call_contracts"], 2)
        self.assertEqual(result["leg_quantities"]["contract_multiplier"], 100)
        self.assertEqual(result["leg_quantities"]["long_up_out_call_units"], 200)
        self.assertGreater(result["vanilla_barrier_premium_difference"], 0)

    def test_nitro_requires_a_standard_up_out_call_configuration(self):
        with self.assertRaises(InputError) as wrong_behavior:
            price_structure("nitro", {"option_quantity": 1}, contract())
        self.assertIn("barrier_leg", wrong_behavior.exception.errors)

        with self.assertRaises(InputError) as invalid_strikes:
            price_structure("nitro", {"option_quantity": 1}, contract(behavior="out", strike=120))
        self.assertIn("barrier_leg", invalid_strikes.exception.errors)

        with self.assertRaises(InputError) as invalid_quantity:
            price_structure("nitro", {"option_quantity": 0}, contract(behavior="out"))
        self.assertIn("option_quantity", invalid_quantity.exception.errors)

    def test_nitro_scenarios_distinguish_live_call_from_knockout(self):
        c = contract(behavior="out", rebate=2, paths=5_000)
        result = price_structure("nitro", {"option_quantity": 2, "contract_multiplier": 10}, c)
        scenarios = maturity_scenarios("nitro", {"scenario_min": 100, "scenario_max": 140, "scenario_points": 3}, c, result)

        live = scenarios["states"]["knockout_not_triggered"][2]
        knocked_out = scenarios["states"]["knockout_triggered"][2]
        self.assertEqual(live["leg_payoffs"]["long_up_out_call"], 700)
        self.assertEqual(knocked_out["leg_payoffs"]["knockout_rebate"], 40)
        self.assertNotIn("total_pnl_bps", live)
        self.assertEqual(scenarios["chart_unit"], "BRL")

    def test_double_up_ko_decomposition_has_signed_option_costs(self):
        c = contract(behavior="out", barrier=130, paths=5_000)
        data = {
            "share_quantity": 100,
            "underlying_quantity_ratio": 1,
            "long_up_out_call_quantity_ratio": 2,
            "short_vanilla_call_quantity_ratio": .5,
            "short_vanilla_call_strike": 115,
        }
        result = price_structure("double_up_ko", data, c)
        expected = result["long_up_out_call_premium"] - result["short_vanilla_call_premium"]

        self.assertAlmostEqual(result["net_option_cost"], expected)
        self.assertAlmostEqual(result["total_initial_cash_requirement"], result["underlying_value"] + expected)
        self.assertEqual(result["leg_quantities"]["underlying_shares"], 100)
        self.assertEqual(result["leg_quantities"]["long_up_out_call_units"], 200)
        self.assertEqual(result["leg_quantities"]["short_vanilla_call_units"], 50)
        self.assertEqual(result["contract_snapshot"]["up_out_call_strike"], 105)
        self.assertEqual(result["contract_snapshot"]["short_vanilla_call_strike"], 115)
        self.assertGreater(result["vanilla_barrier_premium_difference"], 0)

    def test_double_up_ko_uses_portfolio_sizing_and_knockout_states(self):
        c = contract(behavior="out", barrier=130, paths=5_000)
        data = {
            "portfolio_value": 1_000_000,
            "position_allocation_pct": 10,
            "underlying_quantity_ratio": 1,
            "long_up_out_call_quantity_ratio": 1,
            "short_vanilla_call_quantity_ratio": 1,
            "short_vanilla_call_strike": 115,
            "scenario_min": 100,
            "scenario_max": 120,
            "scenario_points": 3,
        }
        result = price_structure("double_up_ko", data, c)
        scenarios = maturity_scenarios("double_up_ko", data, c, result)
        no_hit = scenarios["states"]["knockout_not_triggered"][2]
        knocked_out = scenarios["states"]["knockout_triggered"][2]

        self.assertEqual(result["base_share_quantity"], 1_000)
        self.assertEqual(no_hit["leg_payoffs"]["underlying"], 120_000)
        self.assertEqual(no_hit["leg_payoffs"]["long_up_out_call"], 15_000)
        self.assertEqual(no_hit["leg_payoffs"]["short_vanilla_call"], -5_000)
        self.assertEqual(knocked_out["leg_payoffs"]["long_up_out_call"], 0)
        self.assertAlmostEqual(no_hit["total_pnl_bps"], no_hit["total_pnl"] / 1_000_000 * 10_000)

    def test_double_up_ko_requires_k1_k2_barrier_ordering(self):
        c = contract(behavior="out", barrier=130)
        with self.assertRaises(InputError) as invalid_order:
            price_structure("double_up_ko", {"share_quantity": 100, "short_vanilla_call_strike": 104}, c)
        self.assertIn("short_vanilla_call_strike", invalid_order.exception.errors)

        with self.assertRaises(InputError) as invalid_ratio:
            price_structure("double_up_ko", {
                "share_quantity": 100,
                "short_vanilla_call_strike": 115,
                "long_up_out_call_quantity_ratio": 0,
            }, c)
        self.assertIn("long_up_out_call_quantity_ratio", invalid_ratio.exception.errors)

    def test_collar_decomposition(self):
        c = contract(paths=5_000)
        data = {"protective_put_strike": 90, "share_quantity": 100, "call_quantity_ratio": 1, "protective_put_quantity_ratio": 1, "underlying_quantity_ratio": 1}
        result = price_structure("collar", data, c)
        expected = result["protective_put_premium"] - result["up_in_call_premium"]
        self.assertAlmostEqual(result["net_option_cost"], expected)
        self.assertAlmostEqual(result["total_initial_cash_requirement"], result["underlying_value"] + expected)
        self.assertEqual(result["leg_quantities"]["underlying_shares"], 100)
        self.assertEqual(result["leg_quantities"]["protective_put_units"], 100)
        self.assertEqual(result["leg_quantities"]["short_up_in_call_units"], 100)

    def test_portfolio_allocation_drives_structure_quantities_and_scenario_bps(self):
        c = contract(spot=100, paths=5_000)
        data = {
            "protective_put_strike": 90,
            "portfolio_value": 10_000_000,
            "position_allocation_pct": 10,
            "call_quantity_ratio": 1,
            "protective_put_quantity_ratio": 1,
            "underlying_quantity_ratio": 1,
        }
        result = price_structure("collar", data, c)
        scenarios = maturity_scenarios("collar", data, c, result)
        self.assertEqual(result["base_share_quantity"], 10_000)
        self.assertEqual(result["underlying_value"], 1_000_000)
        self.assertEqual(result["portfolio_context"]["actual_allocation_pct"], 10)
        first = scenarios["states"]["barrier_never_triggered"][0]
        self.assertAlmostEqual(first["total_pnl_bps"], first["total_pnl"] / 10_000_000 * 10_000)

    def test_fence_decomposition(self):
        c = contract(paths=5_000)
        data = {"upper_put_strike": 90, "lower_put_strike": 75, "share_quantity": 200, "call_quantity_ratio": .5, "upper_put_quantity_ratio": 1, "lower_put_quantity_ratio": .75, "underlying_quantity_ratio": 1}
        result = price_structure("fence", data, c)
        expected = result["long_put_premium"] - result["short_put_premium"] - result["up_in_call_premium"]
        self.assertAlmostEqual(result["net_option_cost"], expected)
        self.assertAlmostEqual(result["total_initial_cash_requirement"], result["underlying_value"] + expected)
        self.assertEqual(result["leg_quantities"]["underlying_shares"], 200)
        self.assertEqual(result["leg_quantities"]["upper_put_units"], 200)
        self.assertEqual(result["leg_quantities"]["short_lower_put_units"], 150)
        self.assertEqual(result["leg_quantities"]["short_up_in_call_units"], 100)

    def test_structure_greeks_are_signed_and_scaled_for_the_full_package(self):
        c = contract(paths=2_000)
        data = {
            "protective_put_strike": 90,
            "share_quantity": 100,
            "underlying_quantity_ratio": 1.2,
            "protective_put_quantity_ratio": 1.5,
            "call_quantity_ratio": .5,
            "calculate_structure_greeks": True,
        }
        result = price_structure("collar", data, c)
        greeks = result["structure_greeks"]
        barrier_legs = {leg["label"]: leg for leg in greeks["barrier_structure"]["legs"]}
        vanilla_legs = {leg["label"]: leg for leg in greeks["vanilla_structure"]["legs"]}

        self.assertEqual(barrier_legs["Long underlying"]["signed_quantity"], 120)
        self.assertEqual(barrier_legs["Long protective put"]["signed_quantity"], 150)
        self.assertEqual(barrier_legs["Short Up-and-In call"]["signed_quantity"], -50)
        self.assertEqual(vanilla_legs["Short vanilla call"]["signed_quantity"], -50)
        self.assertEqual(barrier_legs["Long underlying"]["contribution"]["delta"], 120)
        self.assertEqual(barrier_legs["Long underlying"]["contribution"]["gamma"], 0)
        for name, total in greeks["barrier_structure"]["total"].items():
            self.assertAlmostEqual(total, sum(leg["contribution"][name] for leg in barrier_legs.values()))
        for name, total in greeks["vanilla_structure"]["total"].items():
            self.assertAlmostEqual(total, sum(leg["contribution"][name] for leg in vanilla_legs.values()))

    def test_every_retail_structure_family_returns_full_package_greeks(self):
        up_out = contract(behavior="out", barrier=130, paths=256)
        down_out = contract(option_type="put", direction="down", behavior="out", strike=90, barrier=70, paths=256)
        cases = [
            ("nitro", up_out, {"option_quantity": 2}),
            ("double_up_ko", up_out, {"share_quantity": 10, "short_vanilla_call_strike": 115}),
            ("box_ko", down_out, {"share_quantity": 10}),
            ("box_bullet", contract(paths=256), {"share_quantity": 10, "bullet_level": 80, "digital_payout": 5}),
            ("bullet", down_out, {"share_quantity": 10, "coupon_payout": 4}),
            ("bullet_plus", down_out, {"share_quantity": 10, "coupon_payout": 4, "up_out_call_strike": 110, "up_out_barrier": 130}),
            ("golden_bullet", down_out, {"share_quantity": 10, "coupon_payout": 4, "protective_put_strike": 85}),
            ("call_kiko", up_out, {"share_quantity": 10, "short_up_in_call_strike": 115}),
            ("collar_kiko", up_out, {"share_quantity": 10, "short_up_in_call_strike": 115, "protective_put_strike": 90}),
            ("fence_kiko", up_out, {"share_quantity": 10, "short_up_in_call_strike": 115, "upper_put_strike": 90, "lower_put_strike": 75}),
            ("digital", contract(paths=256), {"digital_option_type": "put", "digital_payout": 25}),
        ]
        expected = {"delta", "gamma", "vega_per_1pct", "theta_per_calendar_day", "rho_per_1bp"}
        expected_legs = {
            "nitro": {"Long Up-and-Out call"},
            "double_up_ko": {"Long underlying", "Long Up-and-Out call", "Short vanilla call"},
            "box_ko": {"Long underlying", "Long Down-and-Out put", "Short Down-and-Out call"},
            "box_bullet": {"Long underlying", "Long cash digital call", "Short vanilla call"},
            "bullet": {"Long prepaid forward", "Long lower-barrier cash coupon"},
            "bullet_plus": {"Long prepaid forward", "Long lower-barrier cash coupon", "Long Up-and-Out call"},
            "golden_bullet": {"Long prepaid forward", "Long lower-barrier cash coupon", "Long Down-and-Out put"},
            "call_kiko": {"Long underlying", "Long Up-and-Out call", "Short Up-and-In call"},
            "collar_kiko": {"Long underlying", "Long Up-and-Out call", "Short Up-and-In call", "Long protective put"},
            "fence_kiko": {"Long underlying", "Long Up-and-Out call", "Short Up-and-In call", "Long upper put", "Short lower put"},
            "digital": {"Long cash digital put"},
        }

        for kind, retail_contract, inputs in cases:
            with self.subTest(kind=kind):
                result = price_structure(kind, {**inputs, "calculate_structure_greeks": True}, retail_contract)
                greeks = result["structure_greeks"]
                structure = greeks["barrier_structure"]
                self.assertEqual(set(structure["total"]), expected)
                self.assertEqual({leg["label"] for leg in structure["legs"]}, expected_legs[kind])
                self.assertNotIn("Full structure", expected_legs[kind])
                self.assertTrue(all(math.isfinite(value) for value in structure["total"].values()))
                for greek, total in structure["total"].items():
                    self.assertAlmostEqual(total, sum(leg["contribution"][greek] for leg in structure["legs"]))

    def test_vanilla_strategy_family_prices_decomposes_and_reconciles_greeks(self):
        c = contract(paths=256)
        cases = {
            "call_spread": ({"lower_call_strike": 100, "upper_call_strike": 115}, {"Long call", "Short call"}),
            "risk_reversal": ({"put_strike": 90, "call_strike": 110}, {"Long call", "Short put"}),
            "seagull": ({"put_strike": 85, "lower_call_strike": 105, "upper_call_strike": 120}, {"Long call", "Short upper call", "Short put"}),
            "straddle": ({"common_strike": 100}, {"Long call", "Long put"}),
            "strangle": ({"put_strike": 90, "call_strike": 110}, {"Long call", "Long put"}),
            "reverse_condor": ({"outer_put_strike": 80, "inner_put_strike": 90, "inner_call_strike": 110, "outer_call_strike": 120}, {"Long outer put", "Short inner put", "Short inner call", "Long outer call"}),
        }
        for kind, (inputs, labels) in cases.items():
            with self.subTest(kind=kind):
                result = price_structure(kind, {**inputs, "option_quantity": 2, "contract_multiplier": 10, "calculate_structure_greeks": True}, c)
                scenarios = maturity_scenarios(kind, {**inputs, "scenario_points": 5}, c, result)
                legs = result["structure_greeks"]["barrier_structure"]["legs"]
                self.assertEqual({leg["label"] for leg in legs}, labels)
                self.assertEqual(scenarios["chart_unit"], "BRL")
                self.assertEqual(len(scenarios["states"]["maturity_payoff"]), 5)
                for greek, total in result["structure_greeks"]["barrier_structure"]["total"].items():
                    self.assertAlmostEqual(total, sum(leg["contribution"][greek] for leg in legs))

    def test_vanilla_strategy_strike_order_is_validated(self):
        with self.assertRaises(InputError) as error:
            price_structure("reverse_condor", {"outer_put_strike": 90, "inner_put_strike": 80, "inner_call_strike": 110, "outer_call_strike": 120}, contract())
        self.assertIn("outer_call_strike", error.exception.errors)

    def test_double_up_families_have_two_limiter_calls_and_reconciled_greeks(self):
        c = contract(paths=256)
        cases = {
            "double_up": {"lower_call_strike": 100, "upper_call_strike": 125},
            "double_up_hedge": {"protective_put_strike": 85, "lower_call_strike": 100, "upper_call_strike": 125},
        }
        for kind, inputs in cases.items():
            with self.subTest(kind=kind):
                result = price_structure(kind, {**inputs, "option_quantity": 10, "calculate_structure_greeks": True}, c)
                scenarios = maturity_scenarios(kind, {**inputs, "scenario_min": 80, "scenario_max": 130, "scenario_points": 3}, c, result)
                self.assertEqual(result["leg_quantities"]["short_call_units"], 20)
                self.assertEqual(result["leg_quantities"]["underlying_shares"], 10)
                self.assertIn("underlying", scenarios["states"]["maturity_payoff"][0]["leg_payoffs"])
                for greek, total in result["structure_greeks"]["barrier_structure"]["total"].items():
                    self.assertAlmostEqual(total, sum(leg["contribution"][greek] for leg in result["structure_greeks"]["barrier_structure"]["legs"]))

    def test_seagull_ki_exposes_dormant_and_activated_short_put(self):
        c = contract(paths=512)
        data = {"down_in_barrier": 75, "put_strike": 85, "lower_call_strike": 105, "upper_call_strike": 120, "option_quantity": 10, "scenario_min": 70, "scenario_max": 110, "scenario_points": 3, "calculate_structure_greeks": True}
        result = price_structure("seagull_ki", data, c)
        scenarios = maturity_scenarios("seagull_ki", data, c, result)
        dormant = scenarios["states"]["lower_barrier_not_triggered"][0]
        activated = scenarios["states"]["lower_barrier_triggered"][0]
        self.assertEqual(dormant["leg_payoffs"]["short_down_in_put"], 0)
        self.assertEqual(activated["leg_payoffs"]["short_down_in_put"], -150)
        self.assertEqual({leg["label"] for leg in result["structure_greeks"]["barrier_structure"]["legs"]}, {"Long call", "Short upper call", "Short Down-and-In put"})

    def test_generic_greeks_hold_allocation_sized_quantity_fixed(self):
        c = contract(behavior="out", barrier=130, paths=512)
        data = {
            "portfolio_value": 100_000,
            "position_allocation_pct": 10,
            "short_vanilla_call_strike": 115,
            "calculate_structure_greeks": True,
        }
        result = price_structure("double_up_ko", data, c)

        self.assertEqual(result["base_share_quantity"], 100)
        self.assertGreater(result["structure_greeks"]["barrier_structure"]["total"]["delta"], 0)

    def test_box_ko_has_fixed_survivor_value_and_stock_only_triggered_value(self):
        c = contract(option_type="put", direction="down", behavior="out", strike=90, barrier=70, paths=5_000)
        result = price_structure("box_ko", {"share_quantity": 10}, c)
        scenarios = maturity_scenarios("box_ko", {"share_quantity": 10, "scenario_min": 80, "scenario_max": 100, "scenario_points": 3}, c, result)

        self.assertAlmostEqual(result["net_option_cost"], result["long_down_out_put_premium"] - result["short_down_out_call_premium"])
        self.assertEqual(scenarios["states"]["lower_barrier_not_triggered"][0]["total_payoff"], 900)
        self.assertEqual(scenarios["states"]["lower_barrier_triggered"][0]["total_payoff"], 800)
        self.assertEqual(scenarios["chart_unit"], "basis_points_of_portfolio")

    def test_box_ko_rejects_non_unit_option_ratio(self):
        c = contract(option_type="put", direction="down", behavior="out", strike=90, barrier=70, paths=5_000)
        with self.assertRaises(InputError) as error:
            price_structure("box_ko", {"share_quantity": 10, "option_quantity_ratio": 1.5}, c)
        self.assertIn("option_quantity_ratio", error.exception.errors)

    def test_box_bullet_uses_terminal_digital_condition(self):
        c = contract(paths=5_000)
        data = {"share_quantity": 10, "bullet_level": 80, "digital_payout": 5, "scenario_min": 70, "scenario_max": 90, "scenario_points": 3}
        result = price_structure("box_bullet", data, c)
        rows = maturity_scenarios("box_bullet", data, c, result)["states"]["maturity_observation"]

        self.assertEqual(rows[0]["total_payoff"], 700)
        self.assertEqual(rows[-1]["total_payoff"], 850)
        self.assertEqual(result["contract_snapshot"]["monitoring"], "maturity_only")

    def test_bullet_keeps_prepaid_forward_after_lower_knockout(self):
        c = contract(option_type="put", direction="down", behavior="out", strike=90, barrier=70, paths=5_000)
        data = {"share_quantity": 10, "forward_strike": 95, "coupon_payout": 4, "scenario_min": 80, "scenario_max": 100, "scenario_points": 3}
        result = price_structure("bullet", data, c)
        scenarios = maturity_scenarios("bullet", data, c, result)

        self.assertEqual(scenarios["states"]["lower_barrier_not_triggered"][0]["total_payoff"], -110)
        self.assertEqual(scenarios["states"]["lower_barrier_triggered"][0]["total_payoff"], -150)
        self.assertIn("prepaid forward remains active", result["sign_convention"])

    def test_bullet_plus_exposes_all_lower_and_upper_path_states(self):
        c = contract(option_type="put", direction="down", behavior="out", strike=90, barrier=70, paths=5_000)
        data = {"share_quantity": 10, "coupon_payout": 4, "up_out_call_strike": 110, "up_out_barrier": 130}
        result = price_structure("bullet_plus", data, c)
        scenarios = maturity_scenarios("bullet_plus", data, c, result)

        self.assertEqual(len(scenarios["states"]), 4)
        self.assertIn("upper_barrier", result["contract_snapshot"])
        self.assertEqual(result["premium_legs"][-1]["label"], "Long Up-and-Out call")

    def test_golden_bullet_requires_protective_put_above_lower_barrier(self):
        c = contract(option_type="put", direction="down", behavior="out", strike=90, barrier=70)
        with self.assertRaises(InputError) as error:
            price_structure("golden_bullet", {"share_quantity": 10, "coupon_payout": 4, "protective_put_strike": 65}, c)
        self.assertIn("protective_put_strike", error.exception.errors)

    def test_golden_bullet_removes_extra_put_after_lower_knockout(self):
        c = contract(option_type="put", direction="down", behavior="out", strike=90, barrier=70, paths=5_000)
        data = {"share_quantity": 10, "coupon_payout": 4, "protective_put_strike": 85, "scenario_min": 80, "scenario_max": 100, "scenario_points": 3}
        result = price_structure("golden_bullet", data, c)
        scenarios = maturity_scenarios("golden_bullet", data, c, result)
        self.assertEqual(scenarios["states"]["lower_barrier_not_triggered"][0]["leg_payoffs"]["long_down_out_put"], 50)
        self.assertEqual(scenarios["states"]["lower_barrier_triggered"][0]["leg_payoffs"]["long_down_out_put"], 0)

    def test_kiko_uses_common_triggered_state(self):
        c = contract(option_type="call", direction="up", behavior="out", strike=105, barrier=130, paths=5_000)
        data = {"share_quantity": 10, "short_up_in_call_strike": 115, "scenario_min": 110, "scenario_max": 120, "scenario_points": 2}
        result = price_structure("call_kiko", data, c)
        scenarios = maturity_scenarios("call_kiko", data, c, result)

        triggered = scenarios["states"]["upper_barrier_triggered"][-1]
        self.assertEqual(triggered["leg_payoffs"]["long_up_out_call"], 0)
        self.assertEqual(triggered["leg_payoffs"]["short_up_in_call"], -50)
        self.assertEqual(result["formula"], "S + C_UO(K1, H) - C_UI(K2, H), with one shared upper barrier event.")

    def test_collar_and_fence_kiko_include_their_protection_legs(self):
        c = contract(option_type="call", direction="up", behavior="out", strike=105, barrier=130, paths=5_000)
        collar = price_structure("collar_kiko", {"share_quantity": 10, "short_up_in_call_strike": 115, "protective_put_strike": 90}, c)
        fence = price_structure("fence_kiko", {"share_quantity": 10, "short_up_in_call_strike": 115, "upper_put_strike": 90, "lower_put_strike": 75}, c)
        self.assertIn("long_protective_put_premium", collar)
        self.assertAlmostEqual(fence["net_option_cost"], fence["long_up_out_call_premium"] - fence["short_up_in_call_premium"] + fence["long_upper_put_premium"] - fence["short_lower_put_premium"])

    def test_digital_fixed_payoff_and_brl_scenarios(self):
        c = contract(paths=5_000)
        data = {"digital_option_type": "put", "digital_payout": 25, "option_quantity": 2, "contract_multiplier": 10, "scenario_min": 90, "scenario_max": 110, "scenario_points": 3}
        result = price_structure("digital", data, c)
        scenarios = maturity_scenarios("digital", data, c, result)

        self.assertEqual(scenarios["states"]["maturity_observation"][0]["total_payoff"], 500)
        self.assertEqual(scenarios["states"]["maturity_observation"][-1]["total_payoff"], 0)
        self.assertEqual(scenarios["chart_unit"], "BRL")
