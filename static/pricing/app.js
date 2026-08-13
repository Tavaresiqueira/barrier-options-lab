const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const csrf = () => $('[name=csrfmiddlewaretoken]')?.value || "";
const state = { market: null, packages: {}, barrier: null, charts: {} };
Chart.defaults.font.family = "Poppins, sans-serif";
Chart.defaults.color = "#68736e";

const referenceLinePlugin = {
  id: "referenceLines",
  afterDatasetsDraw(chart, _args, options) {
    const {ctx, chartArea, scales} = chart;
    if (!options?.items || !scales.x) return;
    ctx.save();
    options.items.forEach(item => {
      const x = scales.x.getPixelForValue(item.value);
      if (x < chartArea.left || x > chartArea.right) return;
      ctx.strokeStyle = item.color; ctx.lineWidth = item.width || 1;
      ctx.setLineDash(item.dash || [5, 5]);
      ctx.beginPath(); ctx.moveTo(x, chartArea.top); ctx.lineTo(x, chartArea.bottom); ctx.stroke();
      ctx.setLineDash([]); ctx.fillStyle = item.color; ctx.font = "600 9px Poppins"; ctx.textAlign = "center";
      ctx.fillText(item.label + " " + money(item.value), x, chartArea.top + 10 + (item.offset || 0));
    });
    ctx.restore();
  }
};
Chart.register(referenceLinePlugin);

const payoffPnlPlugin = {
  id: "payoffPnl",
  beforeDatasetsDraw(chart) {
    const {ctx, chartArea, scales} = chart;
    const zeroY = scales.y?.getPixelForValue(0);
    if (!Number.isFinite(zeroY) || zeroY < chartArea.top || zeroY > chartArea.bottom) return;
    ctx.save();
    ctx.fillStyle = "rgba(25, 135, 84, .10)";
    ctx.fillRect(chartArea.left, chartArea.top, chartArea.right - chartArea.left, zeroY - chartArea.top);
    ctx.fillStyle = "rgba(220, 53, 69, .10)";
    ctx.fillRect(chartArea.left, zeroY, chartArea.right - chartArea.left, chartArea.bottom - zeroY);
    ctx.strokeStyle = "rgba(42, 55, 48, .72)";
    ctx.lineWidth = 1.8;
    ctx.beginPath(); ctx.moveTo(chartArea.left, zeroY); ctx.lineTo(chartArea.right, zeroY); ctx.stroke();
    ctx.restore();
  },
  afterDatasetsDraw(chart, _args, options) {
    const dataset = chart.data.datasets[options?.datasetIndex];
    const meta = chart.getDatasetMeta(options?.datasetIndex);
    if (!dataset || !meta?.data?.length) return;
    const checkpoints = Math.min(options.checkpoints || 7, meta.data.length);
    const interval = Math.max(1, Math.round((meta.data.length - 1) / Math.max(checkpoints - 1, 1)));
    const indices = new Set([0, meta.data.length - 1]);
    for (let index = interval; index < meta.data.length - 1; index += interval) indices.add(index);
    const {ctx, chartArea} = chart;
    ctx.save(); ctx.font = "600 9px Poppins"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    [...indices].forEach(index => {
      const point = meta.data[index];
      const value = dataset.data[index].y;
      if (!point || !Number.isFinite(value) || point.x < chartArea.left || point.x > chartArea.right || point.y < chartArea.top || point.y > chartArea.bottom) return;
      const label = options?.unit === "BRL"
        ? `${value >= 0 ? "+" : "−"}R$ ${Math.abs(value).toFixed(0)}`
        : `${value >= 0 ? "+" : ""}${value.toFixed(0)} bps`;
      const width = ctx.measureText(label).width + 8;
      const labelY = Math.max(chartArea.top + 8, Math.min(chartArea.bottom - 8, point.y - 12));
      ctx.fillStyle = "rgba(255,255,255,.88)";
      ctx.fillRect(point.x - width / 2, labelY - 7, width, 14);
      ctx.fillStyle = value >= 0 ? "#126142" : "#a53838";
      ctx.fillText(label, point.x, labelY);
    });
    ctx.restore();
  }
};
Chart.register(payoffPnlPlugin);

const extremaMarkerPlugin = {
  id: "extremaMarkers",
  afterDatasetsDraw(chart) {
    const {ctx, chartArea} = chart;
    chart.data.datasets.forEach((dataset, datasetIndex) => {
      if (!dataset.extremaMarker) return;
      const point = chart.getDatasetMeta(datasetIndex).data[0], value = dataset.data[0];
      if (!point || !value || point.x < chartArea.left || point.x > chartArea.right || point.y < chartArea.top || point.y > chartArea.bottom) return;
      const label = `${dataset.extremaLabel} · R$ ${money(value.y)}`;
      ctx.save(); ctx.font = "600 9px Poppins"; ctx.textBaseline = "middle";
      const width = ctx.measureText(label).width + 12, height = 18;
      const labelX = Math.max(chartArea.left, Math.min(chartArea.right - width, point.x - width / 2));
      const preferredY = dataset.extremaKind === "max" ? point.y - 28 : point.y + 10;
      const labelY = Math.max(chartArea.top + 2, Math.min(chartArea.bottom - height - 2, preferredY));
      ctx.fillStyle = "rgba(255,255,255,.94)"; ctx.strokeStyle = dataset.borderColor; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.roundRect(labelX, labelY, width, height, 5); ctx.fill(); ctx.stroke();
      ctx.fillStyle = dataset.borderColor; ctx.textAlign = "left"; ctx.fillText(label, labelX + 6, labelY + height / 2);
      ctx.restore();
    });
  }
};
Chart.register(extremaMarkerPlugin);

function extremaMarkerDatasets(groups, valueLabel) {
  return groups.flatMap(group => {
    const points = group.points.filter(point => Number.isFinite(point?.x) && Number.isFinite(point?.y));
    if (!points.length) return [];
    const minimum = points.reduce((best, point) => point.y < best.y ? point : best);
    const maximum = points.reduce((best, point) => point.y > best.y ? point : best);
    return [["min", minimum], ["max", maximum]]
      .filter(([kind, point]) => kind === "min" || point.x !== minimum.x || point.y !== minimum.y)
      .map(([kind, point]) => ({
        label: `${group.label} ${kind}`, data: [point], showLine: false, pointRadius: 5.5, pointHoverRadius: 7,
        pointBackgroundColor: "#fff", pointBorderColor: group.color, pointBorderWidth: 3, borderColor: group.color,
        extremaMarker: true, markerGroup: group.key, extremaKind: kind, extremaLabel: `${group.label} ${kind === "max" ? `max ${valueLabel}` : `min ${valueLabel}`}`
      }));
  });
}

function deltaSignFlipDatasets(signFlips) {
  return (signFlips || []).map((flip, index) => {
    const positiveToNegative = flip.direction === "positive_to_negative";
    const direction = positiveToNegative ? "+Δ → −Δ" : "−Δ → +Δ";
    return {
      label: `Delta inversion ${index + 1}`, data: [{x:flip.spot,y:flip.unit_model_value,pnl:null}], showLine:false,
      pointRadius:7, pointHoverRadius:9, pointStyle:"rectRot", pointBackgroundColor:"#fff", pointBorderColor:"#d97706",
      pointBorderWidth:3, borderColor:"#d97706", extremaMarker:true, extremaKind:positiveToNegative ? "max" : "min",
      markerGroup:"exotic", extremaLabel:`${direction} at spot R$ ${money(flip.spot)}`
    };
  });
}

function isoDate(offsetDays) {
  const value = new Date();
  value.setDate(value.getDate() + offsetDays);
  return value.toISOString().slice(0, 10);
}
$$(".valuation-input").forEach(el => el.value = isoDate(0));
$$(".expiry-input").forEach(el => el.value = isoDate(180));

$$(".tabs button").forEach(button => button.addEventListener("click", () => {
  $$(".tabs button").forEach(x => x.classList.toggle("active", x === button));
  $$(".workspace").forEach(x => x.classList.toggle("active", x.id === button.dataset.tab));
  if (button.dataset.tab === "history") loadHistory();
  if (button.dataset.tab === "learning") loadLearningCalculations();
}));

$$("[data-retail-product]").forEach(button => button.addEventListener("click", () => {
  $$("[data-retail-product]").forEach(item => item.classList.toggle("active", item === button));
  $$("[data-retail-panel]").forEach(panel => panel.classList.toggle("active", panel.dataset.retailPanel === button.dataset.retailProduct));
}));

function contractFields(kind) {
  if (["call_spread", "risk_reversal", "seagull", "straddle", "strangle", "reverse_condor", "double_up", "double_up_hedge", "seagull_ki"].includes(kind)) return vanillaStrategyContractFields();
  if (["nitro", "double_up_ko", "collar_kiko", "fence_kiko", "call_kiko"].includes(kind)) return knockOutContractFields(kind);
  if (["box_ko", "bullet", "bullet_plus", "golden_bullet"].includes(kind)) return downOutContractFields(kind);
  if (kind === "box_bullet") return boxBulletContractFields();
  if (kind === "digital") return digitalContractFields();
  const strikeLabel = kind ? "OTM short call strike" : "OTM call strike";
  return `
    <label>Spot<input class="spot-input" name="spot" type="number" step=".01" value="100"></label>
    <label>${strikeLabel}<select class="strike-select" name="strike" data-default-moneyness=".10"></select><small>R$1 increments above spot</small></label>
    <label>Up barrier<select class="barrier-select" name="barrier" data-default-moneyness=".25"></select><small>R$1 increments above call strike</small></label>
    <label>Valuation<input class="valuation-input" name="valuation_date" type="date" value="${isoDate(0)}"></label>
    <label>Expiration<input class="expiry-input" name="expiration_date" type="date" value="${isoDate(180)}"></label>
    <label>DI rate<input class="rate-input" name="rate" type="number" step=".0001" value=".12"></label>
    <label>Dividend yield<input class="dividend-input" name="dividend_yield" type="number" step=".0001" value=".04"></label>
    <label>Volatility<input class="vol-input" name="volatility" type="number" step=".0001" value=".25"></label>
    <label>Monitoring<select name="monitoring"><option value="continuous">Continuous</option><option value="daily_close">Daily close</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="maturity_only">Maturity only</option></select></label>
    <label>Paths<input name="paths" type="number" min="5000" max="500000" value="50000"></label>
    <label>Seed<input name="seed" type="number" value="42"></label>
    <label>Barrier status<select name="barrier_status"><option value="not_triggered">Not triggered</option><option value="triggered">Triggered</option><option value="not_applicable">N/A</option></select></label>`;
}

function structureFields(kind) {
  if (["call_spread", "risk_reversal", "seagull", "straddle", "strangle", "reverse_condor", "double_up", "double_up_hedge", "seagull_ki"].includes(kind)) {
    const strikes = {
      call_spread: [["Lower call K1", "lower_call_strike", 100], ["Upper call K2", "upper_call_strike", 115]],
      risk_reversal: [["Short put Kp", "put_strike", 90], ["Long call Kc", "call_strike", 110]],
      seagull: [["Short put K1", "put_strike", 85], ["Long call K2", "lower_call_strike", 105], ["Short call K3", "upper_call_strike", 120]],
      straddle: [["Common strike K", "common_strike", 100]],
      strangle: [["Put strike Kp", "put_strike", 90], ["Call strike Kc", "call_strike", 110]],
      reverse_condor: [["Outer put K1", "outer_put_strike", 80], ["Inner put K2", "inner_put_strike", 90], ["Inner call K3", "inner_call_strike", 110], ["Outer call K4", "outer_call_strike", 120]],
      double_up: [["Accelerating call K1", "lower_call_strike", 100], ["Limiter call K2", "upper_call_strike", 125]],
      double_up_hedge: [["Protective put Kp", "protective_put_strike", 85], ["Accelerating call K1", "lower_call_strike", 100], ["Limiter call K2", "upper_call_strike", 125]],
      seagull_ki: [["Down-and-In barrier B", "down_in_barrier", 75], ["Short put K1", "put_strike", 85], ["Long call K2", "lower_call_strike", 105], ["Short call K3", "upper_call_strike", 120]],
    }[kind];
    return `<label>Option quantity<input name="option_quantity" type="number" min="1" step="1" value="1"></label>
      <label>Contract multiplier<input name="contract_multiplier" type="number" min="1" step="1" value="1"></label>
      ${strikes.map(([label, name, value]) => `<label>${label}<input name="${name}" type="number" min=".01" step=".01" value="${value}"></label>`).join("")}`;
  }
  if (kind === "nitro") return `
    <label>Option quantity<input name="option_quantity" type="number" min="1" step="1" value="1"><small>Number of Up-and-Out calls purchased</small></label>
    <label>Contract multiplier<input name="contract_multiplier" type="number" min="1" step="1" value="1"><small>Units represented by each option</small></label>`;
  if (kind === "double_up_ko") return `
    <label>Portfolio value (BRL)<input name="portfolio_value" type="number" min="100000" step="100000" value="10000000"><small>Base used for portfolio-bps payoff</small></label>
    <label>Position allocation (%)<input name="position_allocation_pct" type="number" min="0.1" max="100" step="0.1" value="10"><small>Underlying shares are derived from this allocation</small></label>
    <label>Underlying ratio<input name="underlying_quantity_ratio" type="number" min="0.1" step=".1" value="1"></label>
    <label>Long C<sub>UO</sub> ratio<input name="long_up_out_call_quantity_ratio" type="number" min="0.1" step=".1" value="1"><small>Long calls at K<sub>1</sub></small></label>
    <label>Short vanilla-call ratio q<input name="short_vanilla_call_quantity_ratio" type="number" min="0.1" step=".1" value="1"><small>Short calls at K<sub>2</sub></small></label>
    <label>Short vanilla call K<sub>2</sub><select class="short-vanilla-call-select" name="short_vanilla_call_strike"></select><small>R$1 increments between K<sub>1</sub> and H</small></label>`;
  if (kind === "collar") return `
    <label>Portfolio value (BRL)<input name="portfolio_value" type="number" min="100000" step="100000" value="10000000"><small>Default study portfolio: R$ 10 million</small></label>
    <label>Position allocation (%)<input name="position_allocation_pct" type="number" min="0.1" max="100" step="0.1" value="10"><small>Underlying shares are derived from this allocation</small></label>
    <label>Protective put strike<select class="protective-put-select" name="protective_put_strike"></select><small>R$1 increments below spot</small></label>
    <label>Underlying ratio<input name="underlying_quantity_ratio" type="number" step=".1" value="1"></label>
    <label>Put ratio<input name="protective_put_quantity_ratio" type="number" step=".1" value="1"></label>
    <label>Call ratio<input name="call_quantity_ratio" type="number" step=".1" value="1"></label>`;
  if (kind === "box_ko") return holdingFields(`
    <label>Shared put/call ratio<input name="option_quantity_ratio" type="number" value="1" readonly><small>Fixed at 1:1 to preserve the Box KO payoff identity</small></label>`);
  if (kind === "bullet") return holdingFields(`
    <label>Forward strike K<sub>F</sub><select class="forward-strike-select" name="forward_strike"></select><small>Fixed forward delivery level</small></label>
    <label>Coupon Q / unit<input name="coupon_payout" type="number" min=".01" step=".01" value="10"><small>Paid only if lower barrier survives</small></label>`);
  if (kind === "bullet_plus") return holdingFields(`
    <label>Forward strike K<sub>F</sub><select class="forward-strike-select" name="forward_strike"></select><small>Fixed forward delivery level</small></label>
    <label>Coupon Q / unit<input name="coupon_payout" type="number" min=".01" step=".01" value="10"></label>
    <label>Long C<sub>UO</sub> ratio<input name="up_out_call_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>
    <label>Long C<sub>UO</sub> K<select class="up-out-call-select" name="up_out_call_strike"></select><small>R$1 increments above spot</small></label>
    <label>Upper KO barrier<select class="up-out-barrier-select" name="up_out_barrier"></select><small>Above the UO call strike</small></label>`);
  if (kind === "golden_bullet") return holdingFields(`
    <label>Forward strike K<sub>F</sub><select class="forward-strike-select" name="forward_strike"></select><small>Fixed forward delivery level</small></label>
    <label>Coupon Q / unit<input name="coupon_payout" type="number" min=".01" step=".01" value="10"></label>
    <label>Protective P<sub>DO</sub> K<select class="golden-put-select" name="protective_put_strike"></select><small>Between lower barrier and spot</small></label>
    <label>Long P<sub>DO</sub> ratio<input name="protective_put_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>`);
  if (kind === "collar_kiko") return holdingFields(`
    <label>Protective put K<select class="protective-put-select" name="protective_put_strike"></select><small>R$1 increments below spot</small></label>
    <label>Underlying ratio<input name="underlying_quantity_ratio" type="number" value="1" readonly><small>One share per base KI.KO unit</small></label>
    <label>Put ratio<input name="protective_put_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>
    <label>Long C<sub>UO</sub> ratio<input name="long_up_out_call_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>
    <label>Short C<sub>UI</sub> ratio<input name="short_up_in_call_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>
    <label>Short C<sub>UI</sub> K<sub>2</sub><select class="short-up-in-call-select" name="short_up_in_call_strike"></select><small>R$1 increments between K<sub>1</sub> and H</small></label>`);
  if (kind === "fence_kiko") return holdingFields(`
    <label>Upper put K<select class="upper-put-select" name="upper_put_strike"></select><small>R$1 increments below spot</small></label>
    <label>Lower put K<select class="lower-put-select" name="lower_put_strike"></select><small>R$1 increments below upper put</small></label>
    <label>Underlying ratio<input name="underlying_quantity_ratio" type="number" value="1" readonly><small>One share per base KI.KO unit</small></label>
    <label>Upper put ratio<input name="upper_put_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>
    <label>Lower put ratio<input name="lower_put_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>
    <label>Long C<sub>UO</sub> ratio<input name="long_up_out_call_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>
    <label>Short C<sub>UI</sub> ratio<input name="short_up_in_call_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>
    <label>Short C<sub>UI</sub> K<sub>2</sub><select class="short-up-in-call-select" name="short_up_in_call_strike"></select><small>R$1 increments between K<sub>1</sub> and H</small></label>`);
  if (kind === "call_kiko") return holdingFields(`
    <label>Underlying ratio<input name="underlying_quantity_ratio" type="number" value="1" readonly><small>One share per base KI.KO unit</small></label>
    <label>Long C<sub>UO</sub> ratio<input name="long_up_out_call_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>
    <label>Short C<sub>UI</sub> ratio<input name="short_up_in_call_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>
    <label>Short C<sub>UI</sub> K<sub>2</sub><select class="short-up-in-call-select" name="short_up_in_call_strike"></select><small>R$1 increments between K<sub>1</sub> and H</small></label>`);
  if (kind === "box_bullet") return holdingFields(`
    <label>Digital payout / unit<input name="digital_payout" type="number" min=".01" step=".01" value="10"><small>Cash paid if S<sub>T</sub> ≥ B</small></label>
    <label>Digital ratio<input name="digital_quantity_ratio" type="number" min=".1" step=".1" value="1"></label>`);
  if (kind === "digital") return `
    <label>Digital type<select name="digital_option_type"><option value="call">Digital Call · S<sub>T</sub> ≥ K</option><option value="put">Digital Put · S<sub>T</sub> ≤ K</option></select></label>
    <label>Fixed payout / unit<input name="digital_payout" type="number" min=".01" step=".01" value="10"></label>
    <label>Option quantity<input name="option_quantity" type="number" min="1" step="1" value="1"></label>
    <label>Contract multiplier<input name="contract_multiplier" type="number" min="1" step="1" value="1"></label>`;
  return `
    <label>Portfolio value (BRL)<input name="portfolio_value" type="number" min="100000" step="100000" value="10000000"><small>Default study portfolio: R$ 10 million</small></label>
    <label>Position allocation (%)<input name="position_allocation_pct" type="number" min="0.1" max="100" step="0.1" value="10"><small>Underlying shares are derived from this allocation</small></label>
    <label>Upper put strike<select class="upper-put-select" name="upper_put_strike"></select><small>R$1 increments below spot</small></label>
    <label>Lower put strike<select class="lower-put-select" name="lower_put_strike"></select><small>R$1 increments below upper put</small></label>
    <label>Underlying ratio<input name="underlying_quantity_ratio" type="number" step=".1" value="1"></label>
    <label>Upper put ratio<input name="upper_put_quantity_ratio" type="number" step=".1" value="1"></label>
    <label>Lower put ratio<input name="lower_put_quantity_ratio" type="number" step=".1" value="1"></label>
    <label>Call ratio<input name="call_quantity_ratio" type="number" step=".1" value="1"></label>`;
}

