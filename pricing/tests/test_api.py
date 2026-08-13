from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from pricing.models import Calculation
from pricing.services.market_data import MarketDataError


def payload(**changes):
    data = {
        "option_type": "call", "direction": "up", "behavior": "in",
        "spot": 100, "strike": 105, "barrier": 120,
        "valuation_date": "2026-01-02", "expiration_date": "2027-01-02",
        "rate": .1, "dividend_yield": .03, "volatility": .25,
        "quantity": 1, "multiplier": 1, "rebate": 0, "rebate_timing": "expiry",
        "monitoring": "continuous", "barrier_status": "not_triggered",
        "paths": 5000, "seed": 11,
    }
    data.update(changes)
    return data


class ApiTests(TestCase):
    def test_package_snapshot_reprices_without_persisting_calculation(self):
        body = {
            "kind": "call_spread", "lower_call_strike": 100, "upper_call_strike": 115,
            "option_quantity": 1, "contract_multiplier": 1, "calculate_structure_greeks": True,
            "barrier_contract": payload(spot=105, strike=100, barrier=200, barrier_status="not_applicable", monitoring="maturity_only"),
        }
        before = Calculation.objects.count()
        response = self.client.post(reverse("pricing:package_snapshot"), body, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("structure_greeks", response.json()["data"])
        self.assertEqual(Calculation.objects.count(), before)

    def test_barrier_success_and_persistence(self):
        response = self.client.post(reverse("pricing:price_barrier"), payload(), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Calculation.objects.count(), 1)
        row = Calculation.objects.get()
        self.assertEqual(row.request_data["seed"], 11)
        self.assertEqual(row.result_data["model_price"], response.json()["data"]["model_price"])

    def test_same_request_reproduces_price(self):
        first = self.client.post(reverse("pricing:price_barrier"), payload(), content_type="application/json").json()["data"]
        second = self.client.post(reverse("pricing:price_barrier"), payload(), content_type="application/json").json()["data"]
        self.assertEqual(first["model_price"], second["model_price"])

    def test_single_barrier_response_includes_learning_payoff_states(self):
        response = self.client.post(reverse("pricing:price_barrier"), payload(calculate_greeks=True), content_type="application/json")
        result = response.json()["data"]
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(result["scenario_analysis"]["states"]), {"pre_barrier", "post_trigger"})
        self.assertEqual(result["scenario_analysis"]["curve_type"], "valuation_date_mark_to_market")
        self.assertGreater(result["scenario_analysis"]["days_to_expiry"], 0)
        self.assertIn("vanilla_unit_value", result["scenario_analysis"]["states"]["pre_barrier"][0])
        self.assertIn("local_delta", result["scenario_analysis"]["states"]["pre_barrier"][0])
        self.assertIn("delta_sign_flips", result["scenario_analysis"])
        self.assertEqual(set(result["scenario_analysis"]["expiry_states"]), {"barrier_not_triggered", "barrier_triggered"})
        expiry_row = result["scenario_analysis"]["expiry_states"]["barrier_triggered"][0]
        self.assertIn("exotic_payoff_per_unit", expiry_row)
        self.assertIn("vanilla_payoff_per_unit", expiry_row)
        self.assertEqual(result["contract_snapshot"]["spot"], 100)
        self.assertIn("greeks", result)
        self.assertIn("vanilla_greeks", result)

    def test_barrier_snapshot_reprices_without_persistence(self):
        before = Calculation.objects.count()
        response = self.client.post(reverse("pricing:barrier_snapshot"), payload(spot=105, calculate_greeks=True), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("greeks", response.json()["data"])
        self.assertIn("vanilla_greeks", response.json()["data"])
        self.assertEqual(Calculation.objects.count(), before)

    def test_up_and_out_curve_reports_delta_sign_inversion(self):
        response = self.client.post(reverse("pricing:price_barrier"), payload(
            behavior="out", spot=41.13, strike=45, barrier=51,
            valuation_date="2026-08-12", expiration_date="2027-08-02",
            rate=.12, dividend_yield=.04, monitoring="daily_close", paths=50000, seed=42,
        ), content_type="application/json")
        flips = response.json()["data"]["scenario_analysis"]["delta_sign_flips"]
        self.assertTrue(flips)
        self.assertEqual(flips[0]["direction"], "positive_to_negative")
        self.assertGreater(flips[0]["delta_before"], 0)
        self.assertLess(flips[0]["delta_after"], 0)

    def test_field_validation_error(self):
        response = self.client.post(reverse("pricing:price_barrier"), payload(volatility=0), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("volatility", response.json()["error"]["fields"])

    def test_invalid_barrier_configuration(self):
        response = self.client.post(reverse("pricing:price_barrier"), payload(barrier=90), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("barrier", response.json()["error"]["fields"])

    def test_package_and_scenario_endpoints(self):
        body = {
            "kind": "collar", "protective_put_strike": 90,
            "underlying_quantity_ratio": 1, "protective_put_quantity_ratio": 1, "call_quantity_ratio": 1,
            "barrier_contract": payload(),
        }
        package = self.client.post(reverse("pricing:price_package"), body, content_type="application/json")
        self.assertEqual(package.status_code, 201)
        self.assertEqual(
            set(package.json()["data"]["scenario_analysis"]["states"]),
            {"barrier_never_triggered", "barrier_triggered"},
        )
        scenarios = self.client.post(reverse("pricing:scenarios"), body, content_type="application/json")
        self.assertEqual(scenarios.status_code, 201)
        scenario_data = scenarios.json()["data"]
        states = scenario_data["states"]
        self.assertEqual(set(states), {"barrier_never_triggered", "barrier_triggered"})
        triggered = scenario_data["outcome_summary"]["barrier_triggered"]
        self.assertEqual(triggered["maximum_payoff"], body["barrier_contract"]["strike"])
        self.assertIn("downside_pnl_at_zero", triggered)

    def test_nitro_package_and_scenario_endpoints_persist_knockout_states(self):
        body = {
            "kind": "nitro",
            "option_quantity": 3,
            "contract_multiplier": 100,
            "barrier_contract": payload(behavior="out", barrier=130, rebate=1),
        }
        package = self.client.post(reverse("pricing:price_package"), body, content_type="application/json")
        self.assertEqual(package.status_code, 201, package.content)
        data = package.json()["data"]
        self.assertEqual(data["kind"], "nitro")
        self.assertEqual(data["leg_quantities"]["long_up_out_call_units"], 300)
        self.assertEqual(data["total_initial_cash_requirement"], data["net_option_cost"])
        self.assertEqual(set(data["scenario_analysis"]["states"]), {"knockout_not_triggered", "knockout_triggered"})
        self.assertEqual(Calculation.objects.get().kind, "nitro")

        scenarios = self.client.post(reverse("pricing:scenarios"), body, content_type="application/json")
        self.assertEqual(scenarios.status_code, 201, scenarios.content)
        knocked_out = scenarios.json()["data"]["states"]["knockout_triggered"][0]
        self.assertEqual(knocked_out["leg_payoffs"]["knockout_rebate"], 300)
        self.assertNotIn("total_pnl_bps", knocked_out)

    def test_double_up_ko_package_and_scenario_endpoints(self):
        body = {
            "kind": "double_up_ko",
            "share_quantity": 100,
            "underlying_quantity_ratio": 1,
            "long_up_out_call_quantity_ratio": 1.5,
            "short_vanilla_call_quantity_ratio": 1,
            "short_vanilla_call_strike": 115,
            "barrier_contract": payload(behavior="out", barrier=130),
        }
        package = self.client.post(reverse("pricing:price_package"), body, content_type="application/json")
        self.assertEqual(package.status_code, 201, package.content)
        data = package.json()["data"]
        self.assertEqual(data["kind"], "double_up_ko")
        self.assertEqual(data["leg_quantities"]["long_up_out_call_units"], 150)
        self.assertEqual(data["leg_quantities"]["short_vanilla_call_units"], 100)
        self.assertAlmostEqual(
            data["net_option_cost"],
            data["long_up_out_call_premium"] - data["short_vanilla_call_premium"],
        )
        self.assertEqual(set(data["scenario_analysis"]["states"]), {"knockout_not_triggered", "knockout_triggered"})
        self.assertEqual(Calculation.objects.get().kind, "double_up_ko")

        scenarios = self.client.post(reverse("pricing:scenarios"), body, content_type="application/json")
        self.assertEqual(scenarios.status_code, 201, scenarios.content)
        knocked_out = scenarios.json()["data"]["states"]["knockout_triggered"][0]
        self.assertEqual(knocked_out["leg_payoffs"]["long_up_out_call"], 0)
        self.assertIn("total_pnl_bps", knocked_out)

    def test_knockout_packages_reject_invalid_barrier_leg(self):
        nitro = self.client.post(
            reverse("pricing:price_package"),
            {"kind": "nitro", "barrier_contract": payload()},
            content_type="application/json",
        )
        self.assertEqual(nitro.status_code, 400)
        self.assertIn("barrier_leg", nitro.json()["error"]["fields"])

        double_up = self.client.post(
            reverse("pricing:price_package"),
            {
                "kind": "double_up_ko", "share_quantity": 1,
                "short_vanilla_call_strike": 104,
                "barrier_contract": payload(behavior="out", barrier=130),
            },
            content_type="application/json",
        )
        self.assertEqual(double_up.status_code, 400)
        self.assertIn("short_vanilla_call_strike", double_up.json()["error"]["fields"])

    def test_package_returns_structure_greeks_when_requested(self):
        body = {
            "kind": "collar", "protective_put_strike": 90,
            "underlying_quantity_ratio": 1, "protective_put_quantity_ratio": 1, "call_quantity_ratio": 1,
            "calculate_structure_greeks": True, "barrier_contract": payload(paths=5000),
        }
        response = self.client.post(reverse("pricing:price_package"), body, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]["structure_greeks"]
        self.assertEqual(set(data), {"barrier_structure", "vanilla_structure", "conventions", "bumps"})
        self.assertEqual(data["barrier_structure"]["legs"][-1]["label"], "Short Up-and-In call")
        self.assertEqual(data["vanilla_structure"]["legs"][-1]["label"], "Short vanilla call")

    def test_fence_invalid_strikes(self):
        body = {
            "kind": "fence", "upper_put_strike": 80, "lower_put_strike": 90,
            "underlying_quantity_ratio": 1, "upper_put_quantity_ratio": 1, "lower_put_quantity_ratio": 1, "call_quantity_ratio": 1,
            "barrier_contract": payload(),
        }
        response = self.client.post(reverse("pricing:price_package"), body, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("lower_put_strike", response.json()["error"]["fields"])

    def test_zero_cost_solver_converges(self):
        body = {
            "kind": "collar", "protective_put_strike": 90,
            "underlying_quantity_ratio": 1, "protective_put_quantity_ratio": 1, "call_quantity_ratio": 1,
            "solve_for": "call_strike", "search_lower": 100, "search_upper": 180,
            "zero_cost_tolerance": .02, "barrier_contract": payload(paths=5000),
        }
        response = self.client.post(reverse("pricing:solve"), body, content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["data"]["converged"])

    def test_history_contract(self):
        self.client.post(reverse("pricing:price_barrier"), payload(), content_type="application/json")
        response = self.client.get(reverse("pricing:history"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)

    @patch("pricing.views.option_chain")
    def test_chain_success(self, mocked):
        mocked.return_value = {"identifier": "PETR4 BZ Equity", "data": []}
        response = self.client.get(reverse("pricing:chain"), {"underlying": "PETR4 BZ Equity"})
        self.assertEqual(response.status_code, 200)

    @patch("pricing.views.option_chain", side_effect=MarketDataError("offline"))
    def test_chain_error_is_safe(self, mocked):
        response = self.client.get(reverse("pricing:chain"), {"underlying": "PETR4 BZ Equity"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("Traceback", response.content.decode())

    def test_di_curve_endpoint_explains_manual_rate(self):
        response = self.client.get(reverse("pricing:rates"), {"target_date": "2027-01-02"})
        self.assertEqual(response.status_code, 502)
        self.assertIn("manually", response.json()["error"]["message"])

    def test_learning_path_explorer_replays_saved_calculation(self):
        priced = self.client.post(reverse("pricing:price_barrier"), payload(), content_type="application/json").json()["data"]
        response = self.client.get(reverse("pricing:learning_paths", args=[priced["calculation_id"]]), {"path_count": 2, "path_index": 0})
        self.assertEqual(response.status_code, 200, response.content)
        study = response.json()["data"]["result"]
        self.assertEqual(study["provenance"]["seed"], 11)
        self.assertEqual(len(study["available_paths"]), 2)
        self.assertEqual(study["selected_path"]["points"][-1]["date"], "2027-01-02")

    def test_learning_quote_waterfall_and_volatility_study(self):
        priced = self.client.post(reverse("pricing:price_barrier"), payload(), content_type="application/json").json()["data"]
        quote = self.client.get(reverse("pricing:learning_quote", args=[priced["calculation_id"]]), {
            "model_reserve_brl": 2, "hedging_liquidity_reserve_brl": 3, "dealer_margin_brl": 4,
        })
        self.assertEqual(quote.status_code, 200, quote.content)
        quote_result = quote.json()["data"]["result"]
        self.assertAlmostEqual(quote_result["client_quote"], quote_result["clean_value"] + 9)
        volatility = self.client.get(reverse("pricing:learning_volatility", args=[priced["calculation_id"]]), {"historical_volatility": .15, "implied_volatility": .25, "dealer_volatility": .3})
        self.assertEqual(volatility.status_code, 200, volatility.content)
        rows = volatility.json()["data"]["result"]["rows"]
        self.assertIsNone(rows[0]["model_value"])
        self.assertNotEqual(rows[1]["model_value"], rows[2]["model_value"])

    def test_learning_hedge_and_attribution_are_read_only(self):
        priced = self.client.post(reverse("pricing:price_barrier"), payload(), content_type="application/json").json()["data"]
        hedge = self.client.get(reverse("pricing:learning_hedge", args=[priced["calculation_id"]]), {"rebalance_count": 2})
        self.assertEqual(hedge.status_code, 200, hedge.content)
        self.assertEqual(len(hedge.json()["data"]["result"]["timeline"]), 2)
        attribution = self.client.get(reverse("pricing:learning_attribution", args=[priced["calculation_id"]]), {"spot_change_pct": 3, "volatility_change": .01, "rate_change": .001, "days": 1})
        self.assertEqual(attribution.status_code, 200, attribution.content)
        result = attribution.json()["data"]["result"]
        self.assertEqual(set(result["greeks"]), {"delta", "gamma", "vega_per_1pct", "theta_per_calendar_day", "rho_per_1bp"})
        self.assertAlmostEqual(result["residual"], 0.0, places=8)

    def test_retail_digital_package_persists_fixed_payoff_scenario(self):
        body = {
            "kind": "digital", "digital_option_type": "call", "digital_payout": 20,
            "option_quantity": 2, "contract_multiplier": 10,
            "scenario_min": 90, "scenario_max": 110, "scenario_points": 3,
            "barrier_contract": payload(),
        }
        response = self.client.post(reverse("pricing:price_package"), body, content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        result = response.json()["data"]
        self.assertEqual(result["kind"], "digital")
        self.assertEqual(result["scenario_analysis"]["chart_unit"], "BRL")
        self.assertEqual(result["scenario_analysis"]["states"]["maturity_observation"][-1]["total_payoff"], 400)
        self.assertEqual(Calculation.objects.get().kind, "digital")
