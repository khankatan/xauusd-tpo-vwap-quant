class TpoVwapStrategy:
    def __init__(self, be_buffer: float = 0.35):
        self.be_buffer = be_buffer

    def generate_signal(self, row, prev_row, open_positions: list[dict]):
        regime = row['regime']
        sentiment = row['ls_sentiment']
        dxy_bias = row['dxy_bias']
        close = row['close']
        open_p = row['open']
        vwap = row['vwap']
        vah = row['tpo_vah']
        val = row['tpo_val']
        poc = row['tpo_poc']
        atr = row['atr']

        # กรองช่วงเวลาสภาพคล่องต่ำมาก (04:00 - 06:45 น. เวลาไทย)
        hour = row['timestamp'].hour
        if 4 <= hour < 7:
            return None

        # 1. โหมด Pyramiding Scale-In (เมื่อมีไม้เปิดอยู่แล้วและปลดล็อก Risk แล้ว)
        if len(open_positions) > 0:
            side = open_positions[0]['side']
            last_entry = open_positions[-1]['entry']

            if side == 'BUY' and (close - last_entry) >= (1.0 * atr) and sentiment >= 0.0:
                if prev_row['low'] <= max(vwap, poc) and close > max(vwap, poc) and close > open_p:
                    sl = min(prev_row['low'], vwap) - (0.8 * atr)
                    return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'PYRAMID_VWAP_PULLBACK'}

            elif side == 'SELL' and (last_entry - close) >= (1.0 * atr) and sentiment <= 0.0:
                if prev_row['high'] >= min(vwap, poc) and close < min(vwap, poc) and close < open_p:
                    sl = max(prev_row['high'], vwap) + (0.8 * atr)
                    return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'PYRAMID_VWAP_PULLBACK'}
            return None

        # 2. โหมดเข้าไม้แรก (Initial Entry)
        # Setup A: TPO Value Area Breakout (พระเอกที่ทำ PF 1.7 - 4.1)
        if regime == 'TREND_UP' and sentiment >= 0.05 and dxy_bias >= 0:
            if close > vah and close > vwap and prev_row['close'] <= vah:
                sl = min(poc, vwap) - (0.7 * atr)
                return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VAH_BREAKOUT'}

            # Setup B (ใหม่): ย่อทดสอบ POC + VWAP Confluence ในเทรนด์ขาขึ้น
            if prev_row['low'] <= poc and close > poc and close > vwap and close > open_p:
                sl = min(prev_row['low'], val) - (0.6 * atr)
                return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_POC_TREND_PULLBACK'}

        elif regime == 'TREND_DOWN' and sentiment <= -0.05 and dxy_bias <= 0:
            if close < val and close < vwap and prev_row['close'] >= val:
                sl = max(poc, vwap) + (0.7 * atr)
                return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VAL_BREAKOUT'}

            # Setup B (ใหม่): เด้งทดสอบ POC + VWAP Confluence ในเทรนด์ขาลง
            if prev_row['high'] >= poc and close < poc and close < vwap and close < open_p:
                sl = max(prev_row['high'], vah) + (0.6 * atr)
                return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_POC_TREND_PULLBACK'}

        # Setup C: Sideway Mean Reversion (เฉพาะฝั่ง Short ที่แม่นยำ และบังคับ Long ต้องมีแท่งเขียวกลืนกิน + ไม่สวน DXY)
        elif regime == 'BALANCE_SIDEWAY':
            if row['high'] >= row['vwap_upper_2'] and close < vah and close < open_p and sentiment <= 0.10:
                sl = row['high'] + (0.9 * atr)
                return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VWAP_FADE_SHORT'}

            elif (
                row['low'] <= row['vwap_lower_2']
                and close > val
                and close > open_p
                and close > prev_row['high']  # บังคับ Bullish Confirmation กันรับมีด
                and dxy_bias >= 0
                and sentiment >= 0.0
            ):
                sl = min(row['low'], prev_row['low']) - (0.9 * atr)
                return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VWAP_FADE_LONG_CONFIRMED'}

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
                if r_mult >= 3.0:
                    target_sl = max(close - (1.3 * atr), pos['entry'] + (1.6 * one_r))
                elif r_mult >= 2.2:
                    target_sl = pos['entry'] + (0.85 * one_r)
                elif r_mult >= 1.35:  # ขยับจุด Break-Even จาก 1.0R เป็น 1.35R ลดการโดนดีดออกฟรี
                    target_sl = pos['entry'] + self.be_buffer

                if target_sl > pos['current_sl']:
                    pos['current_sl'] = round(target_sl, 2)

            elif pos['side'] == 'SELL':
                r_mult = (pos['entry'] - low) / one_r
                target_sl = pos['current_sl']
                if r_mult >= 3.0:
                    target_sl = min(close + (1.3 * atr), pos['entry'] - (1.6 * one_r))
                elif r_mult >= 2.2:
                    target_sl = pos['entry'] - (0.85 * one_r)
                elif r_mult >= 1.35:
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