function holdingFields(extra) {
  return `<label>Portfolio value (BRL)<input name="portfolio_value" type="number" min="100000" step="100000" value="10000000"><small>Base used for portfolio-bps payoff</small></label>
    <label>Position allocation (%)<input name="position_allocation_pct" type="number" min=".1" max="100" step=".1" value="10"><small>Underlying shares are derived from this allocation</small></label>${extra}`;
}

function knockOutContractFields(kind) {
  const quantityNote = kind === "nitro"
    ? "The package is only the long call—there is no underlying holding."
    : "K<sub>1</sub> is the long Up-and-Out call strike. Require S<sub>0</sub> &lt; K<sub>1</sub> &lt; K<sub>2</sub> &lt; H.";
  return `
    <label>Spot<input class="spot-input" name="spot" type="number" step=".01" value="100"></label>
    <label>Long C<sub>UO</sub> strike K<sub>1</sub><select class="strike-select" name="strike" data-default-moneyness=".10"></select><small>${quantityNote}</small></label>
    <label>Knock-out barrier H<select class="barrier-select" name="barrier" data-default-moneyness=".25"></select><small>Touching H eliminates C<sub>UO</sub></small></label>
    <label>Valuation<input class="valuation-input" name="valuation_date" type="date" value="${isoDate(0)}"></label>
    <label>Expiration<input class="expiry-input" name="expiration_date" type="date" value="${isoDate(180)}"></label>
    <label>DI rate<input class="rate-input" name="rate" type="number" step=".0001" value=".12"></label>
    <label>Dividend yield<input class="dividend-input" name="dividend_yield" type="number" step=".0001" value=".04"></label>
    <label>Volatility<input class="vol-input" name="volatility" type="number" step=".0001" value=".25"></label>
    <label>Monitoring<select name="monitoring"><option value="continuous">Continuous</option><option value="daily_close">Daily close</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="maturity_only">Maturity only</option></select></label>
    <label>Barrier status<select name="barrier_status"><option value="not_triggered">Not triggered</option><option value="triggered">Already triggered</option></select><small>Triggered means the C<sub>UO</sub> has already knocked out.</small></label>
    <label>Paths<input name="paths" type="number" min="5000" max="500000" value="50000"></label>
    <label>Seed<input name="seed" type="number" value="42"></label>`;
}

function downOutContractFields(kind) {
  return `
    <label>Spot<input class="spot-input" name="spot" type="number" step=".01" value="100"></label>
    <label>Shared Down-and-Out K<select class="strike-select" name="strike" data-default-moneyness="-.10"></select><small>K is above the lower knock-out barrier</small></label>
    <label>Lower KO barrier B<select class="barrier-select" name="barrier" data-default-moneyness="-.25"></select><small>Touching B eliminates the DO option</small></label>
    ${sharedMarketContractFields()}`;
}

function boxBulletContractFields() {
  return `
    <label>Spot<input class="spot-input" name="spot" type="number" step=".01" value="100"></label>
    <label>Bullet level B<select class="bullet-level-select" name="bullet_level"></select><small>Only the expiry close is tested</small></label>
    ${sharedMarketContractFields()}`;
}

function digitalContractFields() {
  return `
    <label>Spot<input class="spot-input" name="spot" type="number" step=".01" value="100"></label>
    <label>Digital strike K<select class="digital-strike-select" name="strike"></select><small>Binary terminal observation</small></label>
    ${sharedMarketContractFields()}`;
}

function sharedMarketContractFields() {
  return `<label>Valuation<input class="valuation-input" name="valuation_date" type="date" value="${isoDate(0)}"></label>
    <label>Expiration<input class="expiry-input" name="expiration_date" type="date" value="${isoDate(180)}"></label>
    <label>DI rate<input class="rate-input" name="rate" type="number" step=".0001" value=".12"></label>
    <label>Dividend yield<input class="dividend-input" name="dividend_yield" type="number" step=".0001" value=".04"></label>
    <label>Volatility<input class="vol-input" name="volatility" type="number" step=".0001" value=".25"></label>
    <label>Paths<input name="paths" type="number" min="5000" max="500000" value="50000"></label>
    <label>Seed<input name="seed" type="number" value="42"></label>`;
}

function vanillaStrategyContractFields() {
  return `<label>Spot<input class="spot-input" name="spot" type="number" step=".01" value="100"></label>${sharedMarketContractFields()}`;
}

$$(".package-host").forEach(host => {
  const kind = host.dataset.kind;
  const title = packageTitle(kind);
  const contractTitle = packageContractTitle(kind);
  host.innerHTML = `<form class="package-form" data-kind="${kind}">
    <div class="card"><h3>${title}</h3><div class="structure-fields">${structureFields(kind)}</div></div>
    <div class="card"><h3>${contractTitle}</h3><div class="base-contract">${contractFields(kind)}</div></div>
    <input type="hidden" name="zero_cost_tolerance" value=".01">
    <div class="form-errors"></div><div class="actions"><button class="primary">Price & decompose</button></div>
  </form><div class="result-shell"><div class="empty-result">The signed premium decomposition will appear here.</div></div>`;
});

function packageTitle(kind) {
  return ({nitro:"Nitro package", double_up_ko:"Double Up KO legs", box_ko:"Box KO legs", box_bullet:"Box Bullet legs", bullet:"Bullet legs", bullet_plus:"Bullet Plus legs", golden_bullet:"Golden Bullet legs", collar_kiko:"Collar KI.KO legs", fence_kiko:"Fence KI.KO legs", call_kiko:"Call KI.KO legs", digital:"Digital option"})[kind] || "Template legs";
}

function packageContractTitle(kind) {
  if (["nitro", "double_up_ko", "collar_kiko", "fence_kiko", "call_kiko"].includes(kind)) return "Upper barrier & market";
  if (["box_ko", "bullet", "bullet_plus", "golden_bullet"].includes(kind)) return "Lower barrier & market";
  return kind === "digital" ? "Digital market inputs" : kind === "box_bullet" ? "Maturity observation & market" : "Shared market & Up-and-In call";
}

function integerLevels(minimum, maximum) {
  const values = [];
  for (let value = Math.ceil(minimum); value <= Math.floor(maximum); value += 1) values.push(value);
  return values;
}

function fillLevelSelect(select, levels, preferred) {
  if (!select || !levels.length) return;
  const selected = levels.reduce((best, value) =>
    Math.abs(value - preferred) < Math.abs(best - preferred) ? value : best, levels[0]);
  select.innerHTML = levels.map(value =>
    '<option value="' + value + '"' + (value === selected ? " selected" : "") + '>R$ ' + value.toFixed(2) + "</option>"
  ).join("");
}

function configureStructureLegSelectors(scope, spot, preserve = false) {
  const protectivePut = $(".protective-put-select", scope);
  if (protectivePut) {
    const current = Number(protectivePut.value);
    fillLevelSelect(
      protectivePut,
      integerLevels(Math.max(1, spot * .40), spot - 1),
      preserve && current ? current : spot * .90
    );
  }

  const upperPut = $(".upper-put-select", scope);
  const lowerPut = $(".lower-put-select", scope);
  if (upperPut && lowerPut) {
    const currentUpper = Number(upperPut.value);
    const currentLower = Number(lowerPut.value);
    fillLevelSelect(
      upperPut,
      integerLevels(Math.max(2, spot * .40), spot - 1),
      preserve && currentUpper ? currentUpper : spot * .90
    );
    const selectedUpper = Number(upperPut.value);
    fillLevelSelect(
      lowerPut,
      integerLevels(Math.max(1, spot * .20), selectedUpper - 1),
      preserve && currentLower < selectedUpper ? currentLower : spot * .75
    );
  }
  const shortVanillaCall = $(".short-vanilla-call-select", scope);
  const shortUpInCall = $(".short-up-in-call-select", scope);
  const longUpOutCall = $(".strike-select", scope);
  const barrier = $(".barrier-select", scope);
  if (shortVanillaCall && longUpOutCall && barrier) {
    const current = Number(shortVanillaCall.value);
    const lower = Number(longUpOutCall.value) + 1;
    const upper = Number(barrier.value) - 1;
    fillLevelSelect(shortVanillaCall, integerLevels(lower, upper), preserve && current ? current : Number(longUpOutCall.value) + 5);
  }
  if (shortUpInCall && longUpOutCall && barrier) {
    const current = Number(shortUpInCall.value);
    fillLevelSelect(shortUpInCall, integerLevels(Number(longUpOutCall.value) + 1, Number(barrier.value) - 1), preserve && current ? current : Number(longUpOutCall.value) + 5);
  }
  const upOutCall = $(".up-out-call-select", scope);
  const upOutBarrier = $(".up-out-barrier-select", scope);
  if (upOutCall && upOutBarrier) {
    const callCurrent = Number(upOutCall.value), barrierCurrent = Number(upOutBarrier.value);
    fillLevelSelect(upOutCall, integerLevels(spot + 1, spot * 1.6), preserve && callCurrent ? callCurrent : spot * 1.10);
    fillLevelSelect(upOutBarrier, integerLevels(Number(upOutCall.value) + 1, spot * 2), preserve && barrierCurrent ? barrierCurrent : spot * 1.25);
  }
  const bulletLevel = $(".bullet-level-select", scope);
  if (bulletLevel) fillLevelSelect(bulletLevel, integerLevels(Math.max(1, spot * .4), spot * 1.4), preserve && Number(bulletLevel.value) ? Number(bulletLevel.value) : spot * .8);
  const digitalStrike = $(".digital-strike-select", scope);
  if (digitalStrike) fillLevelSelect(digitalStrike, integerLevels(Math.max(1, spot * .4), spot * 1.6), preserve && Number(digitalStrike.value) ? Number(digitalStrike.value) : spot);
  const forwardStrike = $(".forward-strike-select", scope);
  if (forwardStrike) fillLevelSelect(forwardStrike, integerLevels(Math.max(1, spot * .5), spot * 1.5), preserve && Number(forwardStrike.value) ? Number(forwardStrike.value) : spot);
  const goldenPut = $(".golden-put-select", scope);
  if (goldenPut && barrier) {
    fillLevelSelect(
      goldenPut,
      integerLevels(Number(barrier.value) + 1, spot - 1),
      preserve && Number(goldenPut.value) ? Number(goldenPut.value) : spot * .9
    );
  }
}

function configureMoneynessSelectors(scope, spot, preserveStrike = false) {
  if (!Number.isFinite(spot) || spot <= 1) return;
  const strikeSelect = $(".strike-select", scope);
  const barrierSelect = $(".barrier-select", scope);
  if (!strikeSelect || !barrierSelect) {
    configureStructureLegSelectors(scope, spot, preserveStrike);
    return;
  }
  const kind = scope.dataset.kind;
  const downOut = ["box_ko", "bullet", "bullet_plus", "golden_bullet"].includes(kind);
  const optionType = downOut ? "put" : $('[name="option_type"]', scope)?.value || "call";
  const direction = downOut ? "down" : $('[name="direction"]', scope)?.value || "up";
  const currentStrike = Number(strikeSelect.value);
  const strikePreferred = preserveStrike && currentStrike ? currentStrike : spot * (optionType === "call" ? 1.10 : .90);
  const strikeLevels = optionType === "call"
    ? integerLevels(spot + 1, spot * 1.60)
    : integerLevels(Math.max(1, spot * .40), spot - 1);
  fillLevelSelect(strikeSelect, strikeLevels, strikePreferred);
  const strike = Number(strikeSelect.value);
  const barrierLevels = direction === "up"
    ? integerLevels(Math.max(spot, strike) + 1, spot * 2)
    : integerLevels(Math.max(1, spot * .20), Math.min(spot, strike) - 1);
  fillLevelSelect(barrierSelect, barrierLevels, spot * (direction === "up" ? 1.25 : .75));
  configureStructureLegSelectors(scope, spot, preserveStrike);
}

