# Round 3 - “Gloves Off”

Welcome to **Solvenar**. Round 3 is the opening round of the
**Great Orbital Ascension Trials (GOAT)**, the final three-round phase
of Prosperity 4. The official Round 3 page says that all teams begin
this stage from **zero PnL** and that the leaderboard is reset before
trading starts.

The official intro text describes Solvenar as a prosperous and highly
developed planet known for technological innovation, a robust economy,
and thriving cultural sectors. It also explicitly frames GOAT as a
**Great Galactic Trade-Off**, where trading crews compete head-on for
the title of **Trading Champion of the Galaxy**.

## Sources

This note consolidates:

- the public `prosperity.imc.com` schedule page
- the official Round 3 Notion / wiki text provided by the user
- the official Round 3 data-capsule text provided by the user
- the official Round 3 A.R.I.A. uplink transcript provided by the user
- local verification from the downloaded Round 3 CSV files

Where a point comes from local CSV inspection rather than the official
briefing text, it is labeled as such.

## Round framing

- The public schedule shows **Round 3** running from **Friday, April 24,
  2026 at 12:00 CEST** to **Sunday, April 26, 2026 at 12:00 CEST**.
- The official Round 3 page names this round **“Gloves Off”** and
  frames Solvenar as the start of GOAT, the final three-round
  competition for the title of **Trading Champion of the Galaxy**.
- The Round 3 page and uplink both say all prior Intara results are
  ignored and every team starts this Solvenar phase from **0 PnL**.
- Solvenar rounds are shorter than the Intara rounds: the page says
  each trading round now lasts **48 hours**.

## Round objective

- The official page says this round marks the first step of the final
  phase and tells teams to be decisive, thorough, and fast because
  Solvenarian trading rounds last only 48 hours.
- Build a new Python trader for `HYDROGEL_PACK`,
  `VELVETFRUIT_EXTRACT`, and the `VELVETFRUIT_EXTRACT_VOUCHER`
  product family.
- Manually submit **two** orders for **Ornamental Bio-Pods** in the
  Celestial Gardeners' Guild challenge.
- Any acquired Bio-Pods are automatically converted into profit before
  the next trading round begins.

## Algorithmic trading challenge: “Options Require Decisions”

### Officially confirmed tradable goods

The official Round 3 page confirms three tradable categories:

- `HYDROGEL_PACK`
- `VELVETFRUIT_EXTRACT`
- `VELVETFRUIT_EXTRACT_VOUCHER` products (`VEV_*`)

The page explicitly says there are **2 asset classes** in play:

- `HYDROGEL_PACK` and `VELVETFRUIT_EXTRACT` are delta-1 products
- the `VEV_*` voucher products are options
- all products are traded independently, even though voucher prices may
  be related to `VELVETFRUIT_EXTRACT`

### Velvetfruit Extract vouchers

The official Round 3 page and data-capsule note together specify that
the vouchers:

- are labeled `VEV_4000`, `VEV_4500`, `VEV_5000`, `VEV_5100`,
  `VEV_5200`, `VEV_5300`, `VEV_5400`, `VEV_5500`, `VEV_6000`,
  `VEV_6500`
- are available under these exact product codes and strike prices:
  - `VEV_4000`: strike `4000`
  - `VEV_4500`: strike `4500`
  - `VEV_5000`: strike `5000`
  - `VEV_5100`: strike `5100`
  - `VEV_5200`: strike `5200`
  - `VEV_5300`: strike `5300`
  - `VEV_5400`: strike `5400`
  - `VEV_5500`: strike `5500`
  - `VEV_6000`: strike `6000`
  - `VEV_6500`: strike `6500`
- have a **7-day expiration deadline starting from Round 1**, with each
  round counting as one day
- therefore have **TTE = 5 days** at the start of the final simulation
  of Round 3

The official example on the page also gives the historical mapping:

- historical day `0`: `TTE = 8d` and coincides with the tutorial round
- historical day `1`: `TTE = 7d` and coincides with Round 1
- historical day `2`: `TTE = 6d` and coincides with Round 2

The uplink wording that there are **five rounds left until expiry** in
overall Round 3 is consistent with this mapping.

### Position limits

The official Round 3 page gives these limits:

- `HYDROGEL_PACK`: `200`
- `VELVETFRUIT_EXTRACT`: `200`
- each `VEV_*` voucher: `300`

### End-of-round and exercise rules

The official page explicitly states:

- vouchers **cannot be exercised before expiry**
- inventory does **not** carry over into the next round
- like earlier rounds, any open positions are automatically liquidated
  against a **hidden fair value** at the end of the round

### Data capsule note

The official data-capsule text says:

- "This Data Capsule contains historical performance data for all
  available tradable goods."
- "Download the data file to analyze the performance history of
  Hydrogel Packs and Velvetfruit Extract."
- "All the Velvetfruit Extract Vouchers have a Time To Expiry (TTE) of
  7 Solvenarian days, starting from day 1."

The exact available VEVs listed in the data-capsule note are:

- `VEV_4000`; strike price `4000`
- `VEV_4500`; strike price `4500`
- `VEV_5000`; strike price `5000`
- `VEV_5100`; strike price `5100`
- `VEV_5200`; strike price `5200`
- `VEV_5300`; strike price `5300`
- `VEV_5400`; strike price `5400`
- `VEV_5500`; strike price `5500`
- `VEV_6000`; strike price `6000`
- `VEV_6500`; strike price `6500`

### Local CSV verification

From the downloaded files mirrored into `IMCP2026/data/round3/`:

- each `prices_round_3_day_{0,1,2}.csv` file has `120000` rows
- all three price files contain these `12` products:
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
- the trades files confirm live trading in the underlyings and in most
  of the voucher strikes, though some strikes show no trades on some
  individual sample days

## Manual trading challenge: “The Celestial Gardeners’ Guild”

The official Round 3 page describes a one-round-only manual challenge
involving the **Celestial Gardeners' Guild** and **Ornamental
Bio-Pods**.

The page's opening manual-challenge framing says the Guild is making a
rare appearance to kick off GOAT and that teams may submit two offers
and trade with as many of the so-called gardeners as fits their
profitability strategy.

### Core mechanic

- You trade against a secret number of counterparties.
- Each counterparty has a **reserve price** between **670** and **920**.
- Reserve prices are **uniformly distributed** in **increments of 5**
  across that range.
- You trade at most once with each counterparty.
- On the next trading day, all acquired Bio-Pods are sold for a fair
  price of **920**.
- Teams may submit **two bids**.

### Second-bid rule

The official page states:

- if the **first bid** is higher than a counterparty's reserve price,
  you trade at the first bid
- if the **second bid** is higher than the reserve price **and** higher
  than the mean of second bids across all players, you trade at the
  second bid
- if the second bid is higher than reserve but **lower than or equal**
  to that global mean, the trade becomes much less attractive and the
  page gives a PnL penalty factor:

```text
((920 - avg_b2) / (920 - b2))^3
```

### Extra clue from the uplink

- The uplink says the guild believes in the **power of the flowering
  fives**.
- It also says their reserve prices are always set **a flowering five
  apart**, which aligns with the Notion rule that reserves live on a
  `5`-spaced grid from `670` to `920`.

### Submission flow

- manual bids are submitted directly in the graphical user interface
- manual submissions are separate from algorithm uploads
- you can resubmit until the round ends
- the **last submitted** pair of bids is the one that counts
