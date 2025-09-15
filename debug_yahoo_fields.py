#!/usr/bin/env python3
import yfinance as yf
import json

def debug_yahoo_fields(symbol):
    """Debug what fields are available from Yahoo Finance"""
    print(f"\n=== Debugging Yahoo Finance data for {symbol} ===")
    
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # Print all available fields
        print("\nAll available fields:")
        for key, value in sorted(info.items()):
            if 'short' in key.lower() or 'float' in key.lower() or 'share' in key.lower():
                print(f"  {key}: {value}")
        
        # Look for potential short interest fields
        short_fields = [k for k in info.keys() if 'short' in k.lower()]
        print(f"\nFields containing 'short': {short_fields}")
        
        # Look for potential float fields  
        float_fields = [k for k in info.keys() if 'float' in k.lower()]
        print(f"Fields containing 'float': {float_fields}")
        
        # Look for share-related fields
        share_fields = [k for k in info.keys() if 'share' in k.lower()]
        print(f"Fields containing 'share': {share_fields}")
        
        # Print specific fields we're looking for
        print(f"\nSpecific fields:")
        print(f"  floatShares: {info.get('floatShares', 'NOT FOUND')}")
        print(f"  shortInterest: {info.get('shortInterest', 'NOT FOUND')}")
        print(f"  shortRatio: {info.get('shortRatio', 'NOT FOUND')}")
        print(f"  shortPercentOfFloat: {info.get('shortPercentOfFloat', 'NOT FOUND')}")
        print(f"  sharesShort: {info.get('sharesShort', 'NOT FOUND')}")
        print(f"  sharesShortPriorMonth: {info.get('sharesShortPriorMonth', 'NOT FOUND')}")
        
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")

if __name__ == "__main__":
    # Test with AGAE
    debug_yahoo_fields('AGAE')
    
    # Test with a few other symbols for comparison
    for symbol in ['AAPL', 'TSLA']:
        debug_yahoo_fields(symbol)