function initializeMoneynessControls() {
  $$(".pricing-form, .package-form").forEach(form => {
    const spotInput = $(".spot-input", form);
    if (!spotInput) return;
    configureMoneynessSelectors(form, Number(spotInput.value));
    spotInput.addEventListener("change", () => configureMoneynessSelectors(form, Number(spotInput.value)));
    $(".strike-select", form)?.addEventListener("change", () => configureMoneynessSelectors(form, Number(spotInput.value), true));
    $(".upper-put-select", form)?.addEventListener("change", () => configureStructureLegSelectors(form, Number(spotInput.value), true));
    $('[name="option_type"]', form)?.addEventListener("change", () => configureMoneynessSelectors(form, Number(spotInput.value)));
    $('[name="direction"]', form)?.addEventListener("change", () => configureMoneynessSelectors(form, Number(spotInput.value), true));
  });
}
initializeMoneynessControls();

function formObject(form) {
  const raw = Object.fromEntries(new FormData(form).entries());
  $$('input[type="checkbox"]', form).forEach(input => raw[input.name] = input.checked);
  for (const [key, value] of Object.entries(raw)) {
    if (["option_type", "direction", "behavior", "monitoring", "barrier_status", "rebate_timing", "valuation_date", "expiration_date", "kind", "solve_for"].includes(key)) continue;
    if (value !== "" && !Number.isNaN(Number(value))) raw[key] = Number(value);
  }
  return raw;
}

function normalizeContract(data) {
  return {
    option_type: data.option_type || "call", direction: data.direction || "up", behavior: data.behavior || "in",
    spot: data.spot, strike: data.strike, barrier: data.barrier, valuation_date: data.valuation_date,
    expiration_date: data.expiration_date, rate: data.rate, dividend_yield: data.dividend_yield,
    volatility: data.volatility, quantity: data.quantity || 1, multiplier: data.multiplier || 1,
    rebate: data.rebate || 0, rebate_timing: data.rebate_timing || "expiry",
    monitoring: data.monitoring || "continuous", barrier_status: data.barrier_status || "not_triggered",
    paths: data.paths || 50000, seed: data.seed ?? 42, calculate_greeks: Boolean(data.calculate_greeks)
  };
}

function normalizePackageContract(data, kind) {
  const contract = normalizeContract(data);
  if (["nitro", "double_up_ko", "collar_kiko", "fence_kiko", "call_kiko"].includes(kind)) {
    contract.option_type = "call";
    contract.direction = "up";
    contract.behavior = "out";
  }
  if (["box_ko", "bullet", "bullet_plus", "golden_bullet"].includes(kind)) {
    contract.option_type = "put";
    contract.direction = "down";
    contract.behavior = "out";
  }
  if (kind === "box_bullet") {
    contract.option_type = "call";
    contract.direction = "up";
    contract.behavior = "out";
    contract.strike = data.bullet_level;
    contract.barrier = data.spot * 1.5;
    contract.monitoring = "maturity_only";
    contract.barrier_status = "not_applicable";
  }
  if (kind === "digital") {
    contract.option_type = data.digital_option_type || "call";
    contract.direction = "up";
    contract.behavior = "out";
    contract.barrier = data.spot * 1.5;
    contract.monitoring = "maturity_only";
    contract.barrier_status = "not_applicable";
  }
  if (["call_spread", "risk_reversal", "seagull", "straddle", "strangle", "reverse_condor", "double_up", "double_up_hedge", "seagull_ki"].includes(kind)) {
    contract.option_type = "call"; contract.direction = "up"; contract.behavior = "out";
    contract.strike = data.common_strike || data.lower_call_strike || data.call_strike || data.inner_call_strike;
    contract.barrier = data.spot * 2; contract.monitoring = "maturity_only"; contract.barrier_status = "not_applicable";
  }
  return contract;
}

async function postJSON(url, payload) {
  const response = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": csrf()}, body: JSON.stringify(payload)});
  const body = await response.json();
  if (!response.ok) throw body.error || {message: `HTTP ${response.status}`};
  return body.data;
}

function errorText(error) {
  if (error.fields) return Object.entries(error.fields).map(([field, messages]) => `${field}: ${messages.join(" ")}`).join("\n");
  return error.message || String(error);
}

function money(value) {
  return typeof value === "number" ? value.toLocaleString("pt-BR", {minimumFractionDigits: 4, maximumFractionDigits: 4}) : "—";
}

function metricPresentation(key, value) {
  const presentations = {
    protective_put_premium: ["Protective put premium", "User pays", "debit"],
    long_put_premium: ["Upper protective put premium", "User pays", "debit"],
    short_put_premium: ["Lower short put premium", "User receives", "credit"],
    up_in_call_premium: ["Short Up-and-In call premium", "User receives", "credit"],
    equivalent_vanilla_call_premium: ["Equivalent vanilla short-call premium", "User would receive", "comparison"],
    vanilla_barrier_premium_difference: ["Premium sacrificed versus vanilla call", "Less premium received", "comparison"],
  };
  if (key === "net_option_cost") {
    if (Math.abs(value) <= 1e-9) return {label:"Net option premium", value:0, note:"Approximately zero cost", tone:"comparison"};
    return value > 0
      ? {label:"Net option premium", value, note:"User pays", tone:"debit"}
      : {label:"Net option premium", value:Math.abs(value), note:"User receives", tone:"credit"};
  }
  const presentation = presentations[key];
  return presentation
    ? {label:presentation[0], value:Math.abs(value), note:presentation[1], tone:presentation[2]}
    : {label:key.replaceAll("_"," "), value, note:"", tone:""};
}

function quantity(value) {
  return Number(value).toLocaleString("pt-BR", {maximumFractionDigits:4});
}

function cashFlowItem(label, value, note = "", legQuantity = null, unitPremium = null) {
  const calculation = legQuantity == null ? note : `${quantity(legQuantity)} units × R$ ${money(unitPremium)} per unit · ${note}`;
  return `<div class="cash-flow-item"><span>${label}</span><strong>R$ ${money(Math.abs(value))}</strong>${calculation ? `<small>${calculation}</small>` : ""}</div>`;
}

function resultNumber(result, key) {
  return typeof result[key] === "number" ? result[key] : null;
}

const retailKinds = new Set(["box_ko", "box_bullet", "bullet", "bullet_plus", "golden_bullet", "collar_kiko", "fence_kiko", "call_kiko", "digital", "call_spread", "risk_reversal", "seagull", "straddle", "strangle", "reverse_condor", "double_up", "double_up_hedge", "seagull_ki"]);

function retailName(kind) {
  return ({box_ko:"Box KO", box_bullet:"Box Bullet", bullet:"Bullet", bullet_plus:"Bullet Plus", golden_bullet:"Golden Bullet", collar_kiko:"Collar KI.KO", fence_kiko:"Fence KI.KO", call_kiko:"Call KI.KO", digital:"Digital Call / Put", call_spread:"Call Spread", risk_reversal:"Risk Reversal", seagull:"Seagull", straddle:"Long Straddle", strangle:"Long Strangle", reverse_condor:"Reverse Condor", double_up:"Double Up", double_up_hedge:"Double Up Hedge", seagull_ki:"Seagull KI"})[kind] || kind;
}

function renderRetailEconomics(result) {
  const debit = result.net_option_cost > 1e-9;
  const zero = Math.abs(result.net_option_cost || 0) <= 1e-9;
  const total = resultNumber(result, "total_initial_cash_requirement") ?? resultNumber(result, "net_option_cost");
  const legs = result.premium_legs || [];
  const paid = legs.filter(leg => leg.side === "paid");
  const received = legs.filter(leg => leg.side === "received");
  const unknown = legs.filter(leg => !["paid", "received"].includes(leg.side));
  const legMarkup = leg => cashFlowItem(leg.label, leg.premium, leg.note || "", leg.units, leg.unit_premium);
  const quantities = Object.entries(result.leg_quantities || {}).map(([key, value]) => `<span><b>${quantity(value)}</b>${key.replaceAll("_", " ")}</span>`).join("");
  return `<section class="package-economics retail-economics">
    <div class="structure-total"><div><small>Entire ${retailName(result.kind)} initial value</small><strong>R$ ${money(total)}</strong></div>
      <p><span>${result.formula || "Representative lab v1 package"}</span></p>
      <div class="net-premium ${zero ? "comparison" : debit ? "debit" : "credit"}"><small>Net option package</small><strong>R$ ${money(Math.abs(result.net_option_cost || 0))}</strong><span>${zero ? "Approximately zero cost" : debit ? "Client pays" : "Client receives"}</span></div>
    </div>
    <div class="quantity-pills">${quantities}</div>
    <div class="cash-flow-columns"><article class="flow-paid"><h4>Client pays</h4>${paid.length ? paid.map(legMarkup).join("") : '<div class="cash-flow-item"><span>No initial debit leg</span><strong>—</strong></div>'}</article>
      <article class="flow-received"><h4>Client receives</h4>${received.length ? received.map(legMarkup).join("") : '<div class="cash-flow-item"><span>No initial credit leg</span><strong>—</strong></div>'}</article>
      <article class="flow-comparison"><h4>Package convention</h4>${unknown.length ? unknown.map(legMarkup).join("") : `<div class="cash-flow-item"><span>Formula</span><strong>Lab v1</strong><small>Every displayed leg uses the ratio shown above.</small></div>`}</article>
    </div>
    <p class="formula-note"><strong>Representative convention.</strong> ${result.formula_note || "This educational package follows the displayed lab v1 formula. An executable RFQ can use different strikes, ratios, monitoring and dealer adjustments."}</p>
  </section>`;
}

function renderKnockOutEconomics(result) {
  const isNitro = result.kind === "nitro";
  const isDebit = result.net_option_cost > 1e-9;
  const isZero = Math.abs(result.net_option_cost) <= 1e-9;
  const netLabel = isZero ? "Approximately zero cost" : isDebit ? "Client pays" : "Client receives";
  const snapshot = result.contract_snapshot || {};
  const premiums = result.unit_premiums || {};
  const quantities = result.leg_quantities || {};
  const upOutPremium = resultNumber(result, "up_out_call_premium");
  const vanillaPremium = resultNumber(result, "short_vanilla_call_premium") ?? resultNumber(result, "vanilla_call_premium");
  const vanillaEquivalent = resultNumber(result, "equivalent_vanilla_call_premium");
  const premiumDifference = resultNumber(result, "vanilla_barrier_premium_difference");
  const structureName = isNitro ? "Nitro — Call Up-and-Out" : "Double Up KO";
  const k1 = snapshot.up_out_call_strike ?? snapshot.call_strike;
  const k2 = snapshot.short_vanilla_call_strike ?? snapshot.vanilla_call_strike;
  const upOutPaid = cashFlowItem("Long Up-and-Out call", upOutPremium, "Premium paid", quantities.long_up_out_call_units, premiums.up_out_call);
  const vanillaReceived = !isNitro && vanillaPremium != null
    ? cashFlowItem("Short vanilla call", vanillaPremium, "Premium received", quantities.short_vanilla_call_units, premiums.vanilla_call)
    : "<div class=\"cash-flow-item\"><span>No short vanilla call</span><strong>—</strong><small>Nitro is a standalone long C<sub>UO</sub>.</small></div>";
  const comparison = vanillaEquivalent != null || premiumDifference != null
    ? `<article class="flow-comparison"><h4>Vanilla comparison</h4>${vanillaEquivalent != null ? cashFlowItem("Equivalent long vanilla call", vanillaEquivalent, "Would cost without knock-out") : ""}${premiumDifference != null ? cashFlowItem("Premium saved with barrier", premiumDifference, "Lower initial outlay") : ""}</article>`
    : "";
  const totalInitial = resultNumber(result, "total_initial_cash_requirement");
  return `<section class="package-economics knockout-economics">
    <div class="structure-total">
      <div><small>Entire ${structureName} initial value</small><strong>R$ ${money(totalInitial)}</strong></div>
      <p><span>${isNitro ? "Long C<sub>UO</sub>(K, H) only" : `S + long C<sub>UO</sub>(K<sub>1</sub>, H) − qC(K<sub>2</sub>)`}</span><b>·</b><span>K<sub>1</sub> R$ ${money(k1)}${k2 != null ? ` · K<sub>2</sub> R$ ${money(k2)}` : ""} · H R$ ${money(snapshot.barrier)}</span></p>
      <div class="net-premium ${isZero ? "comparison" : isDebit ? "debit" : "credit"}"><small>Net option package</small><strong>R$ ${money(Math.abs(result.net_option_cost))}</strong><span>${netLabel}</span></div>
    </div>
    <div class="cash-flow-columns">
      <article class="flow-paid"><h4>Client pays</h4>${upOutPaid}</article>
      <article class="flow-received"><h4>Client receives</h4>${vanillaReceived}</article>
      ${comparison}
    </div>
    <p class="knockout-result-note">A monitored touch of H eliminates the long C<sub>UO</sub>. This remains true if the terminal price later falls below H.</p>
  </section>`;
}

function renderPackageEconomics(result) {
  if (retailKinds.has(result.kind)) return renderRetailEconomics(result);
  if (result.kind === "nitro" || result.kind === "double_up_ko") return renderKnockOutEconomics(result);
  const isDebit = result.net_option_cost > 1e-9;
  const isZero = Math.abs(result.net_option_cost) <= 1e-9;
  const netLabel = isZero ? "Approximately zero cost" : isDebit ? "User pays" : "User receives";
  const operator = result.net_option_cost >= 0 ? "+" : "−";
  const paid = result.kind === "collar"
    ? cashFlowItem("Protective put", result.protective_put_premium, "Premium paid", result.leg_quantities.protective_put_units, result.unit_premiums.protective_put)
    : cashFlowItem("Upper protective put", result.long_put_premium, "Premium paid", result.leg_quantities.upper_put_units, result.unit_premiums.upper_put);
  const receivedItems = [];
  if (result.kind === "fence") receivedItems.push(cashFlowItem("Lower short put", result.short_put_premium, "Premium received", result.leg_quantities.short_lower_put_units, result.unit_premiums.lower_put));
  receivedItems.push(cashFlowItem("Short Up-and-In call", result.up_in_call_premium, "Premium received", result.leg_quantities.short_up_in_call_units, result.unit_premiums.up_in_call));
  const structureName = result.kind === "collar" ? "Collar Up-and-In" : "Fence Up-and-In";
  return `<section class="package-economics">
    <div class="structure-total">
      <div><small>Entire ${structureName} initial value</small><strong>R$ ${money(result.total_initial_cash_requirement)}</strong></div>
      <p><span>${quantity(result.leg_quantities.underlying_shares)} shares × R$ ${money(result.contract_snapshot.spot)} = R$ ${money(result.underlying_value)}</span><b>${operator}</b><span>Option package R$ ${money(Math.abs(result.net_option_cost))}</span><b>=</b><span>R$ ${money(result.total_initial_cash_requirement)}</span></p>
      <div class="net-premium ${isZero ? "comparison" : isDebit ? "debit" : "credit"}"><small>Net option package</small><strong>R$ ${money(Math.abs(result.net_option_cost))}</strong><span>${netLabel}</span></div>
    </div>
    <div class="cash-flow-columns">
      <article class="flow-paid"><h4>User pays</h4>${paid}</article>
      <article class="flow-received"><h4>User receives</h4>${receivedItems.join("")}</article>
      <article class="flow-comparison"><h4>Vanilla comparison</h4>
        ${cashFlowItem("Equivalent vanilla short call", result.equivalent_vanilla_call_premium, "Would be received")}
        ${cashFlowItem("Premium sacrificed with barrier", result.vanilla_barrier_premium_difference, "Less financing")}
      </article>
    </div>
  </section>`;
}

function greekValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return Number(value).toLocaleString("pt-BR", {minimumFractionDigits:4, maximumFractionDigits:4, signDisplay:"always"});
}

function deltaValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const decimal = Number(value).toLocaleString("pt-BR", {minimumFractionDigits:4, maximumFractionDigits:4, signDisplay:"always"});
  const marketDelta = Number(value * 100).toLocaleString("pt-BR", {minimumFractionDigits:1, maximumFractionDigits:1, signDisplay:"always"});
  return `${decimal} · ${marketDelta}Δ`;
}

