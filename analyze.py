#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Poker Hand Analyzer - Inspect poker session statistics
Usage: python inspect.py --DATE 0407
"""

import argparse
import re
import os
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum
import matplotlib.pyplot as plt
from matplotlib import font_manager
import seaborn as sns
import pandas as pd


class Position(Enum):
    """Poker positions"""
    BTN = "BTN"      # Button
    SB = "SB"        # Small Blind
    BB = "BB"        # Big Blind
    CO = "CO"        # Cutoff
    MP = "MP"        # Middle Position
    LP = "LP"        # Late Position


@dataclass
class Hand:
    """Represents a single poker hand"""
    hand_id: str
    timestamp: str
    table: str
    stakes: str
    hero_seat: int
    hero_position: Position
    hero_cards: str
    hero_action: str  # 'folded', 'won', 'lost'
    hero_profit: float
    hero_net_profit: float
    result_summary: str
    
    def __repr__(self):
        return f"Hand({self.hand_id}) - {self.hero_position.value} - {self.hero_cards} - {self.hero_action}: ${self.hero_profit:.2f}"


class PokerHandParser:
    """Parse poker hand records from text files"""
    
    def __init__(self, date: str):
        self.date = date
        self.base_path = Path(__file__).parent
        self.date_folder = self.base_path / date
        self.hands: List[Hand] = []

    def _configure_plot_font(self):
        """Configure UTF-8 friendly CJK fonts for plotting."""
        preferred_fonts = [
            'Noto Sans CJK TC',
            'Noto Sans CJK SC',
            'Microsoft JhengHei',
            'PingFang TC',
            'Heiti TC',
            'WenQuanYi Zen Hei',
            'SimHei',
            'Arial Unicode MS',
        ]
        available = {f.name for f in font_manager.fontManager.ttflist}
        selected = [name for name in preferred_fonts if name in available]
        # Keep DejaVu Sans as the last fallback for non-CJK glyphs.
        selected.append('DejaVu Sans')

        plt.rcParams['font.sans-serif'] = selected
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['axes.unicode_minus'] = False
        
    def get_position(self, seat: int, button_seat: int, max_seats: int = 6) -> Position:
        """Determine position based on seat number and button position"""
        # In 6-max: BTN, SB, BB, CO, MP, LP
        # Calculate position relative to button
        position_offset = (seat - button_seat) % max_seats
        
        if position_offset == 0:
            return Position.BTN
        elif position_offset == 1:
            return Position.SB
        elif position_offset == 2:
            return Position.BB
        elif position_offset == 3:
            return Position.CO
        elif position_offset == 4:
            return Position.MP
        else:
            return Position.LP

    def _get_big_blind_amount(self) -> float:
        """Extract the big blind amount from parsed stakes."""
        if not self.hands:
            return 0.0

        stakes = self.hands[0].stakes
        stakes_match = re.search(r'\$?([0-9.]+)\s*/\s*\$?([0-9.]+)', stakes)
        if not stakes_match:
            return 0.0

        return float(stakes_match.group(2))

    def _calculate_hero_investment(self, lines: List[str]) -> float:
        """Track Hero's actual chips invested in the pot across streets."""
        hero_invested = 0.0
        hero_street_put = 0.0

        for line in lines:
            if line.startswith('*** FLOP ***') or line.startswith('*** TURN ***') or line.startswith('*** RIVER ***'):
                hero_street_put = 0.0
                continue

            if line.startswith('Hero: posts small blind '):
                amount_match = re.search(r'\$([0-9.]+)', line)
                if amount_match:
                    amount = float(amount_match.group(1))
                    hero_invested += amount
                    hero_street_put += amount
                continue

            if line.startswith('Hero: posts big blind '):
                amount_match = re.search(r'\$([0-9.]+)', line)
                if amount_match:
                    amount = float(amount_match.group(1))
                    hero_invested += amount
                    hero_street_put += amount
                continue

            if line.startswith('Hero: calls '):
                amount_match = re.search(r'\$([0-9.]+)', line)
                if amount_match:
                    amount = float(amount_match.group(1))
                    hero_invested += amount
                    hero_street_put += amount
                continue

            if line.startswith('Hero: bets '):
                amount_match = re.search(r'\$([0-9.]+)', line)
                if amount_match:
                    amount = float(amount_match.group(1))
                    hero_invested += amount
                    hero_street_put += amount
                continue

            if line.startswith('Hero: raises '):
                raise_match = re.search(r'raises \$([0-9.]+) to \$([0-9.]+)', line)
                if raise_match:
                    to_amount = float(raise_match.group(2))
                    hero_invested += to_amount - hero_street_put
                    hero_street_put = to_amount
                continue

            if 'returned to Hero' in line:
                amount_match = re.search(r'\$([0-9.]+)', line)
                if amount_match:
                    amount = float(amount_match.group(1))
                    hero_invested -= amount
                    hero_street_put = max(0.0, hero_street_put - amount)
                continue

        return hero_invested

    def _calculate_hero_cashout_risk(self, lines: List[str]) -> float:
        """Track EV cashout risk paid by Hero outside the pot."""
        cashout_risk = 0.0
        for line in lines:
            if line.startswith('Hero:') and 'Pays Cashout Risk' in line:
                amount_match = re.search(r'\$([0-9.]+)', line)
                if amount_match:
                    cashout_risk += float(amount_match.group(1))
        return cashout_risk

    def _parse_summary_amounts(self, lines: List[str]) -> Tuple[float, float]:
        """Parse total pot and total deductions shown in the summary line."""
        summary_line = next((line for line in lines if line.startswith('Total pot ')), '')
        if not summary_line:
            return 0.0, 0.0

        total_pot_match = re.search(r'Total pot \$([0-9.]+)', summary_line)
        total_pot = float(total_pot_match.group(1)) if total_pot_match else 0.0

        total_deductions = 0.0
        for label in ['Rake', 'Jackpot', 'Bingo', 'Fortune', 'Tax']:
            amount_match = re.search(fr'{label} \$([0-9.]+)', summary_line)
            if amount_match:
                total_deductions += float(amount_match.group(1))

        return total_pot, total_deductions

    def _calculate_total_collected_from_pot(self, lines: List[str]) -> float:
        """Sum all amounts collected from the pot by every player."""
        total_collected = 0.0
        for line in lines:
            amount_match = re.search(r'collected \$([0-9.]+) from pot', line)
            if amount_match:
                total_collected += float(amount_match.group(1))
        return total_collected
    
    def parse_hand(self, hand_text: str) -> Hand:
        """Parse a single hand from text"""
        lines = hand_text.strip().split('\n')
        
        # Extract hand ID and timestamp
        header = lines[0]
        hand_match = re.search(r'Poker Hand #(\w+).*?(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', header)
        if not hand_match:
            return None
        hand_id = hand_match.group(1)
        timestamp = hand_match.group(2)
        
        # Extract stakes
        stakes_match = re.search(r'\(([^)]+)\)', header)
        stakes = stakes_match.group(1) if stakes_match else "Unknown"
        
        # Extract table name
        table_match = re.search(r"Table '([^']+)'", lines[1])
        table = table_match.group(1) if table_match else "Unknown"
        
        # Extract button seat
        button_match = re.search(r'Seat #(\d+)', lines[1])
        button_seat = int(button_match.group(1)) if button_match else 1
        
        # Find Hero's hand and seat
        hero_seat = None
        hero_cards = None
        hero_position = None
        
        for i, line in enumerate(lines):
            if 'Dealt to Hero' in line:
                # Extract cards
                cards_match = re.search(r'\[([^\]]+)\]', line)
                if cards_match:
                    hero_cards = cards_match.group(1)
                
                # Find Hero's seat in previous lines
                for j in range(i-1, max(-1, i-10), -1):
                    if 'Seat' in lines[j]:
                        seat_match = re.search(r'Seat (\d+):', lines[j])
                        if seat_match and 'Hero' in lines[j]:
                            hero_seat = int(seat_match.group(1))
                            break
                break
        
        if hero_seat:
            hero_position = self.get_position(hero_seat, button_seat)
        
        # Track Hero's chips put into the pot and any separate EV cashout fee.
        hero_invested = self._calculate_hero_investment(lines)
        hero_cashout_risk = self._calculate_hero_cashout_risk(lines)
        _total_pot, total_deductions = self._parse_summary_amounts(lines)
        total_collected_from_pot = self._calculate_total_collected_from_pot(lines)
        
        # Determine Hero's action result
        hero_folded = False
        hero_pot_collected = 0.0
        hero_cashout_received = 0.0
        hero_action = "unknown"
        
        # Check if Hero folded
        for line in lines:
            if line.startswith('Hero:') and 'folds' in line:
                hero_folded = True
                hero_action = "folded"
                break
        
        # If not folded, find what Hero collected or received from EV cashout.
        if not hero_folded:
            for line in lines:
                if line.startswith('Hero collected'):
                    amount_match = re.search(r'collected \$([0-9.]+)', line)
                    if amount_match:
                        hero_pot_collected += float(amount_match.group(1))
                elif line.startswith('Hero:') and 'Receives Cashout' in line:
                    amount_match = re.search(r'\$([0-9.]+)', line)
                    if amount_match:
                        hero_cashout_received += float(amount_match.group(1))

            if hero_pot_collected + hero_cashout_received > 0.0:
                hero_action = "won"
            
            # If no collection line, Hero lost at showdown
            if hero_pot_collected + hero_cashout_received == 0.0 and not hero_folded:
                hero_action = "lost"
        
        # External "Winloss" matches gross pot share before rake/jackpot deductions
        # and excludes separate EV cashout risk fees.
        hero_fee_share = 0.0
        if hero_pot_collected > 0.0 and total_collected_from_pot > 0.0:
            hero_fee_share = total_deductions * (hero_pot_collected / total_collected_from_pot)

        hero_gross_profit = (hero_pot_collected + hero_cashout_received + hero_fee_share) - hero_invested
        hero_net_profit = (hero_pot_collected + hero_cashout_received) - hero_invested - hero_cashout_risk
        
        # Get summary
        result_summary = lines[-1] if lines else ""
        if 'Seat' in result_summary and 'Hero' in result_summary:
            pass
        else:
            result_summary = ""
        
        return Hand(
            hand_id=hand_id,
            timestamp=timestamp,
            table=table,
            stakes=stakes,
            hero_seat=hero_seat,
            hero_position=hero_position,
            hero_cards=hero_cards,
            hero_action=hero_action,
            hero_profit=hero_gross_profit,
            hero_net_profit=hero_net_profit,
            result_summary=result_summary
        )
    
    def load_hands(self):
        """Load all hands from the date folder"""
        if not self.date_folder.exists():
            print(f"❌ 資料夾不存在: {self.date_folder}")
            return False
        
        files = list(self.date_folder.glob("GG*.txt"))
        if not files:
            print(f"⚠️  沒有找到牌局檔案")
            return False
        
        print(f"📂 找到 {len(files)} 個檔案")
        
        total_hands = 0
        for file_path in files:
            with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                content = f.read()
            
            # Split by double newline to separate hands
            hands_text = content.split('\n\n')
            
            for hand_text in hands_text:
                if hand_text.strip() and 'Poker Hand' in hand_text:
                    hand = self.parse_hand(hand_text)
                    if hand:
                        self.hands.append(hand)
                        total_hands += 1
        
        print(f"✅ 成功解析 {total_hands} 手牌\n")
        return True
    
    def print_statistics(self):
        """Print detailed statistics"""
        if not self.hands:
            print("沒有牌局數據")
            return
        
        # Basic stats
        total_hands = len(self.hands)
        hero_folded = sum(1 for h in self.hands if h.hero_action == 'folded')
        hero_won = sum(1 for h in self.hands if h.hero_action == 'won')
        hero_lost = sum(1 for h in self.hands if h.hero_action == 'lost')
        
        total_profit = sum(h.hero_profit for h in self.hands)
        total_net_profit = sum(h.hero_net_profit for h in self.hands)
        avg_profit = total_profit / total_hands if total_hands > 0 else 0
        avg_net_profit = total_net_profit / total_hands if total_hands > 0 else 0
        big_blind = self._get_big_blind_amount()
        gross_bb_per_100 = ((total_profit / big_blind) / total_hands * 100) if total_hands > 0 and big_blind > 0 else 0
        net_bb_per_100 = ((total_net_profit / big_blind) / total_hands * 100) if total_hands > 0 and big_blind > 0 else 0
        
        # Win rate (hands where Hero went to showdown)
        showdown_hands = hero_won + hero_lost
        win_rate = (hero_won / showdown_hands * 100) if showdown_hands > 0 else 0
        
        # Position statistics
        position_stats = defaultdict(lambda: {'played': 0, 'won': 0, 'profit': 0})
        for hand in self.hands:
            if hand.hero_position:
                pos_key = hand.hero_position.value
                position_stats[pos_key]['played'] += 1
                if hand.hero_action == 'won':
                    position_stats[pos_key]['won'] += 1
                position_stats[pos_key]['profit'] += hand.hero_profit
        
        # Starting hand statistics
        hand_stats = defaultdict(lambda: {'count': 0, 'won': 0, 'profit': 0})
        for hand in self.hands:
            if hand.hero_cards:
                hand_key = hand.hero_cards
                hand_stats[hand_key]['count'] += 1
                if hand.hero_action == 'won':
                    hand_stats[hand_key]['won'] += 1
                hand_stats[hand_key]['profit'] += hand.hero_profit
        
        # Print overview
        print("=" * 60)
        print(f"📊 牌局統計 - {self.date}")
        print("=" * 60)
        print(f"總手數:        {total_hands}")
        print(f"棄牌:          {hero_folded} ({hero_folded/total_hands*100:.1f}%)")
        print(f"進到show:      {showdown_hands} ({showdown_hands/total_hands*100:.1f}%)")
        print(f"  └─ 贏:       {hero_won} ({win_rate:.1f}%)")
        print(f"  └─ 輸:       {hero_lost} ({100-win_rate:.1f}%)")
        print()
        print(f"總毛盈虧:      ${total_profit:+.2f}")
        print(f"總淨盈虧:      ${total_net_profit:+.2f}")
        print(f"平均毛盈虧/手: ${avg_profit:+.2f}")
        print(f"平均淨盈虧/手: ${avg_net_profit:+.2f}")
        print(f"毛 BB/100:     {gross_bb_per_100:+.2f}")
        print(f"淨 BB/100:     {net_bb_per_100:+.2f}")
        
        # Position breakdown
        print()
        print("=" * 60)
        print("📍 位置分析")
        print("=" * 60)
        for pos in ['BTN', 'CO', 'MP', 'LP', 'SB', 'BB']:
            if pos in position_stats:
                stats = position_stats[pos]
                pos_played = stats['played']
                showdown_in_pos = sum(1 for h in self.hands 
                                     if h.hero_position and h.hero_position.value == pos 
                                     and h.hero_action in ['won', 'lost'])
                win_pct = (stats['won'] / showdown_in_pos * 100) if showdown_in_pos > 0 else 0
                print(f"{pos:3} - {pos_played:2}手 | ${stats['profit']:+.2f} | 勝率: {win_pct:.0f}%")
        
        # Top hands
        print()
        print("=" * 60)
        print("🎴 起手牌TOP 10")
        print("=" * 60)
        sorted_hands = sorted(hand_stats.items(), 
                            key=lambda x: x[1]['profit'], 
                            reverse=True)[:10]
        for hand_key, stats in sorted_hands:
            win_pct = (stats['won'] / stats['count'] * 100) if stats['count'] > 0 else 0
            print(f"{hand_key:4} - {stats['count']:2}手 | ${stats['profit']:+.2f} | 勝率: {win_pct:.0f}%")
        
        print()
        print("=" * 60)

    def plot_statistics(self):
        """Generate visualization charts for PnL analysis"""
        if not self.hands:
            print("沒有牌局數據")
            return
        
        # Set style
        sns.set_style("whitegrid")
        # Re-apply the CJK-capable font after seaborn resets sans-serif fonts.
        self._configure_plot_font()
        plt.rcParams['figure.figsize'] = (15, 12)
        plt.rcParams['font.size'] = 10
        
        # Create subplots
        fig = plt.figure(figsize=(16, 12))
        
        # 1. PnL by Position (Bar chart)
        ax1 = plt.subplot(2, 3, 1)
        position_stats = defaultdict(lambda: {'profit': 0, 'count': 0})
        for hand in self.hands:
            if hand.hero_position:
                pos_key = hand.hero_position.value
                position_stats[pos_key]['profit'] += hand.hero_profit
                position_stats[pos_key]['count'] += 1
        
        positions = ['BTN', 'CO', 'MP', 'LP', 'SB', 'BB']
        profits = [position_stats[pos]['profit'] for pos in positions if pos in position_stats]
        pos_filtered = [pos for pos in positions if pos in position_stats]
        
        colors = ['green' if p > 0 else 'red' for p in profits]
        bars1 = ax1.bar(pos_filtered, profits, color=colors, alpha=0.7, edgecolor='black')
        ax1.set_title('各位置盈虧 (Position PnL)', fontsize=12, fontweight='bold')
        ax1.set_ylabel('盈虧 ($)')
        ax1.set_xlabel('位置')
        ax1.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        
        # 2. PnL Distribution (Histogram)
        ax2 = plt.subplot(2, 3, 2)
        hand_profits = [h.hero_profit for h in self.hands]
        ax2.hist(hand_profits, bins=50, alpha=0.7, color='steelblue', edgecolor='black')
        ax2.set_title('盈虧分佈 (PnL Distribution)', fontsize=12, fontweight='bold')
        ax2.set_xlabel('盈虧 ($)')
        ax2.set_ylabel('手數')
        ax2.axvline(x=0, color='red', linestyle='--', linewidth=1.5)
        
        # 3. Win/Loss/Fold Breakdown (Pie chart)
        ax3 = plt.subplot(2, 3, 3)
        hero_folded = sum(1 for h in self.hands if h.hero_action == 'folded')
        hero_won = sum(1 for h in self.hands if h.hero_action == 'won')
        hero_lost = sum(1 for h in self.hands if h.hero_action == 'lost')
        
        sizes = [hero_folded, hero_won, hero_lost]
        labels = [f'Fold\n({hero_folded})', f'Win\n({hero_won})', f'Loss\n({hero_lost})']
        colors_pie = ['#ff9999', '#66b3ff', '#ffcc99']
        ax3.pie(sizes, labels=labels, colors=colors_pie, autopct='%1.1f%%', startangle=90)
        ax3.set_title('Action Distribution', fontsize=12, fontweight='bold')
        
        # 4. Cumulative PnL
        ax4 = plt.subplot(2, 3, 4)
        sorted_hands = sorted(self.hands, key=lambda h: h.timestamp)
        cumulative_profit = []
        cum_sum = 0
        for hand in sorted_hands:
            cum_sum += hand.hero_profit
            cumulative_profit.append(cum_sum)
        
        ax4.plot(range(len(cumulative_profit)), cumulative_profit, linewidth=2, color='steelblue')
        ax4.fill_between(range(len(cumulative_profit)), cumulative_profit, alpha=0.3, color='steelblue')
        ax4.set_title('Cumulative PnL', fontsize=12, fontweight='bold')
        ax4.set_xlabel('Hand #')
        ax4.set_ylabel('Cumulative PnL ($)')
        ax4.axhline(y=0, color='red', linestyle='--', linewidth=1)
        ax4.grid(True, alpha=0.3)
        
        # 5. Top 10 Hands by Profit
        ax5 = plt.subplot(2, 3, 5)
        hand_stats = defaultdict(lambda: {'profit': 0, 'count': 0})
        for hand in self.hands:
            if hand.hero_cards:
                hand_key = hand.hero_cards
                hand_stats[hand_key]['profit'] += hand.hero_profit
                hand_stats[hand_key]['count'] += 1
        
        sorted_hands_stats = sorted(hand_stats.items(), 
                                     key=lambda x: x[1]['profit'], 
                                     reverse=True)[:10]
        hand_names = [f"{h[0]}\n(x{h[1]['count']})" for h in sorted_hands_stats]
        hand_profits = [h[1]['profit'] for h in sorted_hands_stats]
        
        colors_hand = ['green' if p > 0 else 'red' for p in hand_profits]
        ax5.bar(range(len(hand_names)), hand_profits, color=colors_hand, alpha=0.7, edgecolor='black')
        ax5.set_xticks(range(len(hand_names)))
        ax5.set_xticklabels(hand_names, rotation=45, ha='right', fontsize=9)
        ax5.set_title('TOP 10 Starting Hands', fontsize=12, fontweight='bold')
        ax5.set_ylabel('PnL ($)')
        ax5.set_xlabel('Hand')
        ax5.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        
        # 6. Position Win Rate
        ax6 = plt.subplot(2, 3, 6)
        position_winrate = {}
        for pos in ['BTN', 'CO', 'MP', 'LP', 'SB', 'BB']:
            showdown_hands = sum(1 for h in self.hands 
                                if h.hero_position and h.hero_position.value == pos 
                                and h.hero_action in ['won', 'lost'])
            wins = sum(1 for h in self.hands 
                      if h.hero_position and h.hero_position.value == pos 
                      and h.hero_action == 'won')
            if showdown_hands > 0:
                position_winrate[pos] = (wins / showdown_hands) * 100
        
        pos_list = list(position_winrate.keys())
        wr_list = list(position_winrate.values())
        colors_wr = ['green' if w > 50 else 'red' for w in wr_list]
        
        ax6.bar(pos_list, wr_list, color=colors_wr, alpha=0.7, edgecolor='black')
        ax6.set_title('Position Win Rate', fontsize=12, fontweight='bold')
        ax6.set_ylabel('Win Rate (%)')
        ax6.set_xlabel('Position')
        ax6.axhline(y=50, color='black', linestyle='--', linewidth=1)
        ax6.set_ylim(0, 100)
        
        # Add overall stats as text
        total_profit = sum(h.hero_profit for h in self.hands)
        date_str = self.date if len(self.date) == 4 else self.date
        title = f'Poker Analysis - {date_str} | Total PnL: ${total_profit:+.2f} | Hands: {len(self.hands)}'
        fig.suptitle(title, fontsize=14, fontweight='bold', y=0.98)
        
        plt.tight_layout(rect=[0, 0.03, 1, 0.96])
        
        # Save figure
        output_path = self.base_path / f'pnl_{self.date}.png'
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"✅ Chart saved: {output_path}")
        
        plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="分析 Poker 牌局統計",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python analyze.py --DATE 0407
  python analyze.py --DATE 0408 --plot
        """
    )
    
    parser.add_argument('--DATE', type=str, required=True,
                      help='日期資料夾 (例如: 0407, 0408)')
    parser.add_argument('--plot', action='store_true',
                      help='生成 PnL 視覺化圖表')
    
    args = parser.parse_args()
    
    analyzer = PokerHandParser(args.DATE)
    
    if analyzer.load_hands():
        analyzer.print_statistics()
        if args.plot:
            print("\n📊 正在生成圖表...")
            analyzer.plot_statistics()
    else:
        print(f"❌ 無法載入資料夾: {args.DATE}")


if __name__ == '__main__':
    main()
