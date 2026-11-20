class TpoVwapStrategy:
    def __init__(self, be_buffer: float = 0.35):
        self.be_buffer = be_buffer
        self.active_hours = {0, 2, 3, 4, 5, 6, 7, 11, 12, 14}

    def generate_signal(self, row, prev_row, open_positions: list[dict], blocked_sides_today: set = None):
        regime = row['regime']
        sentiment = row['ls_sentiment']
        dxy_bias = row['dxy_bias']
        adx = row['adx']
        er = row['efficiency_ratio']
        close = row['close']
        open_p = row['open']
        vwap = row['vwap']
        vah = row['tpo_vah']
        val = row['tpo_val']
        poc = row['tpo_poc']
        atr = row['atr']
        ema_macro = row['ema_macro']
        kama_macro = row['kama_macro']

        ts = row['timestamp']
        hour = ts.hour
        if hour not in self.active_hours:
            return None

        if ts.weekday() == 0 and hour < 1:
            return None

        # 1. โหมด Pyramiding Scale-In (ใช้ SL 0.85 ATR + Regime Gate)
        if len(open_positions) > 0:
            if er < 0.20:
                return None

            side = open_positions[0]['side']
            last_entry = open_positions[-1]['entry']

            if side == 'BUY' and regime == 'TREND_UP' and (close - last_entry) >= (0.9 * atr) and sentiment >= 0.05:
                if prev_row['low'] <= max(vwap, poc) and close > max(vwap, poc) and close > open_p:
                    sl = min(prev_row['low'], vwap) - (0.50 * atr)
                    return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'PYRAMID_VWAP_PULLBACK'}

            elif side == 'SELL' and regime == 'TREND_DOWN' and (last_entry - close) >= (0.9 * atr) and sentiment <= -0.05:
                if prev_row['high'] >= min(vwap, poc) and close < min(vwap, poc) and close < open_p:
                    sl = max(prev_row['high'], vwap) + (0.50 * atr)
                    return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'PYRAMID_VWAP_PULLBACK'}
            return None

        # 2. โหมดตามเทรนด์ (POC Pullback คืน 0.60 ATR + VAL Breakout ใช้ 0.85 ATR)
        if er >= 0.20 and adx >= 19:
            if regime == 'TREND_UP' and close > vwap and close > ema_macro and sentiment >= 0.06 and dxy_bias >= 0:
                if prev_row['low'] <= poc and close > poc and close > open_p:
                    sl = min(prev_row['low'], poc) - (0.60 * atr)
                    return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_POC_TREND_PULLBACK'}

            elif regime == 'TREND_DOWN' and close < vwap and close < ema_macro and sentiment <= -0.06 and dxy_bias <= 0:
                if prev_row['high'] >= poc and close < poc and close < open_p:
                    sl = max(prev_row['high'], poc) + (0.60 * atr)
                    return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_POC_TREND_PULLBACK'}

            # VAL Breakout ใช้ 0.85 ATR
            if close < vwap and close < ema_macro and sentiment <= -0.06 and dxy_bias <= 0:
                if adx >= 22 and close < val and prev_row['close'] >= val:
                    sl = max(poc, vwap) + (0.6 * atr)
                    return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VAL_BREAKOUT'}

        # 3. โหมด Fade (คืน 0.65 ATR เพื่อให้เป้า 1.2R ใกล้ขึ้น)
        if er < 0.30 and adx < 26:
            if (
                hour in {6, 7, 12}
                and min(row['low'], prev_row['low']) <= min(val, row['vwap_lower_1'])
                and close > val
                and close > open_p
                and dxy_bias >= 0
                and sentiment >= -0.15
            ):
                sl = min(row['low'], prev_row['low']) - (0.65 * atr)
                return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VWAP_FADE_LONG'}

            elif (
                close < ema_macro
                and close < kama_macro
                and max(row['high'], prev_row['high']) >= max(vah, row['vwap_upper_1'])
                and close < vah
                and close < open_p
                and dxy_bias <= 0
                and sentiment <= 0.15
            ):
                sl = max(row['high'], prev_row['high']) + (0.65 * atr)
                return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VWAP_FADE_SHORT'}

        return None

    def manage_step_lock_exits(self, open_positions: list[dict], row) -> list[dict]:
        if not open_positions:
            return open_positions

        high = row['high']
        low = row['low']
        close = row['close']
        atr = row['atr']

        for pos in open_positions:
            one_r = abs(pos['entry'] - pos['initial_sl'])
            if one_r <= 0:
                continue

            if pos['side'] == 'BUY':
                r_mult = (high - pos['entry']) / one_r
                target_sl = pos['current_sl']
                if r_mult >= 2.8:
                    target_sl = max(close - (1.1 * atr), pos['entry'] + (1.5 * one_r))
                elif r_mult >= 2.0:
                    target_sl = pos['entry'] + (0.80 * one_r)
                elif r_mult >= 1.2:
                    target_sl = pos['entry'] + self.be_buffer

                if target_sl > pos['current_sl']:
                    pos['current_sl'] = round(target_sl, 2)

            elif pos['side'] == 'SELL':
                r_mult = (pos['entry'] - low) / one_r
                target_sl = pos['current_sl']
                if r_mult >= 2.8:
                    target_sl = min(close + (1.1 * atr), pos['entry'] - (1.5 * one_r))
                elif r_mult >= 2.0:
                    target_sl = pos['entry'] - (0.80 * one_r)
                elif r_mult >= 1.2:
                    target_sl = pos['entry'] - self.be_buffer

                if target_sl < pos['current_sl']:
                    pos['current_sl'] = round(target_sl, 2)

        if len(open_positions) >= 2:
            newest = open_positions[-1]
            if newest['side'] == 'BUY' and newest['current_sl'] >= newest['entry']:
                floor_sl = round(newest['current_sl'] - (0.35 * atr), 2)
                for pos in open_positions[:-1]:
                    if floor_sl > pos['current_sl']:
                        pos['current_sl'] = floor_sl
            elif newest['side'] == 'SELL' and newest['current_sl'] <= newest['entry']:
                floor_sl = round(newest['current_sl'] + (0.35 * atr), 2)
                for pos in open_positions[:-1]:
                    if floor_sl < pos['current_sl']:
                        pos['current_sl'] = floor_sl

        return open_positions