function structureBaseUnits(result) {
  if (typeof result.base_share_quantity === "number" && result.base_share_quantity > 0) return result.base_share_quantity;
  const standaloneUnits = result.option_quantity * result.contract_multiplier;
  if (Number.isFinite(standaloneUnits) && standaloneUnits > 0) return standaloneUnits;
  return Object.values(result.leg_quantities || {}).find(value => typeof value === "number" && value > 0) || 1;
}

function greekUnitLabel(key) {
  return ({delta:"unit option delta", gamma:"per R$1² spot", vega_per_1pct:"per 1 vol point", theta_per_calendar_day:"per day", rho_per_1bp:"per bp"})[key];
}

function renderStructureGreeks(result) {
  const composition = result.structure_greeks;
  if (!composition) return "";
  const names = [
    ["delta", "Delta"], ["gamma", "Gamma"], ["vega_per_1pct", "Vega / 1%"],
    ["theta_per_calendar_day", "Theta / day"], ["rho_per_1bp", "Rho / bp"]
  ];
  const structures = [
    ["Barrier package", composition.barrier_structure],
    ["Vanilla benchmark", composition.vanilla_structure],
    ["Package", composition.package_structure ?? composition.structure],
  ].filter(([, structure], index, entries) => structure?.total && !entries.slice(0, index).some(([, prior]) => prior === structure));
  if (!structures.length && composition.total) structures.push(["Package", {total:composition.total, legs:composition.legs || []}]);
  const primary = structures[0]?.[1];
  const packageDelta = composition.package_delta ?? primary?.total?.delta;
  const comparison = structures.length > 1;
  if (!comparison && structures.length) structures[0][0] = "Package";
  const rows = structures.flatMap(([label, structure]) => (structure.legs || []).map(leg => ({structure:label, ...leg})));
  const bumps = composition.bumps || {};
  const baseUnits = structureBaseUnits(result);
  const portfolioValue = result.portfolio_context?.portfolio_value;
  const scaledGreek = (value, scale) => scale === "unit" ? value / baseUnits : scale === "bps" ? value / portfolioValue * 10_000 : value;
  return `<section class="structure-greeks">
    <header class="greek-heading"><div><small>FULL-PACKAGE SENSITIVITIES</small><h3>${comparison ? "Structure Greeks and vanilla comparison" : "Structure Greeks"}</h3><p>Delta is dimensionless: option value change divided by spot change. A put displayed as −0.2500 is a −25Δ put. Other Greeks remain monetary sensitivities for the stated volatility, time and rate bumps.</p></div><div class="package-delta"><small>Package delta per base unit</small><strong>${deltaValue(scaledGreek(packageDelta, "unit"))}</strong><span>Dimensionless · normalized across ${quantity(baseUnits)} base units</span><div><b>Full position delta</b><em>${greekValue(packageDelta)} equivalent underlying units</em></div></div></header>
    <div class="greek-total-cards">${names.map(([key, label]) => `<article><small>${label} · ${greekUnitLabel(key)}</small>${structures.map(([structureLabel, structure]) => `<div class="greek-scale-name"><b>${structureLabel}</b></div>${key === "delta" ? `<div><span>Per base unit</span><strong>${deltaValue(scaledGreek(structure.total.delta, "unit"))}</strong></div><div><span>Position delta</span><strong>${greekValue(structure.total.delta)} units</strong></div>` : `<div><span>Per base unit</span><strong>${greekValue(scaledGreek(structure.total[key], "unit"))}</strong></div><div><span>Full position BRL</span><strong>${greekValue(structure.total[key])}</strong></div>${portfolioValue ? `<div><span>Portfolio bps</span><strong>${greekValue(scaledGreek(structure.total[key], "bps"))}</strong></div>` : ""}`}`).join("")}</article>`).join("")}</div>
    ${rows.length ? `<div class="greek-composition-wrap"><table class="greek-composition"><thead><tr><th>Package</th><th>Signed leg</th><th>Units</th><th>Signed unit delta</th><th>Position delta</th>${names.slice(1).map(([, label]) => `<th>${label} total</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr><td>${row.structure}</td><td>${row.label}</td><td>${quantity(row.signed_quantity)}</td><td>${deltaValue(row.unit_greeks?.delta * Math.sign(row.signed_quantity))}</td><td>${greekValue(row.contribution?.delta)}</td>${names.slice(1).map(([key]) => `<td>${greekValue(row.contribution?.[key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : ""}
    ${composition.conventions?.method ? `<p class="greek-method">${composition.conventions.method}${typeof bumps.spot === "number" ? ` Bumps: R$ ${money(bumps.spot)} spot, ${(bumps.volatility * 100).toFixed(0)} vol point, ${(bumps.rate * 10000).toFixed(0)} bp rate, and ${bumps.theta_days} calendar day.` : ""}</p>` : ""}
  </section>`;
}

function renderStaticReplication(result) {
  const states = Object.entries(result.scenario_analysis?.states || {});
  if (!states.length) return "";
  const spot = result.contract_snapshot?.spot;
  const stateRows = states.map(([name, rows]) => [name, rows.reduce((closest, row) => !closest || Math.abs(row.terminal_price - spot) < Math.abs(closest.terminal_price - spot) ? row : closest, null)]).filter(([, row]) => row);
  const legNames = [...new Set(stateRows.flatMap(([, row]) => Object.keys(row.leg_payoffs || {})))];
  if (!legNames.length) return "";
  const normalizeLeg = value => String(value).toLowerCase().replace(/[^a-z0-9]/g, "").replace(/units$|shares$/g, "");
  const premiumLegs = result.premium_legs || [];
  const quantities = result.leg_quantities || {};
  const aliases = {protective_put:"long_protective_put", long_put:"long_upper_put", short_put:"short_lower_put", up_in_call:"short_up_in_call", knockout_rebate:"long_up_out_call"};
  const metadata = leg => {
    if (leg === "underlying") return {label:"Long underlying", units:quantities.underlying_shares ?? result.base_share_quantity, premium:result.underlying_value, side:"paid"};
    const canonical = aliases[leg] || leg;
    const premium = premiumLegs.find(item => normalizeLeg(item.label) === normalizeLeg(canonical) || normalizeLeg(item.label).includes(normalizeLeg(canonical)) || normalizeLeg(canonical).includes(normalizeLeg(item.label)));
    const quantityEntry = Object.entries(quantities).find(([key]) => normalizeLeg(key) === normalizeLeg(canonical) || normalizeLeg(key).includes(normalizeLeg(canonical)) || normalizeLeg(canonical).includes(normalizeLeg(key)));
    return {label:premium?.label || canonical.replaceAll("_", " "), units:premium?.units ?? quantityEntry?.[1], premium:premium?.premium, side:premium?.side};
  };
  const currentPrice = stateRows[0][1].terminal_price;
  return `<section class="static-replication"><header><div><small>STATIC REPLICATION EXAMPLE</small><h3>Build the displayed payoff from these legs</h3><p>Leg cash flows are shown at the chart point nearest today’s spot (S<sub>T</sub> = R$ ${money(currentPrice)}). Barrier-dependent legs differ by path state.</p></div><div><small>Package initial value</small><strong>R$ ${money(resultNumber(result, "total_initial_cash_requirement") ?? resultNumber(result, "net_option_cost"))}</strong></div></header>
    <div class="replication-table-wrap"><table class="replication-table"><thead><tr><th>Leg</th><th>Position / quantity</th><th>Initial premium</th>${stateRows.map(([name]) => `<th>Payoff · ${name.replaceAll("_", " ")}</th>`).join("")}</tr></thead><tbody>${legNames.map(leg => { const meta = metadata(leg); const direction = /short/i.test(meta.label) ? "Short" : "Long"; const signedUnits = direction === "Short" && meta.units != null ? -Math.abs(meta.units) : meta.units; const signedPremium = meta.premium == null ? null : meta.side === "received" ? -Math.abs(meta.premium) : Math.abs(meta.premium); return `<tr><td>${meta.label}</td><td>${signedUnits == null ? direction : `${quantity(signedUnits)} units`}</td><td>${signedPremium == null ? "—" : `R$ ${money(signedPremium)}`}</td>${stateRows.map(([, row]) => `<td>R$ ${money(row.leg_payoffs?.[leg] ?? 0)}</td>`).join("")}</tr>`; }).join("")}</tbody><tfoot><tr><th colspan="3">Current package payoff / P&amp;L</th>${stateRows.map(([, row]) => `<th>R$ ${money(row.total_payoff)}<small>P&amp;L R$ ${money(row.total_pnl)}</small></th>`).join("")}</tr></tfoot></table></div>
    <p>The replication is static at maturity: add the signed payoff of each leg. Path-dependent barrier states cannot be reproduced by terminal price alone.</p></section>`;
}

function structureScenarioMarkup(result) {
  const scenario = result.scenario_analysis;
  if (!scenario) return "";
  if (retailKinds.has(result.kind)) {
    const spot = result.contract_snapshot.spot;
    const lowMove = (scenario.scenario_range[0] / spot - 1) * 100;
    const highMove = (scenario.scenario_range[1] / spot - 1) * 100;
    const unit = scenario.chart_unit === "BRL" ? "BRL P&L" : "portfolio bps";
    return `<section class="embedded-scenarios">
      <div class="embedded-scenario-heading"><div><small>PAYOFF BY BARRIER STATE</small><h3>Compare the package across barrier outcomes</h3><p>${result.formula_note || "Each curve shows the package payoff for a different barrier history. Curves stop where that barrier state is impossible at expiry."}</p></div>
        <div class="quantity-pills">${Object.entries(result.leg_quantities || {}).map(([key,value])=>`<span><b>${quantity(value)}</b>${key.replaceAll("_"," ")}</span>`).join("")}</div></div>
      <article class="embedded-chart-card"><header><span>${result.portfolio_context ? `${result.portfolio_context.actual_allocation_pct.toFixed(2)}% actual portfolio allocation · ${quantity(result.base_share_quantity)} base shares` : "Standalone binary option position"}</span><strong>Package payoff and P&amp;L in ${unit}</strong><small>Terminal range: ${lowMove.toFixed(0)}% to +${highMove.toFixed(0)}% versus spot.</small></header><div class="leg-toggle-panel" data-leg-toggles></div><div class="embedded-canvas"><canvas data-structure-chart="combined"></canvas></div>${spotExplorerMarkup(result)}<p>Leg buttons remove that leg's terminal cash flow so you can isolate its payoff effect. The spot slider reprices today's package and Greeks; the chart itself remains the maturity payoff.</p></article>
      ${renderStaticReplication(result)}
      <div class="embedded-outcomes">${Object.entries(scenario.outcome_summary || {}).map(([name,summary]) => `<article><small>${name.replaceAll("_", " ")}</small><strong>${typeof summary.maximum_payoff === "number" ? "R$ "+money(summary.maximum_payoff) : summary.maximum_payoff ?? "—"}</strong><span>Maximum payoff in this state</span><p>${summary.description || summary.upside_explanation || "See the corresponding curve and leg state."}</p></article>`).join("")}</div>
    </section>`;
  }
  const isKnockOut = result.kind === "nitro" || result.kind === "double_up_ko";
  const spot = result.contract_snapshot.spot;
  const lowMove = (scenario.scenario_range[0] / spot - 1) * 100;
  const highMove = (scenario.scenario_range[1] / spot - 1) * 100;
  const stateLabel = name => isKnockOut
    ? name === "knockout_triggered" ? "Barrier touched · C UO knocked out" : "Barrier not touched · C UO survives"
    : name === "barrier_triggered" ? "Barrier triggered · activated Up-and-In" : "Barrier not triggered · only through H";
  const description = isKnockOut
    ? result.kind === "nitro"
      ? "The green path retains the long call only while H was never touched. The red path is the same contract after H has knocked it out; ending below H does not restore it."
      : "The green path includes the long Up-and-Out call. The red path removes it following a touch of H, while the underlying and short vanilla call remain."
    : "The untriggered path is shown only below the up barrier: ending at or above H means the barrier was crossed. Compare the activated Up-and-In structure with the conventional Collar/Fence benchmark, which has the same activated terminal payoff but more short-call premium.";
  return `<section class="embedded-scenarios">
    <div class="embedded-scenario-heading"><div><small>${isKnockOut ? "KNOCK-OUT PATH STATES" : "BARRIER STRUCTURE · VANILLA BENCHMARK"}</small><h3>${isKnockOut ? "A barrier touch changes the payoff" : "Portfolio impact at maturity"}</h3><p>${description}</p></div>
      <div class="quantity-pills">${Object.entries(result.leg_quantities).map(([key,value])=>`<span><b>${quantity(value)}</b>${key.replaceAll("_"," ")}</span>`).join("")}</div></div>
    <article class="embedded-chart-card"><header><span>${result.portfolio_context ? `${result.portfolio_context.actual_allocation_pct.toFixed(2)}% actual portfolio allocation · ${quantity(result.base_share_quantity)} base shares` : "Standalone option position"}</span><strong>One payoff chart, measured in ${isKnockOut && result.kind === "nitro" ? "BRL P&L" : "portfolio bps"}</strong><small>Both paths use the same terminal prices. Terminal range: ${lowMove.toFixed(0)}% to +${highMove.toFixed(0)}% versus spot.</small></header><div class="embedded-canvas"><canvas data-structure-chart="combined"></canvas></div>${spotExplorerMarkup(result)}<p>${isKnockOut ? "The red path is irreversible: crossing H kills the C UO even if the asset finishes below the barrier." : "The dashed vanilla line is higher by the short-call premium sacrificed for the barrier feature. One basis point equals 0.01% of the full portfolio."}</p></article>
    ${renderStaticReplication(result)}
    <div class="embedded-outcomes">${Object.entries(scenario.outcome_summary).map(([name,summary])=>{ const maximumPayoff = summary.maximum_payoff ?? summary.maximum_payoff_in_chart_range; const explanation = summary.upside_explanation ?? summary.description ?? ""; return `<article><small>${stateLabel(name)}</small><strong>${typeof maximumPayoff === "number" ? "R$ "+money(maximumPayoff) : maximumPayoff ?? "—"}</strong><span>Maximum payoff in that path state</span><p>${explanation}</p></article>`; }).join("")}</div>
  </section>`;
}

function spotExplorerMarkup(result) {
  const [low, high] = result.scenario_analysis.scenario_range;
  const spot = result.contract_snapshot.spot;
  return `<section class="spot-explorer" data-spot-explorer>
    <div class="spot-slider-copy"><small>LIVE SPOT REPRICE</small><strong>Spot <output data-spot-output>R$ ${money(spot)}</output></strong><span>Move spot to recalculate premium and Greeks with maturity, volatility and rates held constant.</span></div>
    <input data-spot-slider type="range" min="${low}" max="${high}" value="${spot}" step="${Math.max((high-low)/200,.01)}" aria-label="Exploratory current spot">
    <div class="spot-snapshot" data-spot-snapshot><span>Current package</span><strong>Premium R$ ${money(result.net_option_cost)}</strong><em>Move the slider to reprice.</em></div>
  </section><section class="monitoring-equivalence" data-monitoring-equivalence hidden>
    <div><small>MONITORING EQUIVALENCE</small><strong>Discrete clock ↔ continuous barrier</strong><span>Compare the package PV at the contractual barrier, then solve the more distant continuous barrier producing the same PV.</span></div>
    <label>Discrete observations<select data-discrete-monitoring><option value="daily_close">Daily close</option><option value="weekly">Weekly</option><option value="monthly" selected>Monthly</option><option value="maturity_only">Maturity only</option></select></label>
    <button type="button" class="secondary" data-run-equivalence>Solve matching barrier</button>
    <div class="equivalence-result" data-equivalence-result><span>Run the comparison after pricing the package.</span></div>
  </section>`;
}

function renderSpotSnapshot(host, result) {
  const structure = result.structure_greeks?.barrier_structure || result.structure_greeks?.package_structure || result.structure_greeks?.structure;
  const total = structure?.total || {};
  const legs = structure?.legs || [];
  const baseUnits = structureBaseUnits(result);
  const greekColumns = [["delta","Delta","per base unit"],["gamma","Gamma","position total"],["vega_per_1pct","Vega","per 1 vol pt"],["theta_per_calendar_day","Theta","per day"],["rho_per_1bp","Rho","per bp"]];
  host.innerHTML = `<div class="spot-snapshot-head"><div><span>Package mark at selected spot</span><small>${result.net_option_cost >= 0 ? "Client debit" : "Client credit"}</small></div><strong>R$ ${money(Math.abs(result.net_option_cost))}</strong></div>
    <div class="spot-greek-totals">${greekColumns.map(([key,label,unit])=>`<article><span>${label}</span><strong>${key === "delta" ? deltaValue(total.delta / baseUnits) : greekValue(total[key])}</strong><small>${unit}</small></article>`).join("")}</div>
    ${legs.length ? `<div class="spot-leg-greeks"><div class="spot-leg-header"><span>Signed leg</span><span>Signed unit delta</span><span>Gamma total</span><span>Vega total</span><span>Theta total</span><span>Rho total</span></div>${legs.map(leg=>`<div class="spot-leg-row"><strong>${leg.label}<small>${quantity(leg.signed_quantity)} units</small></strong><span>${deltaValue(leg.unit_greeks?.delta * Math.sign(leg.signed_quantity))}</span><span>${greekValue(leg.contribution?.gamma)}</span><span>${greekValue(leg.contribution?.vega_per_1pct)}</span><span>${greekValue(leg.contribution?.theta_per_calendar_day)}</span><span>${greekValue(leg.contribution?.rho_per_1bp)}</span></div>`).join("")}</div>` : ""}`;
}

function singleBarrierLearningMarkup(result) {
  const contract = result.contract_snapshot, scenario = result.scenario_analysis;
  return `<section class="embedded-scenarios single-barrier-learning">
    <div class="embedded-scenario-heading"><div><small>VALUATION-DATE BARRIER LAB</small><h3>Option value today across spot</h3><p>This is a mark-to-market curve with ${scenario.days_to_expiry} calendar days remaining—not an expiry payoff. Each point is repriced with the original volatility, rates, monitoring and maturity.</p></div><div class="quantity-pills"><span><b>${scenario.days_to_expiry}</b>days to expiry</span><span><b>${quantity(contract.quantity * contract.multiplier)}</b>option units</span><span><b>${contract.behavior.toUpperCase()}</b>${contract.direction} barrier</span></div></div>
    <article class="embedded-chart-card"><header><span>VALUATION ${scenario.valuation_date} · EXPIRY ${scenario.expiration_date}</span><strong data-single-chart-title>Current exotic and vanilla value per option unit</strong><small data-single-chart-subtitle>${contract.option_type.toUpperCase()} · K R$ ${money(contract.strike)} · barrier R$ ${money(contract.barrier)} · ${scenario.paths_used.toLocaleString("pt-BR")} paths per exotic point.</small><div class="curve-time-switch" data-curve-time-switch><button type="button" class="active" data-curve-time="today">Today · ${scenario.days_to_expiry}d left</button><button type="button" data-curve-time="expiry">Expiration payoff</button></div></header><div class="single-barrier-chart-grid"><section><div><strong>Barrier option · price and gamma</strong><small>Price uses the left axis; gamma uses the right axis</small></div><div class="embedded-canvas"><canvas data-single-barrier-chart="exotic"></canvas></div></section><section><div><strong>Equivalent vanilla · price and gamma</strong><small>Independent price and gamma scales for the benchmark</small></div><div class="embedded-canvas"><canvas data-single-barrier-chart="vanilla"></canvas></div></section></div><div class="vanilla-comparison-strip"><div><span>Barrier-option premium</span><strong>R$ ${money(scenario.initial_exotic_premium_per_unit)}</strong></div><div><span>Same vanilla ${contract.option_type}</span><strong>R$ ${money(scenario.initial_vanilla_premium_per_unit)}</strong></div><div class="premium-gap"><span>Premium discount from barrier</span><strong>R$ ${money(scenario.initial_premium_discount_per_unit)}</strong><small>${(scenario.initial_premium_discount_per_unit/scenario.initial_vanilla_premium_per_unit*100).toFixed(1)}% below vanilla</small></div></div>${singleBarrierSpotMarkup(result)}${singleBarrierEquivalenceMarkup()}<p data-single-chart-note>The plots share the same spot range but use independent value scales. Price is read on the left axis and gamma per option unit on the right. Orange diamonds mark interpolated spots where exotic delta changes sign.</p></article>
  </section>`;
}

function singleBarrierSpotMarkup(result) {
  const [low, high] = result.scenario_analysis.scenario_range, spot = result.contract_snapshot.spot;
  return `<section class="spot-explorer" data-barrier-spot-explorer><div class="spot-slider-copy"><small>LIVE OPTION REPRICE</small><strong>Spot <output data-spot-output>R$ ${money(spot)}</output></strong><label class="manual-spot-field"><span>Type exact spot</span><span><b>R$</b><input data-spot-manual type="number" min="0.01" value="${spot}" step="0.01" inputmode="decimal" aria-label="Exact spot price"></span></label><span>Move the slider or type an exact spot to recalculate the unit premium and Greeks with all other contract terms fixed.</span></div><input data-spot-slider type="range" min="${low}" max="${high}" value="${spot}" step="${Math.max((high-low)/200,.01)}"><div class="spot-snapshot" data-spot-snapshot></div></section>`;
}

function singleBarrierEquivalenceMarkup() {
  return `<section class="monitoring-equivalence" data-barrier-equivalence><div><small>MONITORING EQUIVALENCE</small><strong>Discrete clock ↔ continuous barrier</strong><span>Find the more distant continuously monitored barrier that matches the discrete option premium.</span></div><label>Discrete observations<select data-discrete-monitoring><option value="daily_close">Daily close</option><option value="weekly">Weekly</option><option value="monthly" selected>Monthly</option><option value="maturity_only">Maturity only</option></select></label><button type="button" class="secondary" data-run-equivalence>Solve matching barrier</button><div class="equivalence-result" data-equivalence-result><span>Run the comparison for this option.</span></div></section>`;
}

function renderSingleBarrierSnapshot(host, result) {
  const exotic = result.greeks || {}, vanilla = result.vanilla_greeks || {};
  const rows = [["delta","Delta","unit delta"],["gamma","Gamma","per R$1²"],["vega_per_1pct","Vega","per 1 vol pt"],["theta_per_calendar_day","Theta","per day"],["rho_per_1bp","Rho","per bp"]];
  host.innerHTML = `<div class="live-compare-premiums"><div><span>Barrier option / unit</span><strong>R$ ${money(result.premium_per_unit)}</strong></div><div><span>Equivalent vanilla / unit</span><strong>R$ ${money(result.vanilla_equivalent_price)}</strong></div><div><span>Premium difference</span><strong>R$ ${money(result.vanilla_equivalent_price-result.premium_per_unit)}</strong></div></div><div class="live-greek-compare"><div class="live-greek-head"><span>Greek per option unit</span><span>Barrier option</span><span>Vanilla</span><span>Exotic − vanilla</span></div>${rows.map(([key,label,unit])=>`<div><strong>${label}<small>${unit}</small></strong><span>${key==="delta"?deltaValue(exotic[key]):greekValue(exotic[key])}</span><span>${key==="delta"?deltaValue(vanilla[key]):greekValue(vanilla[key])}</span><span>${greekValue(exotic[key]-vanilla[key])}</span></div>`).join("")}</div>`;
}

function drawSingleBarrierLearning(target, result) {
  const exoticCanvas = $("[data-single-barrier-chart='exotic']", target), vanillaCanvas = $("[data-single-barrier-chart='vanilla']", target), scenario = result.scenario_analysis;
  if (!exoticCanvas || !vanillaCanvas || !scenario) return;
  const ordered = [["pre_barrier",scenario.states.pre_barrier],["post_trigger",scenario.states.post_trigger]];
  const datasets = ordered.map(([name,rows],index)=>({label:index ? "Exotic · post-trigger" : "Exotic · pre-barrier",curveGroup:"exotic",data:rows.map(row=>({x:row.spot,y:row.unit_model_value,pnl:row.total_pnl_since_trade})),borderColor:index?"#a53838":"#126142",backgroundColor:index?"rgba(165,56,56,.07)":"rgba(18,97,66,.07)",borderDash:index?[8,5]:[],borderWidth:3,pointRadius:0,tension:.14,spanGaps:false}));
  const exoticGamma = ordered.map(([name,rows],index)=>({label:index ? "Gamma · post-trigger" : "Gamma · pre-barrier",curveGroup:"exoticGamma",data:rows.map(row=>({x:row.spot,y:row.local_gamma,pnl:null})),yAxisID:"yGamma",borderColor:index?"#d97706":"#2276a5",borderDash:index?[7,4]:[2,3],borderWidth:2,pointRadius:0,tension:.12,spanGaps:false}));
  const vanillaRows = [...scenario.states.pre_barrier,...scenario.states.post_trigger].sort((a,b)=>a.spot-b.spot);
  datasets.push({label:`Vanilla ${result.contract_snapshot.option_type}`,curveGroup:"vanilla",data:vanillaRows.map(row=>({x:row.spot,y:row.vanilla_unit_value,pnl:null})),borderColor:"#6f42c1",borderDash:[3,3],borderWidth:2.4,pointRadius:0,tension:.14});
  const vanillaGamma = {label:"Vanilla gamma",curveGroup:"vanillaGamma",data:vanillaRows.map(row=>({x:row.spot,y:row.vanilla_local_gamma,pnl:null})),yAxisID:"yGamma",borderColor:"#d97706",borderWidth:2,borderDash:[6,4],pointRadius:0,tension:.12};
  const todayExotic = [...datasets.slice(0,2),...exoticGamma, ...extremaMarkerDatasets([{key:"exotic",label:"Exotic",color:"#126142",points:datasets.slice(0,2).flatMap(dataset=>dataset.data)}], "price"), ...deltaSignFlipDatasets(scenario.delta_sign_flips)];
  const todayVanilla = [datasets[2],vanillaGamma, ...extremaMarkerDatasets([{key:"vanilla",label:"Vanilla",color:"#6f42c1",points:datasets[2].data}], "price")];
  const groupedLegendClick = (_event,item,legend)=>{const chart=legend.chart,group=chart.data.datasets[item.datasetIndex].curveGroup;if(!group)return;const visible=chart.isDatasetVisible(item.datasetIndex);chart.data.datasets.forEach((dataset,index)=>{if(dataset.curveGroup===group||dataset.markerGroup===group)chart.setDatasetVisibility(index,!visible);});chart.update();};
  const chartOptions = yTitle => ({responsive:true,maintainAspectRatio:false,interaction:{mode:"nearest",intersect:false},plugins:{legend:{position:"bottom",onClick:groupedLegendClick,labels:{usePointStyle:true,pointStyle:"line",filter:(item,data)=>!data.datasets[item.datasetIndex]?.extremaMarker}},referenceLines:{items:[{label:"Current spot",value:result.contract_snapshot.spot,color:"#68736e"},{label:"Strike",value:result.contract_snapshot.strike,color:"#b36b23",offset:12},{label:"Barrier event",value:result.contract_snapshot.barrier,color:"#8d4da8",offset:24}]},tooltip:{callbacks:{title:items=>`Spot today: R$ ${money(items[0].parsed.x)}`,label:item=>item.dataset.yAxisID==="yGamma"?`${item.dataset.label}: ${greekValue(item.parsed.y)} / R$1²`:`${item.dataset.label}: R$ ${money(item.parsed.y)} / unit`,afterLabel:item=>item.raw.pnl==null?"":`P&L since trade: R$ ${money(item.raw.pnl)}`}}},scales:{x:{type:"linear",title:{display:true,text:"Hypothetical underlying spot today (BRL)"},ticks:{callback:value=>`R$ ${Number(value).toFixed(0)}`}},y:{position:"left",title:{display:true,text:yTitle},ticks:{callback:value=>`R$ ${Number(value).toFixed(2)}`}},yGamma:{position:"right",title:{display:true,text:"Gamma per option unit / R$1²"},grid:{drawOnChartArea:false},ticks:{callback:value=>greekValue(value)}}}});
  state.charts.singleBarrierExotic?.destroy(); state.charts.singleBarrierVanilla?.destroy();
  state.charts.singleBarrierExotic = new Chart(exoticCanvas,{type:"line",data:{datasets:todayExotic},options:chartOptions("Barrier option value per unit (BRL)")});
  state.charts.singleBarrierVanilla = new Chart(vanillaCanvas,{type:"line",data:{datasets:todayVanilla},options:chartOptions("Vanilla option value per unit (BRL)")});
  const timeSwitch=$("[data-curve-time-switch]",target),title=$("[data-single-chart-title]",target),subtitle=$("[data-single-chart-subtitle]",target),note=$("[data-single-chart-note]",target);
  timeSwitch.onclick=event=>{
    const button=event.target.closest("button[data-curve-time]"); if(!button)return;
    timeSwitch.querySelectorAll("button").forEach(item=>item.classList.toggle("active",item===button));
    const expiry=button.dataset.curveTime==="expiry";
    if(expiry){
      const expiryStates=scenario.expiry_states;
      const expiryDatasets=[
        {label:"Exotic · barrier not triggered",curveGroup:"exotic",data:expiryStates.barrier_not_triggered.filter(row=>row.state_possible).map(row=>({x:row.terminal_price,y:row.exotic_payoff_per_unit,pnl:row.exotic_pnl_per_unit})),borderColor:"#126142",borderWidth:3,pointRadius:0,tension:0},
        {label:"Exotic · barrier triggered",curveGroup:"exotic",data:expiryStates.barrier_triggered.map(row=>({x:row.terminal_price,y:row.exotic_payoff_per_unit,pnl:row.exotic_pnl_per_unit})),borderColor:"#a53838",borderDash:[8,5],borderWidth:3,pointRadius:0,tension:0},
        {label:`Vanilla ${result.contract_snapshot.option_type} payoff`,curveGroup:"vanilla",data:expiryStates.barrier_triggered.map(row=>({x:row.terminal_price,y:row.vanilla_payoff_per_unit,pnl:row.vanilla_pnl_per_unit})),borderColor:"#6f42c1",borderDash:[3,3],borderWidth:2.4,pointRadius:0,tension:0}
      ];
      state.charts.singleBarrierExotic.data.datasets=[...expiryDatasets.slice(0,2),...extremaMarkerDatasets([{key:"exotic",label:"Exotic",color:"#126142",points:expiryDatasets.slice(0,2).flatMap(dataset=>dataset.data)}],"payoff")];
      state.charts.singleBarrierVanilla.data.datasets=[expiryDatasets[2],...extremaMarkerDatasets([{key:"vanilla",label:"Vanilla",color:"#6f42c1",points:expiryDatasets[2].data}],"payoff")];
      title.textContent="Expiration payoff per option unit";
      subtitle.textContent=`Terminal payoff on ${scenario.expiration_date}; tooltip P&L subtracts the initial exotic or vanilla premium.`;
      note.textContent="At expiration there is no time value. The not-triggered curve is clipped where that state is impossible at the final barrier observation; the triggered curve remains valid after paths that touched and later recovered.";
      [state.charts.singleBarrierExotic,state.charts.singleBarrierVanilla].forEach(chart=>{chart.options.scales.x.title.text="Terminal underlying price (BRL)";chart.options.scales.y.title.text="Expiration payoff per unit (BRL)";chart.options.scales.yGamma.display=false;chart.options.plugins.tooltip.callbacks.title=items=>`Terminal spot: R$ ${money(items[0].parsed.x)}`;});
    }else{
      state.charts.singleBarrierExotic.data.datasets=todayExotic;
      state.charts.singleBarrierVanilla.data.datasets=todayVanilla;
      title.textContent="Current exotic and vanilla value per option unit";
      subtitle.textContent=`${result.contract_snapshot.option_type.toUpperCase()} · K R$ ${money(result.contract_snapshot.strike)} · barrier R$ ${money(result.contract_snapshot.barrier)} · ${scenario.paths_used.toLocaleString("pt-BR")} paths per exotic point.`;
      note.textContent="The plots share the same spot range but use independent value scales. Price is read on the left axis and gamma per option unit on the right. Orange diamonds mark interpolated spots where exotic delta changes sign.";
      [state.charts.singleBarrierExotic,state.charts.singleBarrierVanilla].forEach(chart=>{chart.options.scales.x.title.text="Hypothetical underlying spot today (BRL)";chart.options.scales.yGamma.display=true;chart.options.plugins.tooltip.callbacks.title=items=>`Spot today: R$ ${money(items[0].parsed.x)}`;});
      state.charts.singleBarrierExotic.options.scales.y.title.text="Barrier option value per unit (BRL)";
      state.charts.singleBarrierVanilla.options.scales.y.title.text="Vanilla option value per unit (BRL)";
    }
    state.charts.singleBarrierExotic.update(); state.charts.singleBarrierVanilla.update();
  };
}

function attachSingleBarrierLearning(target, result) {
  const saved=state.barrier, explorer=$("[data-barrier-spot-explorer]",target); if(!saved||!explorer)return;
  const slider=$("[data-spot-slider]",explorer), manual=$("[data-spot-manual]",explorer), output=$("[data-spot-output]",explorer), snapshot=$("[data-spot-snapshot]",explorer); let timer,sequence=0; renderSingleBarrierSnapshot(snapshot,result);
  const repriceSpot=spot=>{if(!Number.isFinite(spot)||spot<=0){manual.setCustomValidity("Enter a spot greater than zero.");manual.reportValidity();return;}manual.setCustomValidity("");manual.value=spot;slider.value=Math.max(Number(slider.min),Math.min(Number(slider.max),spot));output.textContent=`R$ ${money(spot)}`;clearTimeout(timer);timer=setTimeout(async()=>{const id=++sequence,payload={...saved.payload,spot,calculate_greeks:true};if((payload.direction==="up"&&spot>=payload.barrier)||(payload.direction==="down"&&spot<=payload.barrier))payload.barrier_status="triggered";snapshot.classList.add("loading");try{const repriced=await postJSON("/api/v1/barriers/snapshot/",payload);if(id===sequence)renderSingleBarrierSnapshot(snapshot,repriced);}catch(error){if(id===sequence)snapshot.innerHTML=`<span class="error">${errorText(error)}</span>`;}finally{snapshot.classList.remove("loading");}},260);};
  slider.oninput=()=>repriceSpot(Number(slider.value));
  manual.onkeydown=event=>{if(event.key==="Enter"){event.preventDefault();manual.blur();}};
  manual.onchange=()=>repriceSpot(Number(manual.value));
  const lab=$("[data-barrier-equivalence]",target),button=$("[data-run-equivalence]",lab),equivalence=$("[data-equivalence-result]",lab);button.onclick=async()=>{button.disabled=true;button.textContent="Solving…";try{const comparison=await postJSON("/api/v1/barriers/monitoring-equivalence/",{...saved.payload,discrete_monitoring:$("[data-discrete-monitoring]",lab).value});equivalence.innerHTML=`<div><span>Continuous · original barrier</span><strong>R$ ${money(comparison.continuous_price_at_original_barrier)}</strong></div><div><span>${comparison.discrete_monitoring.replaceAll("_"," ")} · original barrier</span><strong>R$ ${money(comparison.discrete_price_at_original_barrier)}</strong></div><div class="equivalent-level"><span>Matching continuous barrier</span><strong>R$ ${money(comparison.equivalent_continuous_barrier)}</strong><em>${comparison.barrier_shift_brl>=0?"+":""}${comparison.barrier_shift_brl.toFixed(2)} BRL · ${Math.abs(comparison.barrier_shift_pct_of_spot).toFixed(2)}% of spot</em></div><div><span>Matching residual</span><strong>R$ ${money(comparison.matching_residual)}</strong></div>`;}catch(error){equivalence.innerHTML=`<span class="error">${errorText(error)}</span>`;}finally{button.disabled=false;button.textContent="Solve matching barrier";}};
}

function attachSpotExplorer(target, result) {
  const explorer = $("[data-spot-explorer]", target);
  const saved = state.packages[result.kind];
  if (!explorer || !saved) return;
  const slider = $("[data-spot-slider]", explorer), output = $("[data-spot-output]", explorer), snapshot = $("[data-spot-snapshot]", explorer);
  const chart = state.charts[`${result.kind}-embedded-combined`];
  let timer, requestNumber = 0;
  renderSpotSnapshot(snapshot, result);
  slider.addEventListener("input", () => {
    const selectedSpot = Number(slider.value);
    output.textContent = `R$ ${money(selectedSpot)}`;
    const referenceItems = chart?.options?.plugins?.referenceLines?.items;
    if (referenceItems) {
      const prior = referenceItems.find(item => item.label === "Selected spot");
      if (prior) prior.value = selectedSpot;
      else referenceItems.push({label:"Selected spot", value:selectedSpot, color:"#db7c26", offset:48});
      chart.update("none");
    }
    snapshot.classList.add("loading");
    snapshot.innerHTML = `<span>Repricing at R$ ${money(selectedSpot)}…</span>`;
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const ownRequest = ++requestNumber;
      const payload = structuredClone(saved.payload);
      payload.barrier_contract.spot = selectedSpot;
      payload.calculate_structure_greeks = true;
      const barrier = Number(payload.barrier_contract.barrier);
      const direction = payload.barrier_contract.direction;
      if ((direction === "up" && selectedSpot >= barrier) || (direction === "down" && selectedSpot <= barrier)) payload.barrier_contract.barrier_status = "triggered";
      try {
        const repriced = await postJSON("/api/v1/packages/snapshot/", payload);
        if (ownRequest !== requestNumber) return;
        renderSpotSnapshot(snapshot, repriced);
        snapshot.classList.remove("loading", "error");
      } catch (error) {
        if (ownRequest !== requestNumber) return;
        snapshot.classList.remove("loading"); snapshot.classList.add("error");
        snapshot.innerHTML = `<span>This spot is outside the valid contractual state.</span><em>${errorText(error)}</em>`;
      }
    }, 260);
  });
}

function attachMonitoringEquivalence(target, result) {
  const lab = $("[data-monitoring-equivalence]", target), saved = state.packages[result.kind];
  if (!lab || !saved) return;
  const supported = new Set(["collar","fence","nitro","double_up_ko","box_ko","bullet","golden_bullet","collar_kiko","fence_kiko","call_kiko"]);
  const contract = saved.payload.barrier_contract;
  if (!supported.has(result.kind) || contract.barrier_status === "triggered" || contract.barrier_status === "not_applicable") return;
  lab.hidden = false;
  const button = $("[data-run-equivalence]", lab), output = $("[data-equivalence-result]", lab);
  button.addEventListener("click", async () => {
    button.disabled = true; button.textContent = "Solving…"; output.innerHTML = "<span>Matching package PV with common random numbers…</span>";
    try {
      const payload = structuredClone(saved.payload);
      payload.discrete_monitoring = $("[data-discrete-monitoring]", lab).value;
      const comparison = await postJSON("/api/v1/packages/monitoring-equivalence/", payload);
      const shiftDirection = comparison.barrier_shift_brl >= 0 ? "higher" : "lower";
      output.innerHTML = `<div><span>Continuous · original barrier</span><strong>R$ ${money(comparison.continuous_price_at_original_barrier)}</strong></div>
        <div><span>${comparison.discrete_monitoring.replaceAll("_"," ")} · original barrier</span><strong>R$ ${money(comparison.discrete_price_at_original_barrier)}</strong></div>
        <div class="equivalent-level"><span>Matching continuous barrier</span><strong>R$ ${money(comparison.equivalent_continuous_barrier)}</strong><em>${Math.abs(comparison.barrier_shift_brl).toFixed(2)} BRL ${shiftDirection} · ${Math.abs(comparison.barrier_shift_pct_of_spot).toFixed(2)}% of spot</em></div>
        <div><span>Matching residual</span><strong>R$ ${money(comparison.matching_residual)}</strong><em>${comparison.paths_used.toLocaleString("pt-BR")} paths · ${comparison.evaluations} evaluations</em></div>`;
    } catch (error) { output.innerHTML = `<span class="error">${errorText(error)}</span>`; }
    finally { button.disabled = false; button.textContent = "Solve matching barrier"; }
  });
}

function drawStructureScenarioCharts(target, result) {
  const scenario = result.scenario_analysis;
  if (!scenario) return;
  if (retailKinds.has(result.kind)) return drawRetailScenarioChart(target, result);
  const isKnockOut = result.kind === "nitro" || result.kind === "double_up_ko";
  const neverTriggered = isKnockOut
    ? scenario.states.knockout_not_triggered.filter(row => row.terminal_price < result.contract_snapshot.barrier)
    : scenario.states.barrier_never_triggered.filter(row => row.terminal_price < result.contract_snapshot.barrier);
  const triggered = isKnockOut ? scenario.states.knockout_triggered : scenario.states.barrier_triggered;
  if (!neverTriggered?.length || !triggered?.length) return;
  const canvas = $('[data-structure-chart="combined"]', target);
  const chartKey = `${result.kind}-embedded-combined`;
  const usesPortfolioBps = Boolean(result.portfolio_context);
  const pnl = row => usesPortfolioBps ? row.total_pnl_bps : row.total_pnl;
  const pnlLabel = value => usesPortfolioBps ? `${value >= 0 ? "+" : ""}${value.toFixed(0)} bps` : `R$ ${money(value)}`;
  const snapshot = result.contract_snapshot;
  const activeLabel = isKnockOut ? "Barrier not touched · long C UO survives" : "Barrier not triggered · valid only through H";
  const changedLabel = isKnockOut ? "Barrier touched · long C UO knocked out" : "Barrier triggered · activated Up-and-In";
  const datasets = [
    {label:activeLabel,data:neverTriggered.map(row=>({x:row.terminal_price,y:pnl(row)})),borderColor:"#126142",backgroundColor:"rgba(18,97,66,.10)",borderWidth:2.6,pointRadius:0,tension:.18},
    {label:changedLabel,data:triggered.map(row=>({x:row.terminal_price,y:pnl(row)})),borderColor:"#a53838",backgroundColor:"rgba(165,56,56,.10)",borderWidth:2.6,pointRadius:0,tension:.18}
  ];
  if (!isKnockOut && typeof result.vanilla_barrier_premium_difference === "number") {
    const vanillaPremiumBps = result.vanilla_barrier_premium_difference / result.portfolio_context.portfolio_value * 10_000;
    datasets.push({label:"Equivalent vanilla structure",data:triggered.map(row=>({x:row.terminal_price,y:row.total_pnl_bps + vanillaPremiumBps})),borderColor:"#6f42c1",borderDash:[6,4],borderWidth:1.8,pointRadius:0,tension:.18});
  }
  if (result.kind !== "nitro" && triggered.some(row => typeof row.underlying_pnl === "number")) {
    datasets.push({label:"Underlying-only P&L",data:triggered.map(row=>({x:row.terminal_price,y:usesPortfolioBps ? row.underlying_pnl_bps : row.underlying_pnl})),borderColor:"#94a39c",borderDash:[5,4],borderWidth:1.4,pointRadius:0});
  }
  state.charts[chartKey]?.destroy();
  state.charts[chartKey] = new Chart(canvas, {type:"line",data:{datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{position:"bottom",labels:{usePointStyle:true,pointStyle:"line",font:{size:9}}},payoffPnl:{datasetIndex:0,checkpoints:7,unit:usesPortfolioBps ? "bps" : "BRL"},referenceLines:{items:[
    {label:"Spot",value:snapshot.spot,color:"#68736e"},{label:isKnockOut ? "K1" : "Call K",value:snapshot.up_out_call_strike ?? snapshot.call_strike,color:"#b36b23",offset:12},
    ...(snapshot.short_vanilla_call_strike != null ? [{label:"K2",value:snapshot.short_vanilla_call_strike,color:"#126142",offset:24}] : []),
    {label:"Barrier H",value:snapshot.barrier,color:"#8d4da8",offset:36}
  ]},tooltip:{callbacks:{title:items=>"Terminal underlying: R$ "+money(items[0].parsed.x),label:item=>item.dataset.label+": "+pnlLabel(item.parsed.y)}}},scales:{x:{type:"linear",title:{display:true,text:"Terminal underlying price (BRL)"},ticks:{callback:value=>"R$ "+Number(value).toFixed(0)}},y:{title:{display:true,text:usesPortfolioBps ? "P&L impact (bps of portfolio)" : "P&L (BRL)"},ticks:{callback:value=>usesPortfolioBps ? Number(value).toFixed(0)+" bps" : "R$ "+Number(value).toFixed(0)}}}}});
}

function drawRetailScenarioChart(target, result) {
  const scenario = result.scenario_analysis;
  const canvas = $('[data-structure-chart="combined"]', target);
  if (!canvas) return;
  const snapshot = result.contract_snapshot || {};
  const lowerBarrier = snapshot.lower_barrier ?? snapshot.down_barrier ?? (result.kind === "box_ko" || ["bullet", "bullet_plus", "golden_bullet"].includes(result.kind) ? snapshot.barrier : null);
  const upperBarrier = snapshot.upper_barrier ?? snapshot.up_out_barrier ?? (["collar_kiko", "fence_kiko", "call_kiko", "bullet_plus"].includes(result.kind) ? snapshot.barrier : null);
  const isBrl = scenario.chart_unit === "BRL";
  const palette = ["#126142", "#188a5e", "#a53838", "#b65b45", "#6f42c1", "#8b6b25"];
  const stateIsSurvival = name => /not_triggered|surviv|unbreached|alive|before/i.test(name);
  const terminalValid = (name, row) => {
    const lowerSurvives = lowerBarrier != null && /lower.*(not_triggered|surviv|unbreached|alive)|down.*(not_triggered|surviv|unbreached|alive)/i.test(name);
    const upperSurvives = upperBarrier != null && /upper.*(not_triggered|surviv|unbreached|alive)|up.*(not_triggered|surviv|unbreached|alive)|before/i.test(name);
    return (!lowerSurvives || row.terminal_price > lowerBarrier) && (!upperSurvives || row.terminal_price < upperBarrier);
  };
  const stateEntries = Object.entries(scenario.states || {});
  const legNames = [...new Set(stateEntries.flatMap(([, rows]) => rows.flatMap(row => Object.keys(row.leg_payoffs || {}))))];
  const includedLegs = new Set(legNames);
  const rowValue = row => {
    const excludedPayoff = Object.entries(row.leg_payoffs || {}).reduce((sum, [leg, payoff]) => sum + (includedLegs.has(leg) ? 0 : payoff), 0);
    return isBrl ? row.total_pnl - excludedPayoff : row.total_pnl_bps - excludedPayoff / result.portfolio_context.portfolio_value * 10_000;
  };
  const datasets = stateEntries.map(([name, rows], index) => {
    const survival = stateIsSurvival(name);
    const validRows = rows.filter(row => terminalValid(name, row));
    const points = validRows.map(row => ({x:row.terminal_price, y:rowValue(row)}));
    return {label:name.replaceAll("_", " "), data:points, sourceRows:validRows, borderColor:palette[index % palette.length], backgroundColor:"transparent", borderWidth:2.35, pointRadius:0, tension:.16, borderDash:survival ? [] : [6, 3]};
  }).filter(dataset => dataset.data.length);
  if (!datasets.length) return;
  const chartKey = `${result.kind}-embedded-combined`;
  const pnlLabel = value => isBrl ? `R$ ${money(value)}` : `${value >= 0 ? "+" : ""}${value.toFixed(0)} bps`;
  state.charts[chartKey]?.destroy();
  state.charts[chartKey] = new Chart(canvas, {type:"line", data:{datasets}, options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},plugins:{legend:{position:"bottom",labels:{usePointStyle:true,pointStyle:"line",font:{size:9}}},payoffPnl:{datasetIndex:0,checkpoints:7,unit:isBrl ? "BRL" : "bps"},referenceLines:{items:[
    {label:"Spot",value:snapshot.spot,color:"#68736e"},
    ...(snapshot.strike != null ? [{label:"K",value:snapshot.strike,color:"#b36b23",offset:12}] : []),
    ...(snapshot.forward_strike != null ? [{label:"Kf",value:snapshot.forward_strike,color:"#b36b23",offset:12}] : []),
    ...(snapshot.up_out_call_strike != null ? [{label:"K1",value:snapshot.up_out_call_strike,color:"#b36b23",offset:12}] : []),
    ...(snapshot.short_up_in_call_strike != null ? [{label:"K2",value:snapshot.short_up_in_call_strike,color:"#126142",offset:24}] : []),
    ...(snapshot.bullet_level != null ? [{label:"B",value:snapshot.bullet_level,color:"#b36b23",offset:12}] : []),
    ...(lowerBarrier != null ? [{label:"Lower B",value:lowerBarrier,color:"#a53838",offset:24}] : []),
    ...(upperBarrier != null ? [{label:"Upper H",value:upperBarrier,color:"#8d4da8",offset:36}] : [])
  ]},tooltip:{callbacks:{title:items=>"Terminal underlying: R$ "+money(items[0].parsed.x),label:item=>item.dataset.label+": "+pnlLabel(item.parsed.y)}}},scales:{x:{type:"linear",title:{display:true,text:"Terminal underlying price (BRL)"},ticks:{callback:value=>"R$ "+Number(value).toFixed(0)}},y:{title:{display:true,text:isBrl ? "P&L (BRL)" : "P&L impact (bps of portfolio)"},ticks:{callback:value=>isBrl ? "R$ "+Number(value).toFixed(0) : Number(value).toFixed(0)+" bps"}}}}});
  const toggleHost = $("[data-leg-toggles]", target);
  if (toggleHost && legNames.length > 1) {
    toggleHost.innerHTML = `<span>Included legs</span>${legNames.map(leg => `<button type="button" class="active" data-leg="${leg}">${leg.replaceAll("_", " ")}</button>`).join("")}`;
    toggleHost.addEventListener("click", event => {
      const button = event.target.closest("button[data-leg]");
      if (!button) return;
      const leg = button.dataset.leg;
      includedLegs.has(leg) ? includedLegs.delete(leg) : includedLegs.add(leg);
      button.classList.toggle("active", includedLegs.has(leg));
      button.setAttribute("aria-pressed", String(includedLegs.has(leg)));
      state.charts[chartKey].data.datasets.forEach(dataset => {
        dataset.data = dataset.sourceRows.map(row => ({x:row.terminal_price, y:rowValue(row)}));
      });
      state.charts[chartKey].update();
    });
    toggleHost.querySelectorAll("button").forEach(button => button.setAttribute("aria-pressed", "true"));
  }
}

function renderResult(target, result) {
  const preferred = ["model_price","premium_per_unit","total_premium","vanilla_equivalent_price","net_option_cost","protective_put_premium","long_put_premium","short_put_premium","up_in_call_premium","equivalent_vanilla_call_premium","vanilla_barrier_premium_difference","barrier_hit_probability","probability_ending_itm","probability_active_at_expiry","standard_error","residual","solution"];
  const packageKeys = new Set(["net_option_cost","protective_put_premium","long_put_premium","short_put_premium","up_in_call_premium","equivalent_vanilla_call_premium","vanilla_barrier_premium_difference"]);
  const entries = preferred.filter(key => key in result && !(result.kind && packageKeys.has(key))).map(key => [key, result[key]]);
  const warnings = result.warnings || [];
  target.innerHTML = `${result.kind ? renderPackageEconomics(result) + renderStructureGreeks(result) + structureScenarioMarkup(result) : result.scenario_analysis ? singleBarrierLearningMarkup(result) : ""}<div class="metrics">${entries.map(([key,value]) => {
    const view = metricPresentation(key, value);
    return `<div class="metric ${view.tone}"><small>${view.label}</small><strong>${money(view.value)}</strong>${view.note ? `<em>${view.note}</em>` : ""}</div>`;
  }).join("")}</div>
    ${warnings.length ? `<ul class="warnings">${warnings.map(x => `<li>${x}</li>`).join("")}</ul>` : ""}
    <div class="result-actions"><button class="secondary copy-result">Copy JSON</button><button class="secondary export-result">Export JSON</button></div>`;
  if (result.kind) drawStructureScenarioCharts(target, result);
  if (result.kind) attachSpotExplorer(target, result);
  if (result.kind) attachMonitoringEquivalence(target, result);
  if (!result.kind && result.scenario_analysis) { drawSingleBarrierLearning(target,result); attachSingleBarrierLearning(target,result); }
  $(".copy-result", target).onclick = () => navigator.clipboard.writeText(JSON.stringify(result, null, 2));
  $(".export-result", target).onclick = () => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type:"application/json"}));
    link.download = `barrier-study-${result.calculation_id || "result"}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
  };
}

$("#barrier-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget, button = $('button[type="submit"]', form), errors = $(".form-errors", form);
  errors.textContent = ""; button.disabled = true; button.textContent = "Simulating paths…";
  try {
    const payload = {...normalizeContract(formObject(form)), calculate_greeks:true};
    const result = await postJSON(form.dataset.endpoint, payload);
    state.barrier = {payload,result};
    renderResult($("#barrier .result-shell"), result);
  } catch (error) { errors.textContent = errorText(error); }
  finally { button.disabled = false; button.textContent = "Run barrier study"; }
});

$$(".package-form").forEach(form => form.addEventListener("submit", async event => {
  event.preventDefault();
  const kind = form.dataset.kind, errors = $(".form-errors", form), button = $(".primary", form);
  const values = formObject(form);
  const payload = {...values, kind, calculate_structure_greeks:true, barrier_contract: normalizePackageContract(values, kind)};
  errors.textContent = ""; button.disabled = true; button.textContent = "Pricing package…";
  try {
    const result = await postJSON("/api/v1/packages/price/", payload);
    state.packages[kind] = {payload, result};
    renderResult(form.parentElement.querySelector(".result-shell"), result);
  } catch (error) { errors.textContent = errorText(error); }
  finally { button.disabled = false; button.textContent = "Price & decompose"; }
}));

$(".solver-host").innerHTML = `<form id="solver-form">
  <div class="solver-row">
    <label>Structure<select name="kind"><option value="collar">Collar</option><option value="fence">Fence</option></select></label>
    <label>Solve for<select name="solve_for"></select></label>
    <label>Lower bound<input name="search_lower" type="number" step=".01" value="70"></label>
    <label>Upper bound<input name="search_upper" type="number" step=".01" value="100"></label>
    <label>Cost tolerance<input name="zero_cost_tolerance" type="number" step=".001" value=".01"></label>
    <button class="primary">Solve</button>
  </div><div class="form-errors"></div>
</form><div class="result-shell"></div>`;

function solverOptions() {
  const kind = $('#solver-form [name="kind"]').value;
  const options = kind === "collar" ? ["protective_put_strike","call_strike","barrier"] : ["lower_put_strike","upper_put_strike","call_strike","barrier"];
  $('#solver-form [name="solve_for"]').innerHTML = options.map(x => `<option>${x}</option>`).join("");
}
$('#solver-form [name="kind"]').addEventListener("change", solverOptions); solverOptions();
$("#solver-form").addEventListener("submit", async event => {
  event.preventDefault();
  const controls = formObject(event.currentTarget), saved = state.packages[controls.kind];
  const errors = $(".form-errors", event.currentTarget);
  if (!saved) { errors.textContent = `Price a ${controls.kind} first; its current template inputs define the solver contract.`; return; }
  try {
    const payload = {...saved.payload, ...controls};
    const result = await postJSON("/api/v1/solvers/zero-cost/", payload);
    renderResult($(".solver-host .result-shell"), result);
  } catch (error) { errors.textContent = errorText(error); }
});

$("#run-scenarios").addEventListener("click", async () => {
  const kind = $("#scenario-kind").value, saved = state.packages[kind], errors = $(".scenario-error");
  if (!saved) { errors.textContent = `Price a ${kind} first so scenarios can use its current legs and initial premium.`; return; }
  errors.textContent = "";
  try {
    const result = await postJSON("/api/v1/scenarios/", saved.payload);
    updateScenarioSnapshot(saved, result);
    renderOutcomeSummary(result);
    drawEducationalScenario("never", result.states.barrier_never_triggered, saved, "Barrier never triggered · short Up-and-In call inactive");
    drawEducationalScenario("triggered", result.states.barrier_triggered, saved, "Barrier triggered · short Up-and-In call active");
  } catch (error) { errors.textContent = errorText(error); }
});

function drawScenario(name, rows) {
  state.charts[name]?.destroy();
  state.charts[name] = new Chart($(`#chart-${name}`), {type:"line",data:{labels:rows.map(x=>money(x.terminal_price)),datasets:[
    {label:"Total P&L",data:rows.map(x=>x.total_pnl),borderColor:"#126142",backgroundColor:"#12614222",fill:true,tension:.15},
    {label:"Underlying P&L",data:rows.map(x=>x.underlying_pnl),borderColor:"#8b9690",borderDash:[5,4],pointRadius:0}
  ]},options:{responsive:true,interaction:{mode:"index",intersect:false},plugins:{legend:{position:"bottom"}},scales:{x:{title:{display:true,text:"Terminal price"}},y:{title:{display:true,text:"P&L"}}}}});
}

function updateScenarioSnapshot(saved, result) {
  const contract = saved.payload.barrier_contract;
  const values = [
    $("#underlying").value.trim() || "Manual BRL underlying",
    "R$ " + money(contract.spot), "R$ " + money(contract.strike),
    "R$ " + money(contract.barrier), "R$ " + money(result.initial_investment)
  ];
  $$("#scenario-snapshot strong").forEach((element, index) => element.textContent = values[index]);
}

function signedMultiple(value) {
  return typeof value === "number" ? value.toFixed(1) + "×" : "Not meaningful";
}

function renderOutcomeSummary(result) {
  const labels = {
    barrier_never_triggered: "Barrier never triggered",
    barrier_triggered: "Barrier triggered"
  };
  $("#scenario-outcomes").innerHTML = Object.entries(result.outcome_summary).map(([stateName, summary]) =>
    '<article><div class="outcome-title"><span>' + labels[stateName] + '</span><strong>' +
    (typeof summary.maximum_payoff === "number" ? "R$ " + money(summary.maximum_payoff) : summary.maximum_payoff) +
    '</strong><small>Maximum payoff</small></div><div class="outcome-metrics">' +
    '<div><small>Best P&L in chart</small><strong>R$ ' + money(summary.best_pnl_in_chart_range) + '</strong><em>' + signedMultiple(summary.best_pnl_to_net_premium_multiple) + ' net premium</em></div>' +
    '<div><small>Worst P&L in chart</small><strong>R$ ' + money(summary.worst_pnl_in_chart_range) + '</strong><em>' + signedMultiple(summary.worst_pnl_to_net_premium_multiple) + ' net premium</em></div>' +
    '<div><small>If the underlying ends at zero</small><strong>R$ ' + money(summary.downside_pnl_at_zero) + '</strong><em>Total position P&L</em></div>' +
    '</div><p>' + summary.upside_explanation + '</p><footer>' + summary.multiple_note + '</footer></article>'
  ).join("");
}

function synchronizedScenarioHover(_event, elements, sourceName) {
  if (!elements.length) return;
  const index = elements[0].index;
  Object.entries(state.charts).forEach(([name, chart]) => {
    const active = chart.data.datasets.map((_, datasetIndex) => ({datasetIndex, index}));
    chart.setActiveElements(active);
    if (name !== sourceName) chart.tooltip.setActiveElements(active, {
      x: chart.scales.x.getPixelForValue(chart.data.datasets[0].data[index].x), y: chart.chartArea.top
    });
    chart.update("none");
  });
}

function drawEducationalScenario(name, rows, saved, pathDescription) {
  state.charts[name]?.destroy();
  const contract = saved.payload.barrier_contract;
  const security = $("#underlying").value.trim() || "Underlying";
  const legNames = Object.keys(rows[0].leg_payoffs).filter(key => key !== "underlying");
  const colors = ["#6f42c1", "#d97706", "#0d6efd"];
  const pointData = getter => rows.map(row => ({x: row.terminal_price, y: getter(row)}));
  const datasets = [
    {label:"Total structured-position P&L",data:pointData(row=>row.total_pnl),borderColor:"#126142",backgroundColor:"rgba(18,97,66,.18)",fill:{target:"origin",above:"rgba(25,135,84,.20)",below:"rgba(220,53,69,.18)"},tension:.22,borderWidth:3,pointRadius:2,pointHoverRadius:5,order:1},
    {label:"Underlying P&L",data:pointData(row=>row.underlying_pnl),borderColor:"#8b9690",borderDash:[6,4],borderWidth:1.5,pointRadius:0,fill:false,order:2},
    ...legNames.map((leg,index)=>({label:leg.replaceAll("_"," "),data:pointData(row=>row.leg_payoffs[leg]),borderColor:colors[index%colors.length],borderWidth:1.5,pointRadius:0,fill:false,hidden:true,order:3}))
  ];
  state.charts[name] = new Chart($("#chart-" + name), {
    type:"line",data:{datasets},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},animation:{duration:500},onHover:(event,elements)=>synchronizedScenarioHover(event,elements,name),
      plugins:{
        legend:{position:"top",align:"start",labels:{usePointStyle:true,pointStyle:"line",boxWidth:26,padding:14,font:{size:9}}},
        title:{display:true,text:security+" maturity payoff · spot used R$ "+money(contract.spot),align:"start",color:"#31443b",font:{size:12,weight:"600"},padding:{bottom:14}},
        tooltip:{backgroundColor:"rgba(20,31,26,.94)",padding:12,cornerRadius:7,titleFont:{family:"Poppins",size:11},bodyFont:{family:"Poppins",size:10},callbacks:{title:items=>security+" terminal price: R$ "+money(items[0].parsed.x),label:context=>context.dataset.label+": R$ "+money(context.parsed.y),footer:()=>pathDescription}},
        referenceLines:{items:[{label:"Spot",value:contract.spot,color:"#126142",dash:[2,3]},{label:"Call K",value:contract.strike,color:"#6f42c1",offset:12},{label:"Barrier H",value:contract.barrier,color:"#d97706",offset:24}]}
      },
      scales:{
        x:{type:"linear",title:{display:true,text:security+" terminal price (BRL)",color:"#48534e",font:{size:10,weight:"600"}},grid:{color:"rgba(90,110,100,.09)"},ticks:{callback:value=>"R$ "+Number(value).toFixed(0),font:{size:9}}},
        y:{title:{display:true,text:"Total P&L (BRL)",color:"#48534e",font:{size:10,weight:"600"}},grid:{color:context=>context.tick.value===0?"rgba(23,33,29,.45)":"rgba(90,110,100,.09)",lineWidth:context=>context.tick.value===0?1.5:1},ticks:{callback:value=>"R$ "+Number(value).toFixed(0),font:{size:9}}}
      }
    }
  });
}

