class TpoVwapStrategy:
    def __init__(self, be_buffer: float = 0.35):
        self.be_buffer = be_buffer
        # คัดเฉพาะชั่วโมงที่ทองคำมีสภาพคล่องและทิศทางชัดเจน (Asia Open, London Core, NY/COMEX Core)
        self.active_hours = {0, 7, 10, 12, 16, 17, 20, 21, 22}

    def generate_signal(self, row, prev_row, open_positions: list[dict]):
        regime = row['regime']
        sentiment = row['ls_sentiment']
        dxy_bias = row['dxy_bias']
        adx = row['adx']
        close = row['close']
        open_p = row['open']
        vwap = row['vwap']
        vah = row['tpo_vah']
        val = row['tpo_val']
        poc = row['tpo_poc']
        atr = row['atr']
        ema_fast = row['ema_fast']
        ema_slow = row['ema_slow']

        hour = row['timestamp'].hour
        if hour not in self.active_hours:
            return None

        # 1. โหมด Pyramiding Scale-In (เมื่อไม้แรกปลดล็อก Break-Even แล้ว)
        if len(open_positions) > 0:
            side = open_positions[0]['side']
            last_entry = open_positions[-1]['entry']

            if side == 'BUY' and (close - last_entry) >= (0.9 * atr) and sentiment >= 0.0:
                if prev_row['low'] <= max(vwap, poc) and close > max(vwap, poc) and close > open_p:
                    sl = min(prev_row['low'], vwap) - (0.5 * atr)
                    return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'PYRAMID_VWAP_PULLBACK'}

            elif side == 'SELL' and (last_entry - close) >= (0.9 * atr) and sentiment <= 0.0:
                if prev_row['high'] >= min(vwap, poc) and close < min(vwap, poc) and close < open_p:
                    sl = max(prev_row['high'], vwap) + (0.5 * atr)
                    return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'PYRAMID_VWAP_PULLBACK'}
            return None

        # 2. โหมดเข้าไม้แรก (Initial Entry)
        # Setup A: POC Trend Pullback (เข้าเมื่อย่อทดสอบ POC + VWAP ในทิศทางเทรนด์)
        if regime == 'TREND_UP' and sentiment >= 0.05 and dxy_bias >= 0:
            if prev_row['low'] <= poc and close > poc and close > vwap and close > open_p:
                sl = min(prev_row['low'], poc) - (0.6 * atr)
                return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_POC_TREND_PULLBACK'}

        elif regime == 'TREND_DOWN' and sentiment <= -0.05 and dxy_bias <= 0:
            if prev_row['high'] >= poc and close < poc and close < vwap and close < open_p:
                sl = max(prev_row['high'], poc) + (0.6 * atr)
                return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_POC_TREND_PULLBACK'}

            # VAL Breakdown เฉพาะฝั่งลงที่แรงจริง (ADX >= 22)
            if adx >= 22 and close < val and close < vwap and prev_row['close'] >= val:
                sl = max(poc, vwap) + (0.6 * atr)
                return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VAL_BREAKOUT'}

        # Setup B: Fade Long (ตัวทำกำไร PF 1.24 ใน V3) & Fade Short (จำกัดเฉพาะโครงสร้างหลักขาลง)
        if adx < 26:
            # Fade Long: ลงทดสอบ VAL / VWAP -1SD แล้วดีดกลับปิดเขียวเหนือ VAL
            if (
                min(row['low'], prev_row['low']) <= min(val, row['vwap_lower_1'])
                and close > val
                and close > open_p
                and dxy_bias >= 0
                and sentiment >= -0.15
            ):
                sl = min(row['low'], prev_row['low']) - (0.6 * atr)
                return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VWAP_FADE_LONG'}

            # Fade Short: ขึ้นทดสอบ VAH / VWAP +1SD แล้วตบกลับปิดแดงใต้ VAH (ต้องอยู่ในโครงสร้าง EMA ขาลงเท่านั้น)
            elif (
                ema_fast < ema_slow
                and max(row['high'], prev_row['high']) >= max(vah, row['vwap_upper_1'])
                and close < vah
                and close < open_p
                and dxy_bias <= 0
                and sentiment <= 0.15
            ):
                sl = max(row['high'], prev_row['high']) + (0.6 * atr)
                return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VWAP_FADE_SHORT'}

        return None

    def manage_step_lock_exits(self, open_positions: list[dict], row) -> list[dict]:
        if not open_positions:
            return open_positions

        high = row['high']
        low = row['low']
        close = row['close']
        atr = row['atr']

        # 1. Step-Lock รายไม้ตาม R-Multiple (เร่ง Break-Even ที่ 1.15R เพื่อลด Full SL และปลดล็อก Pyramiding)
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
                elif r_mult >= 1.15:
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
                elif r_mult >= 1.15:
                    target_sl = pos['entry'] - self.be_buffer

                if target_sl < pos['current_sl']:
                    pos['current_sl'] = round(target_sl, 2)

        # 2. Basket Floor Protection
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
