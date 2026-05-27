# Round 4 - "The More The Merrier"

Round 4 is the second round of the Great Orbital Ascension Trials. The
official Round 4 page says the algorithmic products are unchanged from
Round 3, but the historical trade data now exposes named counterparties
in `Trade.buyer` and `Trade.seller`.

## Sources

This note consolidates:

- the public `prosperity.imc.com` schedule page
- the official Round 4 Notion page, fetched from the public Notion API
- the Round 4 A.R.I.A. uplink transcript provided by the user
- local verification from the downloaded Round 4 CSV files
- the local counterparty event study in
  `IMCP2026/analysis/round4_counterparty_signal_report.md`

Where a point comes from local CSV inspection rather than the official
briefing text, it is labeled as local.

## Round framing

- The public schedule shows **Round 4** running from **Sunday, April 26,
  2026 at 12:00 CEST** to **Tuesday, April 28, 2026 at 12:00 CEST**.
- The official Round 4 page names the round **"The More The Merrier"**.
- The algorithmic challenge is titled **"Hello, I'm Mark"**.
- The manual trading challenge is titled **"Vanilla Just Isn't Exotic
  Enough"**.
- The transcript says all Round 3 manual Bio-Pod positions were
  immediately sold before Round 4, adding realized profit to PnL.

## Round objective

- Optimize the Python trader for `HYDROGEL_PACK`,
  `VELVETFRUIT_EXTRACT`, and the `VELVETFRUIT_EXTRACT_VOUCHER`
  product family.
- Incorporate the newly disclosed counterparty IDs where they improve a
  strategy.
- Submit manual orders for `AETHER_CRYSTAL` and its option contracts.
- The Aether Crystal manual challenge is independent from algorithmic
  trading.

## Algorithmic Trading Challenge

The official page confirms there are no new algorithmic products in
Round 4. The products remain:

- `HYDROGEL_PACK`
- `VELVETFRUIT_EXTRACT`
- `VEV_4000`
- `VEV_4500`
- `VEV_5000`
- `VEV_5100`
- `VEV_5200`
- `VEV_5300`
- `VEV_5400`
- `VEV_5500`
- `VEV_6000`
- `VEV_6500`

The official position limits remain:

- `HYDROGEL_PACK`: `200`
- `VELVETFRUIT_EXTRACT`: `200`
- each `VELVETFRUIT_EXTRACT_VOUCHER`: `300`

The official Round 4 page gives the example that `VEV_5000` has strike
`5000`, **TTE = 4 days** in Round 4, and position limit `300`.

## Counterparty Fields

The official Round 4 page says the `Trade` class now exposes the names
of market participants through `self.buyer` and `self.seller`. In
Rounds 1-3 these fields were effectively unavailable for strategy use.

The uplink says identified counterparties come from local neurobotics
programs and use Mark-style IDs. The local Round 4 CSVs contain these
IDs:

- `Mark 01`
- `Mark 14`
- `Mark 22`
- `Mark 38`
- `Mark 49`
- `Mark 55`
- `Mark 67`

Local event-study highlights from the supplied data:

- `Mark 67` buying `VELVETFRUIT_EXTRACT` is the cleanest named-flow
  signal: `165` buy events, positive signed edge across 1/5/10/20 book
  horizons, and hit rates of `0.958`, `0.830`, `0.758`, and `0.648`.
- `Mark 14` has weak positive signed edge in `HYDROGEL_PACK`, while
  `Mark 38` is weakly negative.
- Voucher counterparty flow is mostly mechanical in the supplied
  sample, especially the recurring `Mark 01` / `Mark 22` pairs in the
  OTM vouchers.
- A direct Mark 67 follow overlay was tested in
  `IMCP2026/traders/round4/current_strategy.py` and rejected because it
  reduced the three-day jmerle backtest from `440,853` to `368,294`.

## Local CSV Verification

The downloaded files were mirrored into `IMCP2026/data/round4/`.

- `prices_round_4_day_1.csv`, `prices_round_4_day_2.csv`, and
  `prices_round_4_day_3.csv` each contain `120000` data rows.
- All three price files contain the same `12` products listed above.
- The trade files contain `1407`, `1333`, and `1541` trade rows
  respectively, excluding headers.
- Buyer and seller fields are populated on every local trade row.

## Manual Trading Challenge

The official page says Round 4 manual trading includes:

- `AETHER_CRYSTAL`
- 2-week and 3-week vanilla calls and puts
- a chooser option
- a binary put option
- a knock-out put option

The official page defines a week as `5` trading days and the standard
trading year as `252` days.

The official Aether Crystal simulation settings are:

- underlying process: Geometric Brownian Motion
- risk-neutral drift: `0`
- fixed annualized volatility: `251%`
- time grid: `4` steps per trading day
- final score: average PnL across `100` underlying simulations
- order size: buy or sell up to the displayed volume in each product

The transcript highlights these exotic-contract details:

- chooser option: strike `50`; buyer later chooses call or put, and in
  competition it automatically converts to the in-the-money side
- binary put: strike `40`; pays fixed `10` if the underlying finishes
  below strike, otherwise `0`
- knock-out put: strike `45`; barrier `35`; worthless if the underlying
  ever breaches the barrier before expiry

The transcript describes the chooser decision and expiries in
Solenarian-day language, while the official Round 4 page describes them
as 2-week and 3-week contracts and explicitly defines a week as 5
trading days. Treat the platform's manual challenge window and the
official Notion page as authoritative if the time wording conflicts.

## Submission Flow

- Manual Aether Crystal orders are entered in the Manual Challenge
  Overview window.
- Manual input can be resubmitted until the round timer ends.
- The final submitted manual orders are locked in and processed.
- Algorithmic and manual submissions are independent.