$("#load-market").addEventListener("click", async event => {
  const button = event.currentTarget, message = $("#market-state"), underlying = $("#underlying").value.trim();
  button.disabled = true; button.textContent = "Loading Yahoo price…";
  try {
    const response = await fetch(`/api/v1/market-data/options-chain/?underlying=${encodeURIComponent(underlying)}`);
    const body = await response.json();
    if (!response.ok) throw body.error;
    state.market = body.data;
    $$(".spot-input").forEach(x => x.value = state.market.underlying_px_last);
    $$(".pricing-form, .package-form").forEach(form =>
      configureMoneynessSelectors(form, state.market.underlying_px_last));
    message.innerHTML = `<span>Yahoo last price loaded</span><small>${state.market.yahoo_symbol} · only spot was updated</small>`;
  } catch (error) {
    message.innerHTML = `<span>Manual market data</span><small>${errorText(error)}</small>`;
  } finally { button.disabled = false; button.textContent = "Load latest price"; }
});

async function loadHistory() {
  const host = $("#history-list"); host.innerHTML = '<div class="empty-result">Loading…</div>';
  try {
    const response = await fetch("/api/v1/calculations/?limit=100"), body = await response.json();
    host.innerHTML = body.data.length ? body.data.map(row => `<article class="history-row"><strong>#${row.id}</strong><span>${row.kind}<br><small>${new Date(row.created_at).toLocaleString()}</small></span><code>${JSON.stringify(row.request)}</code><button class="secondary" data-history="${row.id}">Copy</button></article>`).join("") : '<div class="empty-result">No saved calculations yet.</div>';
    $$("[data-history]", host).forEach((button, i) => button.onclick = () => navigator.clipboard.writeText(JSON.stringify(body.data[i], null, 2)));
  } catch (error) { host.innerHTML = `<div class="form-errors">${errorText(error)}</div>`; }
}
$("#refresh-history").addEventListener("click", loadHistory);

