class TpoVwapStrategy:
    def __init__(self, be_buffer: float = 0.30):
        self.be_buffer = be_buffer

    def generate_signal(self, row, prev_row, open_positions: list[dict]):
        regime = row['regime']
        sentiment = row['ls_sentiment']
        close = row['close']
        vwap = row['vwap']
        vah = row['tpo_vah']
        val = row['tpo_val']
        poc = row['tpo_poc']
        atr = row['atr']

        # กรองช่วงเวลาสภาพคล่องต่ำ (พักตลาด 04:00 - 07:00 น. เวลาไทย)
        hour = row['timestamp'].hour
        if 4 <= hour < 7:
            return None

        # กรณีมีออเดอร์เปิดอยู่แล้ว -> หาจังหวะ Scale-In (Pyramiding)
        if len(open_positions) > 0:
            side = open_positions[0]['side']
            last_entry = open_positions[-1]['entry']

            # ต้องวิ่งห่างจากไม้ล่าสุดอย่างน้อย 1.2 ATR และย่อกลับมาทดสอบ VWAP หรือขอบ VAH/VAL
            if side == 'BUY' and (close - last_entry) >= (1.2 * atr) and sentiment >= 0.0:
                if prev_row['low'] <= vwap and close > vwap:
                    sl = min(prev_row['low'], vwap) - (0.8 * atr)
                    return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'PYRAMID_VWAP_PULLBACK'}

            elif side == 'SELL' and (last_entry - close) >= (1.2 * atr) and sentiment <= 0.0:
                if prev_row['high'] >= vwap and close < vwap:
                    sl = max(prev_row['high'], vwap) + (0.8 * atr)
                    return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'PYRAMID_VWAP_PULLBACK'}
            return None

        # กรณีไม่มีออเดอร์ -> หาจังหวะเข้าไม้แรก (Initial Entry)
        # 1. โหมดตามเทรนด์ (Imbalance Breakout + VWAP Confluence)
        if regime == 'TREND_UP' and sentiment >= 0.15:
            if close > vah and close > vwap and prev_row['close'] <= vah:
                sl = min(poc, vwap) - (0.6 * atr)
                return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VAH_BREAKOUT'}

        elif regime == 'TREND_DOWN' and sentiment <= -0.15:
            if close < val and close < vwap and prev_row['close'] >= val:
                sl = max(poc, vwap) + (0.6 * atr)
                return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VAL_BREAKOUT'}

        # 2. โหมดตลาดออกข้าง (Mean Reversion ที่ขอบ VWAP +-2SD ซ้อนทับ VAH/VAL)
        elif regime == 'BALANCE_SIDEWAY':
            if row['high'] >= row['vwap_upper_2'] and close < vah and sentiment <= 0.10:
                sl = row['high'] + (0.8 * atr)
                return {'side': 'SELL', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VWAP_FADE_SHORT'}

            elif row['low'] <= row['vwap_lower_2'] and close > val and sentiment >= -0.10:
                sl = row['low'] - (0.8 * atr)
                return {'side': 'BUY', 'entry': close, 'sl': round(sl, 2), 'setup': 'TPO_VWAP_FADE_LONG'}

        return None

    def manage_step_lock_exits(self, open_positions: list[dict], row) -> list[dict]:
        if not open_positions:
            return open_positions

        high = row['high']
        low = row['low']
        close = row['close']
        atr = row['atr']

        # 1. Step-Lock รายไม้ตาม R-Multiple
        for pos in open_positions:
            one_r = abs(pos['entry'] - pos['initial_sl'])
            if one_r <= 0:
                continue

            if pos['side'] == 'BUY':
                r_mult = (high - pos['entry']) / one_r
                target_sl = pos['current_sl']
                if r_mult >= 3.0:
                    target_sl = max(close - (1.2 * atr), pos['entry'] + (1.5 * one_r))
                elif r_mult >= 2.0:
                    target_sl = pos['entry'] + (0.75 * one_r)
                elif r_mult >= 1.0:
                    target_sl = pos['entry'] + self.be_buffer

                if target_sl > pos['current_sl']:
                    pos['current_sl'] = round(target_sl, 2)

            elif pos['side'] == 'SELL':
                r_mult = (pos['entry'] - low) / one_r
                target_sl = pos['current_sl']
                if r_mult >= 3.0:
                    target_sl = min(close + (1.2 * atr), pos['entry'] - (1.5 * one_r))
                elif r_mult >= 2.0:
                    target_sl = pos['entry'] - (0.75 * one_r)
                elif r_mult >= 1.0:
                    target_sl = pos['entry'] - self.be_buffer

                if target_sl < pos['current_sl']:
                    pos['current_sl'] = round(target_sl, 2)

        # 2. Basket Floor Protection (เมื่อมี >= 2 ไม้ และไม้ล่าสุดอยู่ที่ Break-Even แล้ว)
        if len(open_positions) >= 2:
            newest = open_positions[-1]
            if newest['side'] == 'BUY' and newest['current_sl'] >= newest['entry']:
                floor_sl = round(newest['current_sl'] - (0.3 * atr), 2)
                for pos in open_positions[:-1]:
                    if floor_sl > pos['current_sl']:
                        pos['current_sl'] = floor_sl
            elif newest['side'] == 'SELL' and newest['current_sl'] <= newest['entry']:
                floor_sl = round(newest['current_sl'] + (0.3 * atr), 2)
                for pos in open_positions[:-1]:
                    if floor_sl < pos['current_sl']:
                        pos['current_sl'] = floor_sl

        return open_positions
