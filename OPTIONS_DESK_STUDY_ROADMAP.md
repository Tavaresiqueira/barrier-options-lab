# Options Desk Study Roadmap

This roadmap complements the instrument tasks created in the ClickUp list **Sprint Brad Transition**.

## Repeatable study method

For every structure:

1. Reconstruct the signed contractual legs.
2. Draw payoff by terminal-price region and valid barrier path state.
3. Price every leg and reconcile the package premium.
4. Explain Delta, Gamma, Vega, Theta and Rho per leg and in total.
5. Identify the financing source and zero-cost trade-offs.
6. State ideal, adverse and worst scenarios.
7. Compare it with the closest vanilla or barrier alternative.
8. Deliver a 30-second client explanation and suitability warning.
9. Rebuild and stress the example in the options lab.

## Analysis labs

- Payoff and static replication
- Pricing and premium financing
- Greeks and dynamic hedging
- Volatility surface, skew and term structure
- Barrier monitoring and path dependence
- Zero-cost construction and optimization
- Stress testing, suitability and worst-case loss
- Execution, marking and early unwind

## Paper reading sequence

1. Black & Scholes (1973), *The Pricing of Options and Corporate Liabilities* — replication and risk-neutral valuation: https://doi.org/10.1086/260062
2. Breeden & Litzenberger (1978), *Prices of State-Contingent Claims Implicit in Option Prices* — extracting distributions from option prices: https://doi.org/10.1086/296025
3. Leland (1985), *Option Pricing and Replication with Transactions Costs* — operational limits of continuous hedging: https://doi.org/10.1111/j.1540-6261.1985.tb02383.x
4. Heston (1993), *A Closed-Form Solution for Options with Stochastic Volatility* — stochastic variance, skew and spot/volatility correlation: https://doi.org/10.1093/rfs/6.2.327
5. Dupire (1994), *Pricing with a Smile* — local volatility and surface-consistent exotic pricing.
6. Broadie, Glasserman & Kou (1997), *A Continuity Correction for Discrete Barrier Options* — monitoring-frequency effects: https://www.columbia.edu/~sk75/mfBGK.pdf
7. Carr, Ellis & Gupta (1998), *Static Hedging of Exotic Options* — vanilla replication of barrier and exotic exposures: https://engineering.nyu.edu/sites/default/files/2019-03/Carr-static-hedging-of-exotic-options.pdf
8. Glasserman & Staum (2001), *Conditioning on One-Step Survival for Barrier Option Simulations* — efficient barrier Monte Carlo.

## Deep-research briefs

- Collect real term sheets for Double Up KO, Double Up Hedge, Jump and Seagull KI; document exact legs, ratios, monitoring and post-trigger states.
- Map Brazilian equity-option volatility surfaces, including downside skew, term structure, dividends, borrow and corporate actions.
- Document Brazilian retail barrier conventions: observation calendar, touch source, intraday versus close, gaps and disputed fixes.
- Reconstruct dealer zero-cost optimization under bid/ask, volatility smile, reserves and suitability constraints.
- Build an early-unwind bridge from clean model value to executable client price.
- Study hedging discontinuous barrier Greeks near touch and the consequences for turnover and desk limits.

## Institutional flow, structuring demand and product adoption

### Questions to answer

- Which structures, tenors and underlyings are gaining institutional adoption, segmented by hedge funds, asset managers, pensions, private banks and structured-product desks?
- Which flows are strategic hedges, tactical overlays, yield enhancement, convexity purchases, dispersion/correlation trades or dealer-intermediated client risk?
- How do realized volatility, skew, term structure, spot/vol correlation, rates, dividends and borrow conditions rotate demand across structures?
- How do dealer inventory, gamma/vega limits, barrier proximity and concentrated expiries affect pricing, axes and the structures offered to clients?
- Which trades are held to expiry, rolled, monetized or unwound early, and how does execution quality change the realized economics?
- Where does flow concentrate by delta, maturity, strike, barrier distance and underlying liquidity?
- Which market regimes create demand for protection, overwriting, financed upside, conditional coupons and long-volatility exposure?
- How much of observed surface movement is information, mechanical dealer hedging, supply/demand pressure or event positioning?

### Institutional evidence pack

1. Track B3 monthly/weekly option ADTV, open interest, investor-category participation, concentration by underlying, maturity, delta bucket and exercise style.
2. Request desk RFQ data by structure: inquiry, quote, conversion, ticket size, counterparty segment, underlying, tenor, barrier distance, vol level, skew, axes and unwind.
3. Reconstruct dealer positioning proxies from open-interest changes, volume, surface moves and spot response around concentrated strikes and expiries.
4. Build a flow taxonomy: hedge initiation, monetization, roll, overwrite, financed directional trade, convexity purchase, relative-value trade and unwind.
5. Compare quoted clean value, executable price, reserve, hedge cost and realized unwind economics.
6. Study how institutional flows migrate between listed options, FLEX/OTC structures, futures, variance exposure and cash-equity hedges.

### Papers and market studies

- Poteshman (2004), *Investor Behavior in the Option Market*: https://doi.org/10.3386/w10264
- B3, equity-options market statistics and investor participation: https://www.b3.com.br/pt_br/noticias/mercado-de-opcoes.htm
- Cboe, quarterly *State of the Options Industry* reports for product, tenor, FLEX and index/ETF flow trends: https://www.cboe.com/insights/
- Gârleanu, Pedersen & Poteshman (2009), *Demand-Based Option Pricing* — option demand, intermediary constraints and implied-volatility effects.
- Bollen & Whaley (2004), *Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?* — demand pressure and the volatility surface.
- Ni, Pearson & Poteshman (2005), *Stock Price Clustering on Option Expiration Dates* — expiration positioning and pinning.
- Hu (2014), *Does Option Trading Convey Stock Price Information?* — information content of option flow.
- Muravyev, Pearson & Broussard (2013), *Is There Price Discovery in Equity Options?* — price discovery between options and stock.
- Easley, O'Hara & Srinivas (1998), *Option Volume and Stock Prices* — informed trading and cross-market flow.

### Deliverables

- Monthly institutional flow and adoption dashboard.
- Structure-by-counterparty-segment heatmap.
- Market-regime versus product-demand timeline.
- Surface-impact attribution by flow, dealer inventory and event regime.
- RFQ conversion, axes and unwind-cost dashboard.
- Five evidence-backed structuring opportunities by institutional segment and regime.
- Deep-research memo separating observed flow, inferred positioning and commercial hypothesis.

## Application roadmap

- Add conventional Double Up and Double Up Hedge.
- Add Seagull KI with explicit lower-barrier path states.
- Add a term-sheet-driven custom leg builder for Jump and dealer variants.
- Add implied-volatility surface and skew inputs by strike and expiry.
- Add hedge turnover, transaction costs and barrier-event jumps.
- Add bid/mid/ask, model-reserve and early-unwind analysis.
- Add a client-suitability and worst-loss checklist.
- Add spaced-repetition flashcards and timed 30-second pitch drills.
