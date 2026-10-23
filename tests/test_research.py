from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

from order_ui.research import ResearchData, chart_summary, fear_summary, CNN_URL
from order_ui.research_symbols import UNDERLYINGS
from toss_fractional.client import TossClient
from toss_fractional.errors import TradingError


def candles(count=200):
    day = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {"candles": [{"timestamp": (day+timedelta(days=i)).isoformat(),
                         "closePrice": str(i+1), "currency": "USD"} for i in reversed(range(count))]}


def fear_payload():
    return {"fear_and_greed": {"score": 32.2, "rating": "fear", "previous_close": 34,
                                "timestamp": "2026-10-15T19:44:38+00:00"},
            "fear_and_greed_historical": {"data": [{"x": 1792093478000, "y": 32.2}]}}


class ResearchTests(unittest.TestCase):
    def test_adjusted_daily_request_uses_official_parameters_without_account(self):
        client = TossClient(None)
        calls = []
        client._request = lambda *args, **kwargs: calls.append((args, kwargs)) or candles()
        client.get_daily_candles('NVDA')
        self.assertEqual(calls, [(('GET', '/api/v1/candles'), {'params': {
            'symbol':'NVDA','interval':'1d','count':200,'adjusted':'true'}})])

    def test_average_orders_by_time_and_uses_latest_120_bars(self):
        result = chart_summary(candles(), 'NVDA')
        self.assertEqual(result['lastClose'], '200')
        avg = result['averages'][2]
        self.assertEqual(Decimal(avg['value']), Decimal('140.5'))
        self.assertEqual(Decimal(avg['distancePct']), (Decimal(200)/Decimal('140.5')-1)*100)
        self.assertEqual(result['history'][0]['value'], 1)

    def test_short_history_does_not_fabricate_long_average(self):
        result = chart_summary(candles(60), 'IPO')
        self.assertIsNotNone(result['averages'][1]['value'])
        self.assertIsNone(result['averages'][2]['value'])
        self.assertIsNone(result['averages'][2]['distancePct'])

    def test_bad_candles_do_not_produce_plausible_summary(self):
        for value in ['NaN', 'Infinity', '-1', '0', None, True, '1e999999', '1e-999999', '9' * 1000]:
            data = candles(); data['candles'][0]['closePrice'] = value
            with self.assertRaises(ValueError): chart_summary(data, 'NVDA')
        data = candles(); data['candles'][0]['currency'] = 'KRW'
        with self.assertRaises(ValueError): chart_summary(data, 'NVDA')
        data = candles(); data['candles'].append(data['candles'][0]); data['candles'].pop(1)
        with self.assertRaises(ValueError): chart_summary(data, 'NVDA')

    def test_chart_cache_is_bounded_and_isolated_by_broker_identity(self):
        calls=[]; now=[0]
        broker=SimpleNamespace(get_daily_candles=lambda symbol: calls.append(symbol) or candles())
        research=ResearchData(clock=lambda:now[0])
        research.chart(broker,'NVDA'); research.chart(broker,'NVDA')
        self.assertEqual(len(calls),1)
        research.chart(SimpleNamespace(get_daily_candles=broker.get_daily_candles),'NVDA')
        self.assertEqual(len(calls),2)
        now[0]=301;research.chart(broker,'NVDA');self.assertEqual(len(calls),3)
        for i in range(40):research.chart(broker,f'T{i}')
        self.assertLessEqual(len(research._charts),32)
        with self.assertRaises(ValueError):research.chart(broker,'../orders')
        bad=SimpleNamespace(get_daily_candles=lambda symbol:{'items':[]})
        with self.assertRaises(TradingError):research.chart(bad,'NVDA')

    def test_cnn_failure_cache_stale_and_no_broker_headers(self):
        now=[datetime(2026,10,15,20,tzinfo=timezone.utc).timestamp()]; calls=[]; status=[200]
        def get(url,**kwargs):
            calls.append((url,kwargs))
            return SimpleNamespace(status_code=status[0],json=fear_payload)
        data=ResearchData(session=SimpleNamespace(get=get),clock=lambda:now[0])
        self.assertFalse(data.fear()['stale']);data.fear()
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],CNN_URL)
        self.assertEqual(calls[0][1]['headers'],{'Accept':'application/json'})
        self.assertEqual(calls[0][1]['max_response_bytes'],1024*1024)
        now[0]+=901;status[0]=403
        result=data.fear()
        self.assertEqual(result['score'],32.2);self.assertTrue(result['stale'])
        self.assertTrue(data.fear()['unavailable']);self.assertEqual(len(calls),2)

    def test_underlying_uses_actual_prices_and_cache_does_not_mix_selections(self):
        calls=[]
        broker=SimpleNamespace(get_daily_candles=lambda symbol:calls.append(symbol) or candles())
        research=ResearchData()
        result=research.chart(broker,'GOOW')
        self.assertEqual(calls,['GOOGL'])
        self.assertEqual(result['symbol'],'GOOGL')
        self.assertEqual(result['selectedSymbol'],'GOOW')
        self.assertEqual(result['underlying']['name'],'알파벳 A')
        self.assertEqual(result['lastClose'],'200')
        self.assertEqual(Decimal(result['averages'][2]['value']),Decimal('140.5'))
        direct=research.chart(broker,'GOOGL')
        self.assertEqual(calls,['GOOGL'])
        self.assertEqual(direct['selectedSymbol'],'GOOGL')
        self.assertIsNone(direct['underlying'])
        self.assertEqual(research.chart(broker,'GOOW')['selectedSymbol'],'GOOW')
        own=research.chart(broker,'GOOW','self')
        self.assertEqual(own['symbol'],'GOOW')
        self.assertEqual(own['basis'],'self')
        self.assertEqual(calls,['GOOGL','GOOW'])

    def test_reviewed_underlyings_only_and_invalid_basis_does_not_fetch(self):
        calls=[]
        broker=SimpleNamespace(get_daily_candles=lambda symbol:calls.append(symbol) or candles())
        research=ResearchData()
        for symbol,(underlying,_) in UNDERLYINGS.items():
            self.assertEqual(research.chart(broker,symbol)['symbol'],underlying)
        self.assertEqual(research.chart(broker,'AVGW')['symbol'],'AVGO')
        for symbol in ['NVDA','ETHU','FAKEW']:
            result=research.chart(broker,symbol)
            self.assertEqual(result['symbol'],symbol)
            self.assertIsNone(result['underlying'])
        before=len(calls)
        for basis in ['',None,'SELF','unknown',[]]:
            with self.assertRaises(ValueError):research.chart(broker,'GOOW',basis)
        self.assertEqual(len(calls),before)

    def test_underlying_failure_never_silently_substitutes_etf_candles(self):
        calls=[]
        broker=SimpleNamespace(get_daily_candles=lambda symbol:calls.append(symbol) or {'candles':[]})
        with self.assertRaisesRegex(TradingError,'GOOGL'):
            ResearchData().chart(broker,'GOOW')
        self.assertEqual(calls,['GOOGL'])

    def test_cnn_unavailable_and_malformed_do_not_fabricate_zero(self):
        data=ResearchData(session=SimpleNamespace(get=lambda *args,**kwargs:SimpleNamespace(status_code=403)))
        self.assertNotIn('score',data.fear())
        for score in [-1,101,'NaN',None,True]:
            payload=fear_payload();payload['fear_and_greed']['score']=score
            with self.assertRaises(ValueError):fear_summary(payload)

    def test_old_source_date_is_marked_even_after_successful_fetch(self):
        now=datetime(2026,10,19,tzinfo=timezone.utc).timestamp()
        data=ResearchData(session=SimpleNamespace(get=lambda *args,**kwargs:SimpleNamespace(status_code=200,json=fear_payload)),clock=lambda:now)
        self.assertTrue(data.fear()['stale'])
