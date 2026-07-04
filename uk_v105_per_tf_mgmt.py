"""uk_v105_per_tf_mgmt.py — v102 + per-TF trade management knobs.

Per-TF knobs (set in configure_for_tf, swept via grid):
  - max_run_r:               cap on trade R (currently 5.0 universal)
  - trail_after_tp_buffer:   trail buffer after TP1 (currently 0.003 universal)
  - trail_after_tp_pivot:    trail pivot window (currently 5 bars HARDCODED)
  - vstop.buffer_pct:        SL pivot buffer (currently 0.003 universal)
  - vstop.pivot_window:      SL pivot window (currently 3 universal)

Grid keys passed via --set (engine flatten):
  mgmt_us_1d_max_run_r, mgmt_us_8h_max_run_r, mgmt_fut_1d_max_run_r
  mgmt_us_1d_trail_buf, mgmt_us_8h_trail_buf, ...
  mgmt_us_1d_vstop_buf, ...
  mgmt_us_1d_vstop_win, ...

Default behavior identical to v102 when all knobs at defaults.
"""
import sys
sys.path.insert(0, "/root/hl-backtest/strategies")
import datetime as dt
from typing import Optional
from uk_v102_ib_filtered import Strategy as V102Base
from harness.strategy import Signal, ExitDecision


TRAIL_TP_TFS = {"1d", "8h"}
EOD_INTRADAY_US_TFS = {"15m", "30m", "1h", "2h"}


class Strategy(V102Base):
    name = "uk_v105_per_tf_mgmt"
    default_config = dict(V102Base.default_config)
    # Per-TF knobs (default = universal v102 behavior)
    for tf in ["us_1d", "us_8h", "fut_1d"]:
        default_config[f"mgmt_{tf}_max_run_r"] = 5.0
        default_config[f"mgmt_{tf}_trail_buf"] = 0.003
        default_config[f"mgmt_{tf}_trail_pivot"] = 5
        default_config[f"mgmt_{tf}_vstop_buf"] = 0.003
        default_config[f"mgmt_{tf}_vstop_win"] = 3

    def configure_for_tf(self, tf: str):
        super().configure_for_tf(tf)
        # Determine bucket key (asset_class needed — set by engine via _asset_class config key)
        ac_raw = self.config.get("_asset_class", "us")
        # Normalize: engine uses 'us'/'futures'/'crypto'/'ib_stocks'; we use 'us'/'fut'
        AC_MAP = {"us": "us", "ib_stocks": "us", "futures": "fut", "crypto": "crypto"}
        ac = AC_MAP.get(ac_raw, ac_raw)
        bk = f"{ac}_{tf}"
        # Read per-TF mgmt knobs and write into universal config keys
        if f"mgmt_{bk}_max_run_r" in self.config:
            self.config["max_run_r"] = self.config[f"mgmt_{bk}_max_run_r"]
        if f"mgmt_{bk}_trail_buf" in self.config:
            self.config["trail_after_tp_buffer_pct"] = self.config[f"mgmt_{bk}_trail_buf"]
        if f"mgmt_{bk}_trail_pivot" in self.config:
            self.config["_trail_after_tp_pivot"] = int(self.config[f"mgmt_{bk}_trail_pivot"])
        if f"mgmt_{bk}_vstop_buf" in self.config:
            if "vstop" not in self.config: self.config["vstop"] = {}
            self.config["vstop"]["buffer_pct"] = self.config[f"mgmt_{bk}_vstop_buf"]
        if f"mgmt_{bk}_vstop_win" in self.config:
            if "vstop" not in self.config: self.config["vstop"] = {}
            self.config["vstop"]["pivot_window"] = int(self.config[f"mgmt_{bk}_vstop_win"])

    def maybe_exit(self, pos, ctx) -> Optional[ExitDecision]:
        cfg = self.config
        w = ctx.window
        i = w.i
        # Trail-after-TP only on selected TFs
        if cfg.get("enable_trail_after_tp", True) and ctx.tf in TRAIL_TP_TFS:
            if not hasattr(self, "_tp_hit"):
                self._tp_hit = {}
            tp_hit = self._tp_hit.get(ctx.coin, False)
            sl_dist = pos.entry_price - pos.sl_initial
            if sl_dist > 0:
                rr = cfg.get("raw_rr_target", 1.5)
                tp1 = pos.entry_price + rr * sl_dist
                if not tp_hit:
                    if w.high[i] >= tp1:
                        buffer = cfg.get("trail_after_tp_buffer_pct", 0.003)
                        new_sl = pos.entry_price * (1 + buffer)
                        if new_sl > pos.sl_current:
                            if not hasattr(self, "_trail_sl"):
                                self._trail_sl = {}
                            self._trail_sl[ctx.coin] = new_sl
                        self._tp_hit[ctx.coin] = True
                        return None
                else:
                    cur_r = (w.close[i] - pos.entry_price) / sl_dist
                    if cur_r >= cfg.get("max_run_r", 5.0):
                        self._tp_hit.pop(ctx.coin, None)
                        self._cleanup_trail(ctx.coin)
                        return ExitDecision(exit_price=pos.entry_price + cfg["max_run_r"] * sl_dist, reason="max_run_cap")
                    # Trail pivot window — per-TF configurable (was hardcoded 5)
                    trail_pivot = int(cfg.get("_trail_after_tp_pivot", 5))
                    if i >= trail_pivot:
                        recent_low = min(w.low[i-trail_pivot:i+1])
                        new_sl = recent_low - cfg.get("tick_size", 0.01)
                        cur_sl = self._trail_sl.get(ctx.coin, pos.sl_current) if hasattr(self, "_trail_sl") else pos.sl_current
                        if new_sl > cur_sl:
                            if not hasattr(self, "_trail_sl"):
                                self._trail_sl = {}
                            self._trail_sl[ctx.coin] = new_sl
                    trail_sl = self._trail_sl.get(ctx.coin) if hasattr(self, "_trail_sl") else None
                    if trail_sl is not None and w.low[i] <= trail_sl:
                        self._tp_hit.pop(ctx.coin, None)
                        self._cleanup_trail(ctx.coin)
                        return ExitDecision(exit_price=trail_sl, reason="trail_after_tp_stop")
                    return None
        # EOD close for US intraday
        if cfg.get("force_eod_close_us", True) and ctx.tf in EOD_INTRADAY_US_TFS:
            ac = cfg.get("_asset_class", "crypto")
            if ac == "us":
                ts_ms = int(w.ts[i])
                tf_min = {"15m": 15, "30m": 30, "1h": 60, "2h": 120}[ctx.tf]
                next_ts_ms = ts_ms + tf_min * 60 * 1000
                if dt.datetime.utcfromtimestamp(ts_ms/1000).date() != dt.datetime.utcfromtimestamp(next_ts_ms/1000).date():
                    self._cleanup_trail(ctx.coin)
                    return ExitDecision(exit_price=w.close[i], reason="eod_close")
        return super().maybe_exit(pos, ctx)
