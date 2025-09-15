#!/usr/bin/env python3
import yfinance as yf
import requests
from threading import Lock
import time

class StockDataFetcher:
    def __init__(self):
        self.cache = {}
        self.cache_lock = Lock()
        self.cache_expiry = 3600  # 1 hour cache
        
    def get_stock_info(self, symbol):
        """Get stock info from Yahoo Finance with caching"""
        with self.cache_lock:
            # Check cache first
            if symbol in self.cache:
                data, timestamp = self.cache[symbol]
                if time.time() - timestamp < self.cache_expiry:
                    return data
        
        try:
            # Fetch from Yahoo Finance
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Extract relevant data with correct field names
            float_shares = info.get('floatShares', 0)
            shares_outstanding = info.get('sharesOutstanding', 0)
            short_int_shares = info.get('sharesShort', 0)  # Correct field name
            short_pct_float = info.get('shortPercentOfFloat', 0)  # Direct percentage
            
            # Use direct percentage if available, otherwise calculate
            short_int_pct = 0.0
            if short_pct_float > 0:
                short_int_pct = short_pct_float * 100  # Convert from decimal to percentage
            elif float_shares > 0 and short_int_shares > 0:
                short_int_pct = (short_int_shares / float_shares) * 100
            
            data = {
                'float_shares': float_shares,
                'shares_outstanding': shares_outstanding,
                'short_int_shares': short_int_shares,
                'short_int_pct': short_int_pct
            }
            
            # Cache the result
            with self.cache_lock:
                self.cache[symbol] = (data, time.time())
            
            return data
            
        except Exception as e:
            print(f"Error fetching data for {symbol}: {e}")
            return {
                'float_shares': 0,
                'shares_outstanding': 0,
                'short_int_shares': 0,
                'short_int_pct': 0.0
            }
    
    def get_finviz_data(self, symbol):
        """Alternative: scrape data from Finviz (simpler but less reliable)"""
        try:
            url = f"https://finviz.com/quote.ashx?t={symbol}"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                # This would require HTML parsing - keeping it simple for now
                # Could use BeautifulSoup to extract specific fields
                pass
                
        except Exception as e:
            print(f"Error fetching Finviz data for {symbol}: {e}")
            
        return None