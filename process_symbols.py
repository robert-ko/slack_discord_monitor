#!/usr/bin/env python3
import sys
import csv
import curses
import time
import threading
from collections import defaultdict

try:
    from stock_data_fetcher import StockDataFetcher
    EXTERNAL_DATA_AVAILABLE = True
except ImportError:
    EXTERNAL_DATA_AVAILABLE = False
    print("Warning: yfinance not available. Install with: pip install yfinance")

class SymbolDashboard:
    def __init__(self, csv_file=None, fetch_external_data=False):
        self.symbol_stats = {}
        self.running = True
        self.data_lock = threading.Lock()
        self.update_needed = False
        self.csv_file = csv_file
        self.fetch_external_data = fetch_external_data and EXTERNAL_DATA_AVAILABLE
        self.data_fetcher = StockDataFetcher() if self.fetch_external_data else None
        self.external_data_cache = {}
        
    def process_csv_data(self):
        if self.csv_file:
            with open(self.csv_file, 'r') as f:
                reader = csv.DictReader(f)
                self._process_reader(reader)
        else:
            self._process_stdin()
    
    def _process_reader(self, reader):
        # For file input, process all rows
        for row in reader:
            if not self.running:
                break
            self._process_row(row)
    
    def _process_stdin(self):
        reader = csv.DictReader(sys.stdin)
        
        # Process initial data
        try:
            for row in reader:
                if not self.running:
                    break
                self._process_row(row)
        except StopIteration:
            pass
        
        # Keep the thread alive - dashboard will handle quit via 'q' key
        while self.running:
            time.sleep(0.1)
    
    def _process_row(self, row):
        symbol = row.get('Symbol', '').strip().replace('"', '')
        price_str = row.get('Price($)', '').strip()
        event_time = row.get('EventTime(HH:MM:SS)', '').strip().replace('"', '')
        
        # Skip empty or invalid symbols
        if not symbol or len(symbol) > 10 or symbol in ['***', 'N/A']:
            return
            
        if not price_str:
            return
            
        try:
            # Remove any quotes and commas that might be in the price field
            price_clean = price_str.replace('"', '').replace(',', '').strip()
            if not price_clean or price_clean in ['***', 'N/A']:
                return
            price = float(price_clean)
            # Skip unrealistic prices
            if price <= 0 or price > 10000:
                return
        except (ValueError, TypeError):
            return
            
        # Parse additional fields
        def safe_parse_float(value, default=0.0):
            try:
                clean_val = str(value).replace('"', '').replace(',', '').strip()
                if clean_val in ['***', 'N/A', '']:
                    return default
                return float(clean_val)
            except (ValueError, TypeError):
                return default
                
        rvol_yday = safe_parse_float(row.get('RVOL %(vs yday)', ''))
        rvol_30d = safe_parse_float(row.get('RVOL %(vs 30D)', ''))
        float_shares = safe_parse_float(row.get('Float(Shares)', ''))
        short_int_pct = safe_parse_float(row.get('ShortInt(%)', ''))  # Use existing percentage column
        volume_shares = safe_parse_float(row.get('Volume(Shares)', ''))
            
        # Fetch external data once per symbol if enabled and CSV data is missing
        if self.fetch_external_data and (float_shares == 0 or short_int_pct == 0):
            if symbol not in self.external_data_cache:
                try:
                    # Fetch once and cache permanently
                    ext_data = self.data_fetcher.get_stock_info(symbol)
                    self.external_data_cache[symbol] = ext_data
                except Exception:
                    # Cache empty data to avoid repeated failures
                    self.external_data_cache[symbol] = {
                        'float_shares': 0,
                        'shares_outstanding': 0,
                        'short_int_shares': 0,
                        'short_int_pct': 0.0
                    }
            
            # Use cached external data
            ext_data = self.external_data_cache[symbol]
            if float_shares == 0 and ext_data['float_shares'] > 0:
                float_shares = ext_data['float_shares']
            if short_int_pct == 0 and ext_data['short_int_pct'] > 0:
                short_int_pct = ext_data['short_int_pct']

        with self.data_lock:
            if symbol in self.symbol_stats:
                self.symbol_stats[symbol]['count'] += 1
                self.symbol_stats[symbol]['last_time'] = event_time
                self.symbol_stats[symbol]['price'] = price
                self.symbol_stats[symbol]['rvol_yday'] = rvol_yday
                self.symbol_stats[symbol]['rvol_30d'] = rvol_30d
                self.symbol_stats[symbol]['float_shares'] = float_shares
                self.symbol_stats[symbol]['short_int_pct'] = short_int_pct
                self.symbol_stats[symbol]['volume_shares'] = volume_shares
            else:
                self.symbol_stats[symbol] = {
                    'count': 1,
                    'first_price': price,
                    'price': price,
                    'last_time': event_time,
                    'rvol_yday': rvol_yday,
                    'rvol_30d': rvol_30d,
                    'float_shares': float_shares,
                    'short_int_pct': short_int_pct,
                    'volume_shares': volume_shares
                }
            self.update_needed = True
        
        # Small delay to make updates visible and reduce flicker
        time.sleep(0.005)
    
    def draw_dashboard(self, stdscr):
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(True)  # Non-blocking input
        
        # Initialize color pairs for gradient
        if curses.has_colors():
            curses.start_color()
            curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)      # Newest
            curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)   
            curses.init_pair(3, curses.COLOR_GREEN, curses.COLOR_BLACK)    
            curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLACK)     
            curses.init_pair(5, curses.COLOR_BLUE, curses.COLOR_BLACK)     
            curses.init_pair(6, curses.COLOR_MAGENTA, curses.COLOR_BLACK)  # Oldest
        
        last_screen = ""
        
        while self.running:
            # Only redraw if data has changed
            with self.data_lock:
                need_update = self.update_needed
                if need_update:
                    self.update_needed = False
                    
                    # Build screen content
                    height, width = stdscr.getmaxyx()
                    screen_content = []
                    
                    # Header
                    header = "Symbol Dashboard - Press Ctrl+C to quit"
                    screen_content.append((0, (width - len(header)) // 2, header, curses.A_BOLD))
                    headers = f"{'Symbol':<8} {'Cnt':<4} {'Price':<8} {'Vol(M)':<8} {'RVOL-Y':<8} {'RVOL-30':<8} {'Float(M)':<9} {'Short%':<7}"
                    screen_content.append((2, 0, headers, curses.A_UNDERLINE))
                    
                    # Symbols - sort by most recent timestamp first
                    sorted_symbols = sorted(self.symbol_stats.items(), 
                                          key=lambda x: x[1].get('last_time', ''), reverse=True)
                    
                    max_items = min(len(sorted_symbols), height-5)
                    for i, (symbol, stats) in enumerate(sorted_symbols[:max_items]):
                        row = 3 + i
                        if row >= height - 2:
                            break
                        
                        # Calculate color based on position (gradient from newest to oldest)
                        if curses.has_colors() and max_items > 1:
                            # Map position to color pair (1-6)
                            color_ratio = i / (max_items - 1)  # 0.0 to 1.0
                            color_pair = min(6, int(color_ratio * 5) + 1)  # 1 to 6
                            attr = curses.color_pair(color_pair)
                        else:
                            attr = curses.A_NORMAL
                        
                        price = stats.get('price', stats['first_price'])
                        volume_shares = stats.get('volume_shares', 0.0)
                        rvol_yday = stats.get('rvol_yday', 0.0)
                        rvol_30d = stats.get('rvol_30d', 0.0)
                        float_shares = stats.get('float_shares', 0.0)
                        short_int_pct = stats.get('short_int_pct', 0.0)
                        
                        # Format values with N/A for zero/missing data
                        vol_m_str = f"{volume_shares/1000000:.1f}" if volume_shares > 0 else "N/A"
                        rvol_y_str = f"{rvol_yday:.1f}" if rvol_yday > 0 else "N/A"
                        rvol_30_str = f"{rvol_30d:.1f}" if rvol_30d > 0 else "N/A"
                        float_m_str = f"{float_shares/1000000:.1f}" if float_shares > 0 else "N/A"
                        short_str = f"{short_int_pct:.1f}" if short_int_pct > 0 else "N/A"
                        
                        line = f"{symbol:<8} {stats['count']:<4} ${price:<7.2f} {vol_m_str:<8} {rvol_y_str:<8} {rvol_30_str:<8} {float_m_str:<9} {short_str:<7}"
                        screen_content.append((row, 0, line, attr))
                    
                    # Footer
                    if height > 5:
                        footer = f"Total symbols: {len(self.symbol_stats)}"
                        screen_content.append((height-2, 0, footer, curses.A_DIM))
                    
                    # Convert to string for comparison
                    screen_str = str(screen_content)
                    
                    # Only update screen if content changed
                    if screen_str != last_screen:
                        stdscr.erase()
                        for row, col, text, attr in screen_content:
                            try:
                                stdscr.addstr(row, col, text, attr)
                            except curses.error:
                                pass
                        stdscr.refresh()
                        last_screen = screen_str
            
            # Small delay to prevent high CPU usage
            time.sleep(0.05)
    
    def run(self, stdscr):
        # Start CSV processing in background thread
        csv_thread = threading.Thread(target=self.process_csv_data)
        csv_thread.daemon = True
        csv_thread.start()
        
        # Run dashboard
        self.draw_dashboard(stdscr)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Symbol Dashboard')
    parser.add_argument('csv_file', nargs='?', help='CSV file to process')
    parser.add_argument('--fetch-external', action='store_true', 
                       help='Fetch float shares and short interest from Yahoo Finance')
    
    args = parser.parse_args()
    
    dashboard = SymbolDashboard(args.csv_file, fetch_external_data=args.fetch_external)
    try:
        curses.wrapper(dashboard.run)
    except KeyboardInterrupt:
        dashboard.running = False

if __name__ == "__main__":
    main()