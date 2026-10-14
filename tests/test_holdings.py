from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from toss_fractional import FractionalTradeService, Settings, TradingError
from test_orders import FakeBroker


class HoldingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.broker=FakeBroker()
        self.service=FractionalTradeService(self.broker,Settings(data_dir=Path(self.temp.name)))

    def test_currency_separation_and_native_currency_returns(self):
        korean=deepcopy(self.broker.holdings_data['items'][0])
        korean.update(symbol='005930',name='삼성전자',marketCountry='KR',currency='KRW',quantity='2',marketValue={'purchaseAmount':'100000','amount':'120000'},profitLoss={'amount':'20000','rate':'0.2'})
        self.broker.holdings_data['items'].append(korean)
        result=self.service.holdings()
        self.assertEqual(result['summary']['USD']['marketValue'],'20')
        self.assertEqual(result['summary']['KRW']['marketValue'],'120000')
        self.assertEqual(Decimal(result['summary']['USD']['profitLossRate']),Decimal(-1)/Decimal(21))
        self.assertTrue(result['items'][0]['orderable'])
        self.assertFalse(result['items'][1]['orderable'])
        self.assertEqual(self.broker.calls,[])

    def test_empty_portfolio_has_zero_value_and_no_percentage(self):
        self.broker.holdings_data={'items':[]}
        result=self.service.holdings()
        self.assertEqual(result['summary']['USD'],{'marketValue':'0','profitLoss':'0','profitLossRate':None,'count':0})

    def test_missing_values_are_not_invented_as_zero(self):
        item=self.broker.holdings_data['items'][0]
        item['profitLoss']['amount']=None
        item['marketValue']['amount']=None
        result=self.service.holdings()
        self.assertIsNone(result['items'][0]['marketValue'])
        self.assertIsNone(result['summary']['USD']['profitLoss'])
        self.assertIsNone(result['summary']['USD']['profitLossRate'])

    def test_invalid_response_and_numbers_fail_closed(self):
        original=deepcopy(self.broker.holdings_data)
        for payload in (None,{}, {'items':{}}, {'items':[None]}, {'items':[{'symbol':[]}]}):
            self.broker.holdings_data=payload
            with self.assertRaises(TradingError): self.service.holdings()
        for invalid in ('NaN','Infinity','-1','bad'):
            self.broker.holdings_data=deepcopy(original)
            self.broker.holdings_data['items'][0]['quantity']=invalid
            with self.assertRaises(TradingError): self.service.holdings()

    def test_unknown_account_rejected_before_portfolio_call(self):
        with self.assertRaises(ValueError): self.service.holdings('unknown')
        self.assertEqual(self.broker.calls,[])