// Dealer & Risk Lab: these views only present backend-calculated learning payloads.
const learningState = { calculations: [], selectedId: null };
const learningKinds = { paths: "paths", quote: "quote", volatility: "volatility", hedge: "hedge", attribution: "attribution" };

function learningNumber(value, fallback = "—") {
  return typeof value === "number" && Number.isFinite(value) ? money(value) : fallback;
}

function learningValue(row, keys, fallback = null) {
  for (const key of keys) if (row && row[key] != null) return row[key];
  return fallback;
}

function learningRows(result, keys) {
  for (const key of keys) if (Array.isArray(result?.[key])) return result[key];
  return [];
}

function learningSetMessage(target, message, error = false) {
  const host = $(target);
  if (host) host.textContent = message;
  if (host) host.classList.toggle("error", error);
}

async function getLearningJSON(url) {
  const response = await fetch(url);
  const body = await response.json();
  if (!response.ok) throw body.error || {message: `HTTP ${response.status}`};
  return body.data || body;
}

function learningUrl(tool, params = {}) {
  const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== "" && value != null));
  const suffix = query.toString();
  return `/api/v1/calculations/${learningState.selectedId}/learning/${learningKinds[tool]}/` + (suffix ? `?${suffix}` : "");
}

async function loadLearningCalculations() {
  const select = $("#learning-calculation");
  if (!select) return;
  select.disabled = true;
  try {
    const data = await getLearningJSON("/api/v1/calculations/?limit=100");
    learningState.calculations = data.data || data;
    const previous = learningState.selectedId || select.value;
    select.innerHTML = `<option value="">Choose a saved calculation…</option>${learningState.calculations.map(row => `<option value="${row.id}">#${row.id} · ${row.kind} · ${new Date(row.created_at).toLocaleDateString()}</option>`).join("")}`;
    if (previous && learningState.calculations.some(row => String(row.id) === String(previous))) {
      select.value = previous;
      learningState.selectedId = Number(previous);
    }
  } catch (error) {
    select.innerHTML = '<option value="">Unable to load saved calculations</option>';
    learningSetMessage("#path-insight", errorText(error), true);
  } finally { select.disabled = false; }
}

