from datamodel import Order


class Trader:
    LIMITS = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300,
        "VEV_4500": 300,
    }

    BASIS_VOUCHERS = {"VEV_4000": 4000, "VEV_4500": 4500}

    H_ANCHOR = 9983.0
    H_CLIP = 33.0
    H_TAKE_EDGE = 0.3
    H_REDUCE_EDGE = 0.0
    H_PENNY_EDGE = 4.0
    H_PASSIVE_OFFSET = 8.0
    H_WIDE_SPREAD = 8
    H_BASE_POST_SIZE = 18
    H_POST_MIN = 12
    H_POST_MAX = 18
    H_POST_ABS_POS_THR = 160
    H_POST_VK_HIGH = 1.0
    H_POST_VK_LOW = 0.0
    H_INV_SKEW = 0.014
    H_INV_SKEW_LONG = -0.015
    H_INV_SKEW_SHORT = 0.014
    H_VK_UP = 0.78
    H_VK_DN = 0.87
    H_VK_DN_SHORT = 0.85
    H_VK_DN_LOW = 2.7
    H_VK_DN_HIGH = 12.0
    H_VK_DN_XTREME = 16.0
    H_POS_THR = 130
    H_POS_THR_2 = 165
    H_AR1_BETA = 0.20
    H_DMID_HISTORY = 150
    H_TYPICAL_SPREAD = 16
    H_STICKY_POS = 184
    H_STICKY_TICKS = 100_000
    H_STICKY_REDUCE_QTY = 40

    V_SIGMA = 0.23
    V_TAKE_EDGE = 0.0
    V_POST_EDGE = 1.0
    V_INV_SKEW = 0.005
    V_POST_SIZE = 40
    V_WIDE_SPREAD = 3

    def _book(self, od):
        if not od.buy_orders or not od.sell_orders:
            return None
        buys = {int(price): abs(int(volume)) for price, volume in od.buy_orders.items()}
        sells = {int(price): abs(int(volume)) for price, volume in od.sell_orders.items()}
        best_bid = max(buys)
        best_ask = min(sells)
        return {
            "buys": dict(sorted(buys.items(), reverse=True)),
            "sells": dict(sorted(sells.items())),
            "bb": best_bid,
            "ba": best_ask,
            "bv": buys[best_bid],
            "av": sells[best_ask],
            "spread": best_ask - best_bid,
            "mid": 0.5 * (best_bid + best_ask),
        }

    @staticmethod
    def _floor(value):
        return int(value)

    @staticmethod
    def _ceil(value):
        whole = int(value)
        return whole if whole == value else whole + 1

    @staticmethod
    def _encode_state(saved):
        hist = saved.get("hydro_dmid_hist", [])
        hist_text = ",".join(str(x) for x in hist)
        extreme = saved.get("hydro_extreme_since")
        if extreme is None:
            extreme = ""
        return "|".join(
            [
                str(saved.get("hydro_last_mid", "")),
                str(saved.get("hydro_last_dmid", 0.0)),
                str(extreme),
                hist_text,
            ]
        )

    @staticmethod
    def _decode_state(text):
        saved = {}
        if not text:
            return saved
        parts = text.split("|", 3)
        while len(parts) < 4:
            parts.append("")
        try:
            if parts[0] != "":
                saved["hydro_last_mid"] = float(parts[0])
            saved["hydro_last_dmid"] = float(parts[1]) if parts[1] != "" else 0.0
            if parts[2] != "":
                saved["hydro_extreme_since"] = int(float(parts[2]))
            if parts[3]:
                saved["hydro_dmid_hist"] = [float(x) for x in parts[3].split(",") if x != ""]
            else:
                saved["hydro_dmid_hist"] = []
        except Exception:
            return {}
        return saved

    def _cap_size(self, max_size, pos, side, cap, limit, linear_cap):
        if cap <= 0:
            return 0
        ratio = 1.0 - min(linear_cap, abs(pos) / limit)
        if (side == "buy" and pos > 0) or (side == "sell" and pos < 0):
            ratio = max(0.3, ratio - 0.3)
        return max(0, min(cap, int(round(max_size * ratio))))

    def _hydro_fair_input(self, book):
        if book["spread"] < self.H_TYPICAL_SPREAD:
            total = book["bv"] + book["av"]
            if total > 0:
                return (book["ba"] * book["bv"] + book["bb"] * book["av"]) / total
        return book["mid"]

    def _hydro_skew_coeff(self, pos):
        if pos > 0:
            return self.H_INV_SKEW_LONG
        if pos < 0:
            return self.H_INV_SKEW_SHORT
        return self.H_INV_SKEW

    def _hydro_clip(self, pos, dmid_hist):
        if len(dmid_hist) < 3:
            return self.H_CLIP, self.H_CLIP, 0.0
        mean_d = sum(dmid_hist) / len(dmid_hist)
        std_d = (sum((value - mean_d) ** 2 for value in dmid_hist) / len(dmid_hist)) ** 0.5
        clip_up = self.H_CLIP + self.H_VK_UP * std_d
        if pos > self.H_POS_THR_2:
            vk_down = self.H_VK_DN_XTREME
        elif pos > self.H_POS_THR:
            vk_down = self.H_VK_DN_HIGH
        elif pos > 0:
            vk_down = self.H_VK_DN_LOW
        elif pos < 0:
            vk_down = self.H_VK_DN_SHORT
        else:
            vk_down = self.H_VK_DN
        return clip_up, self.H_CLIP + vk_down * std_d, std_d

    def _trade_hydrogel(
        self,
        od,
        pos,
        last_dmid,
        dmid_hist,
        sticky_age,
    ):
        product = "HYDROGEL_PACK"
        limit = self.LIMITS[product]
        book = self._book(od)
        if book is None:
            return [], None

        clip_up, clip_down, std_d = self._hydro_clip(pos, dmid_hist)
        fair_offset = self._hydro_fair_input(book) - self.H_ANCHOR
        fair = self.H_ANCHOR + max(-clip_down, min(clip_up, fair_offset))
        fair -= self.H_AR1_BETA * last_dmid

        orders = []
        working = pos
        submitted_buy = 0
        submitted_sell = 0

        for ask, volume in book["sells"].items():
            cap = limit - working
            submit_cap = limit - pos - submitted_buy
            if cap <= 0:
                break
            skew = fair - self._hydro_skew_coeff(working) * working
            if ask <= skew - self.H_TAKE_EDGE:
                qty = min(volume, cap, submit_cap)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    working += qty
                    submitted_buy += qty
            elif working < 0 and ask <= skew + self.H_REDUCE_EDGE:
                qty = min(volume, cap, abs(working), submit_cap)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    working += qty
                    submitted_buy += qty

        for bid, volume in book["buys"].items():
            cap = limit + working
            submit_cap = limit + pos - submitted_sell
            if cap <= 0:
                break
            skew = fair - self._hydro_skew_coeff(working) * working
            if bid >= skew + self.H_TAKE_EDGE:
                qty = min(volume, cap, submit_cap)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    working -= qty
                    submitted_sell += qty
            elif working > 0 and bid >= skew - self.H_REDUCE_EDGE:
                qty = min(volume, cap, working, submit_cap)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    working -= qty
                    submitted_sell += qty

        if sticky_age >= self.H_STICKY_TICKS and working != 0:
            qty_left = min(self.H_STICKY_REDUCE_QTY, abs(working))
            if working > 0:
                for bid, volume in book["buys"].items():
                    submit_cap = limit + pos - submitted_sell
                    qty = min(volume, qty_left, working, submit_cap)
                    if qty > 0:
                        orders.append(Order(product, bid, -qty))
                        working -= qty
                        submitted_sell += qty
                        qty_left -= qty
                    if qty_left <= 0 or working <= 0:
                        break
            else:
                for ask, volume in book["sells"].items():
                    submit_cap = limit - pos - submitted_buy
                    qty = min(volume, qty_left, abs(working), submit_cap)
                    if qty > 0:
                        orders.append(Order(product, ask, qty))
                        working += qty
                        submitted_buy += qty
                        qty_left -= qty
                    if qty_left <= 0 or working >= 0:
                        break

        skew = fair - self._hydro_skew_coeff(working) * working
        buy_cap = max(0, min(limit - working, limit - pos - submitted_buy))
        sell_cap = max(0, min(limit + working, limit + pos - submitted_sell))
        post_vk = self.H_POST_VK_HIGH if abs(working) > self.H_POST_ABS_POS_THR else self.H_POST_VK_LOW
        post_size = int(round(self.H_BASE_POST_SIZE - post_vk * std_d))
        post_size = max(self.H_POST_MIN, min(self.H_POST_MAX, post_size))
        bid_size = self._cap_size(post_size, working, "buy", buy_cap, limit, 0.5)
        ask_size = self._cap_size(post_size, working, "sell", sell_cap, limit, 0.5)
        if working >= int(0.92 * limit):
            bid_size = 0
        elif working <= -int(0.92 * limit):
            ask_size = 0

        if book["spread"] >= self.H_WIDE_SPREAD:
            bid_price = min(book["bb"] + 1, self._floor(skew - self.H_PENNY_EDGE))
            ask_price = max(book["ba"] - 1, self._ceil(skew + self.H_PENNY_EDGE))
        else:
            bid_price = self._floor(skew - self.H_PASSIVE_OFFSET)
            ask_price = self._ceil(skew + self.H_PASSIVE_OFFSET)
        bid_price = min(int(bid_price), book["ba"] - 1, self._floor(fair) - 1)
        ask_price = max(int(ask_price), book["bb"] + 1, self._ceil(fair) + 1)

        if bid_price < ask_price:
            if bid_size > 0:
                orders.append(Order(product, bid_price, bid_size))
            if ask_size > 0:
                orders.append(Order(product, ask_price, -ask_size))
        return orders, book["mid"]

    def _trade_basis_voucher(self, product, strike, od, pos, spot_mid):
        limit = self.LIMITS[product]
        book = self._book(od)
        if book is None:
            return []

        fair = max(0.0, spot_mid - strike)
        orders = []
        working = pos
        submitted_buy = 0
        submitted_sell = 0

        for ask, volume in book["sells"].items():
            cap = limit - working
            submit_cap = limit - pos - submitted_buy
            if cap <= 0:
                break
            skew = fair - self.V_INV_SKEW * working
            if ask <= skew - self.V_TAKE_EDGE:
                qty = min(volume, cap, submit_cap)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    working += qty
                    submitted_buy += qty
            elif working < 0 and ask <= skew:
                qty = min(volume, cap, abs(working), submit_cap)
                if qty > 0:
                    orders.append(Order(product, ask, qty))
                    working += qty
                    submitted_buy += qty

        for bid, volume in book["buys"].items():
            cap = limit + working
            submit_cap = limit + pos - submitted_sell
            if cap <= 0:
                break
            skew = fair - self.V_INV_SKEW * working
            if bid >= skew + self.V_TAKE_EDGE:
                qty = min(volume, cap, submit_cap)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    working -= qty
                    submitted_sell += qty
            elif working > 0 and bid >= skew:
                qty = min(volume, cap, working, submit_cap)
                if qty > 0:
                    orders.append(Order(product, bid, -qty))
                    working -= qty
                    submitted_sell += qty

        if book["spread"] < self.V_WIDE_SPREAD:
            return orders

        skew = fair - self.V_INV_SKEW * working
        buy_cap = max(0, min(limit - working, limit - pos - submitted_buy))
        sell_cap = max(0, min(limit + working, limit + pos - submitted_sell))
        bid_size = self._cap_size(self.V_POST_SIZE, working, "buy", buy_cap, limit, 0.7)
        ask_size = self._cap_size(self.V_POST_SIZE, working, "sell", sell_cap, limit, 0.7)
        if working >= int(0.80 * limit):
            bid_size = 0
        elif working <= -int(0.80 * limit):
            ask_size = 0
        bid_price = min(book["bb"] + 1, self._floor(skew - self.V_POST_EDGE))
        ask_price = max(book["ba"] - 1, self._ceil(skew + self.V_POST_EDGE))
        bid_price = min(int(bid_price), book["ba"] - 1, self._floor(fair) - 1)
        ask_price = max(int(ask_price), book["bb"] + 1, self._ceil(fair) + 1)

        if bid_price < ask_price:
            if bid_size > 0:
                orders.append(Order(product, bid_price, bid_size))
            if ask_size > 0:
                orders.append(Order(product, ask_price, -ask_size))
        return orders

    def run(self, state):
        saved = self._decode_state(state.traderData)

        result = {}

        last_mid = saved.get("hydro_last_mid")
        last_dmid = float(saved.get("hydro_last_dmid", 0.0))
        dmid_hist = list(saved.get("hydro_dmid_hist", []))
        hydro_od = state.order_depths.get("HYDROGEL_PACK")
        if hydro_od is not None:
            hydro_pos = state.position.get("HYDROGEL_PACK", 0)
            extreme_since = saved.get("hydro_extreme_since")
            if abs(hydro_pos) >= self.H_STICKY_POS:
                if extreme_since is None:
                    extreme_since = state.timestamp
                saved["hydro_extreme_since"] = extreme_since
                sticky_age = int(state.timestamp - int(extreme_since))
            else:
                saved.pop("hydro_extreme_since", None)
                sticky_age = 0
            orders, new_mid = self._trade_hydrogel(
                hydro_od,
                hydro_pos,
                last_dmid,
                dmid_hist,
                sticky_age,
            )
            if orders:
                result["HYDROGEL_PACK"] = orders
            if new_mid is not None:
                if last_mid is not None:
                    dmid = new_mid - float(last_mid)
                    saved["hydro_last_dmid"] = dmid
                    dmid_hist.append(dmid)
                    if len(dmid_hist) > self.H_DMID_HISTORY:
                        dmid_hist = dmid_hist[-self.H_DMID_HISTORY:]
                else:
                    saved["hydro_last_dmid"] = 0.0
                saved["hydro_last_mid"] = new_mid
                saved["hydro_dmid_hist"] = dmid_hist

        spot_book = None
        spot_od = state.order_depths.get("VELVETFRUIT_EXTRACT")
        if spot_od is not None:
            spot_book = self._book(spot_od)
        if spot_book is not None:
            spot_mid = spot_book["mid"]
            for product, strike in self.BASIS_VOUCHERS.items():
                od = state.order_depths.get(product)
                if od is None:
                    continue
                orders = self._trade_basis_voucher(
                    product,
                    strike,
                    od,
                    state.position.get(product, 0),
                    spot_mid,
                )
                if orders:
                    result[product] = orders

        return result, 0, self._encode_state(saved)
