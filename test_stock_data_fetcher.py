#!/usr/bin/env python3
import unittest
import time
from unittest.mock import patch, MagicMock
import sys
import os

# Add the current directory to the path so we can import our module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from stock_data_fetcher import StockDataFetcher
    YFINANCE_AVAILABLE = True
except ImportError as e:
    print(f"Import error: {e}")
    YFINANCE_AVAILABLE = False

class TestStockDataFetcher(unittest.TestCase):
    
    def setUp(self):
        if not YFINANCE_AVAILABLE:
            self.skipTest("yfinance not available")
        self.fetcher = StockDataFetcher()
    
    def test_cache_functionality(self):
        """Test that caching works correctly"""
        # Mock the yfinance ticker
        mock_info = {
            'floatShares': 1000000,
            'sharesOutstanding': 1500000,
            'shortInterest': 50000
        }
        
        with patch('yfinance.Ticker') as mock_ticker:
            mock_ticker.return_value.info = mock_info
            
            # First call should fetch from API
            result1 = self.fetcher.get_stock_info('AAPL')
            
            # Second call should use cache
            result2 = self.fetcher.get_stock_info('AAPL')
            
            # Should only call yfinance once due to caching
            self.assertEqual(mock_ticker.call_count, 1)
            self.assertEqual(result1, result2)
    
    def test_short_interest_calculation(self):
        """Test short interest percentage calculation"""
        mock_info = {
            'floatShares': 1000000,
            'sharesOutstanding': 1500000,
            'shortInterest': 100000  # 10% short interest
        }
        
        with patch('yfinance.Ticker') as mock_ticker:
            mock_ticker.return_value.info = mock_info
            
            result = self.fetcher.get_stock_info('AAPL')
            
            expected_short_pct = (100000 / 1000000) * 100  # 10%
            self.assertEqual(result['short_int_pct'], expected_short_pct)
            self.assertEqual(result['float_shares'], 1000000)
            self.assertEqual(result['short_int_shares'], 100000)
    
    def test_missing_data_handling(self):
        """Test handling of missing data"""
        mock_info = {
            'floatShares': 0,  # Missing float shares
            'sharesOutstanding': 1500000,
            # shortInterest missing entirely
        }
        
        with patch('yfinance.Ticker') as mock_ticker:
            mock_ticker.return_value.info = mock_info
            
            result = self.fetcher.get_stock_info('AAPL')
            
            self.assertEqual(result['float_shares'], 0)
            self.assertEqual(result['short_int_shares'], 0)
            self.assertEqual(result['short_int_pct'], 0.0)
    
    def test_api_error_handling(self):
        """Test handling of API errors"""
        with patch('yfinance.Ticker') as mock_ticker:
            mock_ticker.side_effect = Exception("API Error")
            
            result = self.fetcher.get_stock_info('INVALID')
            
            # Should return default values on error
            expected = {
                'float_shares': 0,
                'shares_outstanding': 0,
                'short_int_shares': 0,
                'short_int_pct': 0.0
            }
            self.assertEqual(result, expected)
    
    def test_cache_expiry(self):
        """Test that cache expires correctly"""
        # Set a very short cache expiry for testing
        self.fetcher.cache_expiry = 0.1  # 100ms
        
        mock_info = {
            'floatShares': 1000000,
            'sharesOutstanding': 1500000,
            'shortInterest': 50000
        }
        
        with patch('yfinance.Ticker') as mock_ticker:
            mock_ticker.return_value.info = mock_info
            
            # First call
            result1 = self.fetcher.get_stock_info('AAPL')
            
            # Wait for cache to expire
            time.sleep(0.2)
            
            # Second call should fetch again due to expired cache
            result2 = self.fetcher.get_stock_info('AAPL')
            
            # Should call yfinance twice due to cache expiry
            self.assertEqual(mock_ticker.call_count, 2)

class TestRealAPICall(unittest.TestCase):
    """Test with real API calls (optional, may be slow)"""
    
    def setUp(self):
        if not YFINANCE_AVAILABLE:
            self.skipTest("yfinance not available")
        self.fetcher = StockDataFetcher()
    
    @unittest.skip("Uncomment to test real API calls")
    def test_real_api_call(self):
        """Test with a real API call to Yahoo Finance"""
        # Test with a well-known stock
        result = self.fetcher.get_stock_info('AAPL')
        
        # Apple should have valid data
        self.assertGreater(result['float_shares'], 0)
        self.assertGreater(result['shares_outstanding'], 0)
        # Short interest may or may not be available
        
        print(f"AAPL data: {result}")

def run_quick_test():
    """Quick test function to check if everything is working"""
    print("Testing StockDataFetcher...")
    
    if not YFINANCE_AVAILABLE:
        print("❌ yfinance not available - install with: pip install yfinance")
        return False
    
    try:
        fetcher = StockDataFetcher()
        
        # Test with a mock to avoid API calls
        mock_info = {
            'floatShares': 1000000,
            'sharesOutstanding': 1500000,
            'shortInterest': 100000
        }
        
        with patch('yfinance.Ticker') as mock_ticker:
            mock_ticker.return_value.info = mock_info
            result = fetcher.get_stock_info('TEST')
            
            if result['float_shares'] == 1000000 and result['short_int_pct'] == 10.0:
                print("✅ StockDataFetcher working correctly")
                return True
            else:
                print(f"❌ Unexpected result: {result}")
                return False
                
    except Exception as e:
        print(f"❌ Error testing StockDataFetcher: {e}")
        return False

if __name__ == '__main__':
    # Run quick test first
    if run_quick_test():
        print("\nRunning full unit tests...")
        unittest.main(verbosity=2)
    else:
        print("Quick test failed - check your setup")
        sys.exit(1)