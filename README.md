# Barrier Options Lab

Independent, local Django application for studying BRL OTC equity barrier options, Collar Up-and-In and Fence Up-and-In packages. It does not import or modify ATON or the existing Options Structuring application.

## Run

1. Copy `.env.example` values into `.env`.
2. Start the independent container:

   ```powershell
   docker compose up --build
   ```

3. Open <http://localhost:8010>.

Yahoo Finance is used only to update the latest underlying price. All pricing assumptions remain editable and explicit.

Run all tests:

```powershell
docker compose run --rm web python manage.py test
```

## Deploy on Render

The repository includes a `render.yaml` Blueprint and a production Gunicorn/WhiteNoise configuration. Connect the repository as a new Blueprint in Render; the service builds from `Dockerfile`, generates its Django secret, runs migrations, and deploys at an `onrender.com` URL.

The default deployment uses SQLite inside the web-service container. Pricing and analytics are fully functional, but saved calculation history resets when Render replaces the container. Attach PostgreSQL before relying on persistent shared history.

## Architecture

- `pricing/services/vanilla.py`: European Black–Scholes.
- `pricing/services/monte_carlo.py`: pluggable GBM Monte Carlo engine, Brownian bridge, discrete monitoring, statistics and Greeks.
- `pricing/services/structures.py`: signed Collar/Fence decomposition and two-state maturity scenarios.
- `pricing/services/solver.py`: bracketed Brent zero-cost solver with common random numbers.
- `pricing/services/market_data.py`: Yahoo Finance adapter for the latest BRL underlying price.
- `pricing/views.py`: JSON boundary, persistence and consistent errors.
- `templates/pricing/index.html` and `static/pricing/`: browser workspace; no authoritative pricing in JavaScript.

## Model and contract conventions

Under the risk-neutral measure, the engine simulates

`dS/S = (r-q)dt + sigma dW`

with constant annualized continuously compounded rate, continuous dividend yield and volatility. European terminal intrinsic value is activated or deactivated by the barrier event. Continuous monitoring uses the conditional crossing probability between adjacent log-price endpoints. Discrete daily, weekly and monthly dates follow B3 sessions; weekly/monthly select the last B3 session of the period.

Barrier status is explicit. A triggered knock-in becomes vanilla. A triggered knock-out is its contractual rebate, or zero. Current spot is never used as a substitute for historical path status.

Long premiums are costs and short premiums are receipts:

- Collar: `net cost = P(Kp) - C_UI(Kc,H)`
- Fence: `net cost = P(Kpu) - P(Kpl) - C_UI(Kc,H)`

Zero cost means the absolute net option premium is inside the selected tolerance. It does not mean zero risk.

## Yahoo Finance market snapshot

The app maps B3 identifiers such as `PETR4` and `PETR4 BZ Equity` to Yahoo symbols such as `PETR4.SA`, then requests the latest price from Yahoo's chart endpoint. It deliberately does not load an option chain, volatility, dividend yield, or DI curve. Those assumptions remain user-entered and every pricing request stores the actual values used.

No passwords or access tokens are stored in calculations, logs, browser code, or exported output.

## Greeks

Disabled by default. Common random numbers are used for all bumps:

- delta/gamma: ±1% spot;
- vega: ±1 volatility point, reported per 1 point;
- rho: ±1 bp, reported per 1 bp;
- theta: one calendar day.

## Limitations

Study/prototyping use only. Yahoo prices may be delayed and are not suitable as executable dealer marks. No discrete dividends, corporate-action adjustments, local/stochastic volatility, jumps, early exercise, smile dynamics, credit/funding adjustments, dealer margin, hedging reserve, liquidity reserve, RFQ, trading, or B3 registration. Continuous-barrier rebates paid immediately use simulated interval timing. Validate the manually entered DI rate against desk standards before relying on it for commercial quoting.