function requireLearningCalculation() {
  if (learningState.selectedId) return true;
  learningSetMessage("#path-insight", "Choose a saved calculation first. The lab deliberately reuses a priced trade instead of recalculating it in the browser.", true);
  return false;
}

function learningChart(key, canvasSelector, config) {
  state.charts[key]?.destroy();
  state.charts[key] = new Chart($(canvasSelector), config);
}

function pathPoints(result) {
  const selected = result.selected_path || result.path || result;
  return {selected, points: learningRows(selected, ["points", "observations", "timeline", "path"]) };
}

function renderPathExplorer(payload) {
  const result = payload.result || payload;
  const {selected, points} = pathPoints(result);
  const choices = learningRows(result, ["available_paths", "sample_paths", "paths"]);
  const select = $("#learning-path-index"), hedgeSelect = $("#hedge-path-index");
  const options = choices.length ? choices.map((path, index) => ({value: learningValue(path, ["path_index", "index", "id"], index), label: learningValue(path, ["label", "description", "state"], `Path ${index + 1}`)})) : [{value: learningValue(selected, ["path_index", "index"], 0), label: "Selected path"}];
  [select, hedgeSelect].forEach(control => {
    if (!control) return;
    const existing = control.value;
    control.innerHTML = options.map(option => `<option value="${option.value}">${option.label}</option>`).join("");
    if ([...control.options].some(option => option.value === existing)) control.value = existing;
  });
  const barrier = learningValue(selected, ["barrier", "barrier_level"], learningValue(result, ["barrier", "barrier_level"]));
  const data = points.map((point, index) => ({x: learningValue(point, ["step", "index", "time_index"], index), y: learningValue(point, ["spot", "price", "underlying"])})).filter(point => typeof point.y === "number");
  const bridges = points.map((point, index) => ({point, index})).filter(({point}) => point.bridge_crossing || point.bridge_hit).map(({point, index}) => ({x: learningValue(point, ["step", "index", "time_index"], index), y: learningValue(point, ["spot", "price", "underlying"])}));
  const hits = points.map((point, index) => ({point, index})).filter(({point}) => point.endpoint_hit || point.barrier_hit || point.event === "barrier_hit").map(({point, index}) => ({x: learningValue(point, ["step", "index", "time_index"], index), y: learningValue(point, ["spot", "price", "underlying"])}));
  learningChart("learning-path", "#learning-path-chart", {type:"line",data:{datasets:[
    {label:"Selected risk-neutral path",data,borderColor:"#126142",backgroundColor:"rgba(18,97,66,.10)",fill:true,borderWidth:2.5,pointRadius:0,tension:.12},
    {label:"Barrier touch at endpoint",data:hits,showLine:false,pointRadius:5,pointStyle:"rectRot",backgroundColor:"#a53838",borderColor:"#a53838"},
    {label:"Brownian-bridge crossing",data:bridges,showLine:false,pointRadius:5,pointStyle:"triangle",backgroundColor:"#8d4da8",borderColor:"#8d4da8"}
  ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:"bottom",labels:{usePointStyle:true,font:{size:9}}},referenceLines:{items:typeof barrier === "number" ? [{label:"Barrier",value:barrier,color:"#a53838"}] : []},tooltip:{callbacks:{title:items => `Observation ${items[0].parsed.x}`,label:item => `${item.dataset.label}: R$ ${learningNumber(item.parsed.y)}`}}},scales:{x:{type:"linear",title:{display:true,text:"Observation step"}},y:{title:{display:true,text:"Underlying price (BRL/share)"},ticks:{callback:value => `R$ ${value}`}}}}});
  const provenance = payload.inputs?.provenance || result.provenance || payload.provenance || {};
  const hit = learningValue(selected, ["first_hit", "first_hit_index", "first_barrier_event"]);
  const bridge = learningValue(selected, ["first_bridge", "first_bridge_index"]);
  learningSetMessage("#path-insight", `Path #${learningValue(selected, ["path_index", "index"], "—")} · seed ${learningValue(provenance, ["seed"], "saved")}; ${hit != null ? `first endpoint touch: observation ${hit}.` : "No endpoint barrier touch."} ${bridge != null ? `Brownian bridge inferred crossing near observation ${bridge}.` : "No bridge crossing inferred."}`);
  $("#path-metrics").innerHTML = learningMetricCards([
    ["Terminal payoff", learningValue(selected, ["terminal_payoff", "payoff", "discounted_payoff"])],
    ["Terminal spot", learningValue(selected, ["terminal_spot", "terminal_price", "ending_spot", "final_spot"])],
    ["Barrier state", learningValue(selected, ["barrier_state", "state", "active_at_expiry"], "Not reported")],
    ["Monitoring", learningValue(provenance, ["monitoring"], "Saved contract")]
  ]);
  $("#path-table").innerHTML = points.map((point, index) => `<tr><td>${learningValue(point, ["step", "index", "time_index"], index)}</td><td>${learningValue(point, ["date", "observation_date"], "—")}</td><td>R$ ${learningNumber(learningValue(point, ["spot", "price", "underlying"]))}</td><td>${learningValue(point, ["barrier_state"], point.endpoint_hit ? "Endpoint touch" : "—")}</td><td>${point.bridge_crossing || point.bridge_hit ? "Crossing inferred" : "—"}</td></tr>`).join("") || "<tr><td colspan=\"5\">The backend did not return path observations for this calculation.</td></tr>";
}

