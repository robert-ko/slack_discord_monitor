#!/usr/bin/env python3
import sys
import csv
from stock_data_fetcher import StockDataFetcher

def test_external_data():
    fetcher = StockDataFetcher()
    
    # Test with a few real symbols from the CSV
    test_symbols = ['AGAE', 'BJDX', 'MPU', 'BHAT']
    
    for symbol in test_symbols:
        print(f"\n--- Testing {symbol} ---")
        try:
            data = fetcher.get_stock_info(symbol)
            print(f"Float shares: {data['float_shares']:,}")
            print(f"Short interest shares: {data['short_int_shares']:,}")
            print(f"Short interest %: {data['short_int_pct']:.2f}%")
        except Exception as e:
            print(f"Error for {symbol}: {e}")

if __name__ == "__main__":
    test_external_data()