function learningMetricCards(entries) {
  return entries.map(([label, value]) => `<article><small>${label}</small><strong>${typeof value === "number" ? `R$ ${learningNumber(value)}` : value ?? "—"}</strong></article>`).join("");
}

function waterfallMarkup(rows, finalLabel, finalValue) {
  const rendered = rows.map(row => ({label: learningValue(row, ["label", "name", "component"], "Adjustment"), value: learningValue(row, ["value", "amount", "pnl"], 0), kind: learningValue(row, ["kind", "type"], "neutral")}));
  return `<div class="waterfall-rows">${rendered.map(row => `<div class="waterfall-row ${row.value >= 0 ? "positive" : "negative"}"><span>${row.label}</span><b>${row.value >= 0 ? "+" : "−"} R$ ${learningNumber(Math.abs(row.value))}</b></div>`).join("")}<div class="waterfall-total"><span>${finalLabel}</span><strong>R$ ${learningNumber(finalValue)}</strong></div></div>`;
}

function renderQuote(payload) {
  const result = payload.result || payload;
  const clean = learningValue(result, ["clean_model_pv", "clean_value", "model_value"]);
  const rows = learningRows(result, ["items", "waterfall", "adjustments"]);
  const quote = learningValue(result, ["client_offer", "client_quote", "quote", "client_debit"]);
  $("#quote-waterfall").innerHTML = waterfallMarkup(rows.length ? rows : [{label:"Clean model PV",value:clean}], "Client offer / debit", quote);
  $("#quote-metrics").innerHTML = learningMetricCards([["Clean model PV", clean], ["Underlying cash notional", learningValue(result, ["underlying_cash_notional"], "Not part of option quote")], ["Client offer", quote], ["Convention", learningValue(result, ["quote_convention"], "Client debit")]]);
}

function renderVolatility(payload) {
  const result = payload.result || payload;
  const rows = learningRows(result, ["rows", "scenarios", "volatility_rows"]);
  const chartRows = rows.filter(row => typeof learningValue(row, ["dealer", "dealer_volatility", "volatility"]) === "number");
  learningChart("learning-volatility", "#learning-volatility-chart", {type:"bar",data:{labels:chartRows.map(row => learningValue(row, ["label", "scenario"], "Scenario")),datasets:[{label:"Backend structure value",data:chartRows.map(row => learningValue(row, ["model_value", "value", "structure_value"])),backgroundColor:["#94a39c", "#5d806c", "#126142"],borderRadius:5}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:item => `Structure value: R$ ${learningNumber(item.parsed.y)}`}}},scales:{x:{title:{display:true,text:"Volatility perspective"}},y:{title:{display:true,text:"Structure value (BRL)"},ticks:{callback:value => `R$ ${value}`}}}}});
  $("#volatility-table").innerHTML = rows.map(row => { const label = learningValue(row, ["label", "scenario"], "Scenario"); const value = learningPercent(learningValue(row, ["volatility", "dealer", "dealer_volatility"])); return `<tr><td>${label}</td><td>${/historical/i.test(label) ? value : "—"}</td><td>${/market|implied/i.test(label) ? value : "—"}</td><td>${/dealer/i.test(label) ? value : "—"}</td><td>R$ ${learningNumber(learningValue(row, ["model_value", "value", "structure_value"]))}</td></tr>`; }).join("") || "<tr><td colspan=\"5\">No volatility scenarios returned.</td></tr>";
}

function learningPercent(value) { return typeof value === "number" ? `${(value * 100).toFixed(2)}%` : "—"; }

function renderHedge(payload) {
  const result = payload.result || payload;
  const rows = learningRows(result, ["timeline", "rows", "observations"]);
  const summary = result.summary || {};
  learningChart("learning-hedge", "#learning-hedge-chart", {type:"line",data:{labels:rows.map(row => learningValue(row, ["date", "step"], "—")),datasets:[{label:"Structure value",data:rows.map(row => learningValue(row, ["structure_value", "package_value", "value"])),borderColor:"#126142",borderWidth:2.4,tension:.15,yAxisID:"value"},{label:"Cumulative hedge P&L",data:rows.map(row => learningValue(row, ["cumulative_pnl", "hedge_pnl"])),borderColor:"#a53838",borderWidth:2,tension:.15,yAxisID:"value"},{label:"Delta",data:rows.map(row => learningValue(row, ["delta"])),borderColor:"#8d4da8",borderDash:[5,4],borderWidth:1.5,pointRadius:0,yAxisID:"delta"}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:"bottom",labels:{font:{size:9}}}},scales:{value:{type:"linear",position:"left",title:{display:true,text:"BRL"}},delta:{type:"linear",position:"right",title:{display:true,text:"Delta"},grid:{drawOnChartArea:false}},x:{title:{display:true,text:"Rebalance date / step"}}}}});
  $("#hedge-metrics").innerHTML = learningMetricCards([["Hedge error at expiry", learningValue(summary, ["hedge_error_at_expiry", "hedge_error"])], ["Transaction costs", learningValue(summary, ["transaction_costs", "total_transaction_cost"])], ["Rebalance convention", learningValue(payload.inputs || result, ["rebalance_count", "rebalance_steps"], "Saved request")], ["Risk note", "Illustrative dealer short-package hedge"]]);
  $("#hedge-table").innerHTML = rows.map(row => `<tr><td>${learningValue(row, ["date", "step"], "—")}</td><td>R$ ${learningNumber(learningValue(row, ["spot", "price"]))}</td><td>R$ ${learningNumber(learningValue(row, ["structure_value", "package_value", "value"]))}</td><td>${learningValue(row, ["delta"], "—")}</td><td>${learningValue(row, ["hedge_shares", "shares"], "—")}</td><td>${learningValue(row, ["trade_shares", "trade"], "—")}</td><td>R$ ${learningNumber(learningValue(row, ["cumulative_pnl", "hedge_pnl"]))}</td></tr>`).join("") || "<tr><td colspan=\"7\">No hedge timeline returned.</td></tr>";
}

function renderAttribution(payload) {
  const result = payload.result || payload;
  const rows = learningRows(result, ["rows", "waterfall", "attribution"]);
  const totalChange = learningValue(result, ["total_change"]);
  const baseline = rows.find(row => /baseline/i.test(learningValue(row, ["label"], "")));
  $("#attribution-waterfall").innerHTML = waterfallMarkup(rows, "Total value change", totalChange);
  $("#attribution-metrics").innerHTML = learningMetricCards([["Baseline PV", learningValue(baseline, ["value"], "—")], ["Exact revaluation", totalChange], ["Exact residual", learningValue(result, ["exact_residual", "residual", "unexplained"])], ["Attribution order", (learningValue(result, ["attribution_order"], []) || []).join(" → ") || "Backend calculation order"]]);
}

async function runLearningTool(tool) {
  if (!requireLearningCalculation()) return;
  const params = tool === "paths" ? {path_index: $("#learning-path-index").value, path_count: $("#learning-path-count").value, seed: $("#learning-path-seed").value} : tool === "quote" ? {pricing_volatility: $("#quote-pricing-volatility").value, model_reserve_brl: $("#quote-model-reserve").value, hedging_liquidity_reserve_brl: $("#quote-hedging-liquidity").value, dealer_margin_brl: $("#quote-margin").value, quote_side: $("#quote-side").value} : tool === "volatility" ? {historical_volatility: $("#volatility-historical").value, implied_volatility: $("#volatility-implied").value, dealer_volatility: $("#volatility-dealer").value} : tool === "hedge" ? {path_index: $("#hedge-path-index").value, rebalance_count: $("#hedge-rebalance-count").value, transaction_cost_bps: $("#hedge-cost-bps").value} : {spot_change_pct: $("#attribution-spot-pct").value, volatility_change: $("#attribution-vol-shift").value, rate_change: $("#attribution-rate-shift").value, days: $("#attribution-days").value};
  const button = $(`[data-learning-run="${tool}"]`);
  button.disabled = true;
  button.textContent = "Loading…";
  try {
    const payload = await getLearningJSON(learningUrl(tool, params));
    ({paths: renderPathExplorer, quote: renderQuote, volatility: renderVolatility, hedge: renderHedge, attribution: renderAttribution}[tool])(payload);
  } catch (error) {
    learningSetMessage("#path-insight", errorText(error), true);
  } finally { button.disabled = false; button.textContent = ({paths:"Explore path",quote:"Build quote",volatility:"Compare volatility",hedge:"Simulate hedge",attribution:"Attribute P&L"})[tool]; }
}

$$('[data-learning-tool]').forEach(button => button.addEventListener("click", () => {
  $$('[data-learning-tool]').forEach(item => item.classList.toggle("active", item === button));
  $$('[data-learning-panel]').forEach(panel => panel.classList.toggle("active", panel.dataset.learningPanel === button.dataset.learningTool));
}));
$$('[data-learning-run]').forEach(button => button.addEventListener("click", () => runLearningTool(button.dataset.learningRun)));
$("#refresh-learning").addEventListener("click", loadLearningCalculations);
$("#learning-calculation").addEventListener("change", event => {
  learningState.selectedId = event.target.value ? Number(event.target.value) : null;
  if (learningState.selectedId) runLearningTool("paths");
});
