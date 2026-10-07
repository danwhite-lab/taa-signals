import unittest
import pandas as pd
import sys
from types import SimpleNamespace
from unittest.mock import patch, Mock
from haa.data import adjusted_yahoo_daily_bars, download_yahoo_daily_bars


class AdjustedOpenDataTests(unittest.TestCase):
    def fixture(self):
        return pd.DataFrame({'Open':[100.,200.],'Close':[110.,220.],'Adj Close':[55.,55.]},index=pd.to_datetime(['2024-01-02','2024-01-03']))

    def test_adjust_open_with_same_session_close_factor(self):
        close,opening=adjusted_yahoo_daily_bars(self.fixture(),{'QQQ':'QQQ'})
        self.assertEqual(close.QQQ.tolist(),[55.,55.])
        self.assertEqual(opening.QQQ.tolist(),[50.,50.])

    def test_both_multiindex_orientations(self):
        for reversed_order in (False,True):
            raw=self.fixture()
            raw.columns=pd.MultiIndex.from_tuples([(c,'QQQ') if not reversed_order else ('QQQ',c) for c in raw.columns])
            _,opening=adjusted_yahoo_daily_bars(raw,{'NASDAQ':'QQQ'})
            self.assertEqual(opening.NASDAQ.tolist(),[50.,50.])

    def test_missing_open_or_adjusted_close_is_rejected(self):
        for field in ('Open','Adj Close'):
            with self.assertRaisesRegex(ValueError,'next-open execution requires'):
                adjusted_yahoo_daily_bars(self.fixture().drop(columns=field),{'QQQ':'QQQ'})

    def test_downloader_gets_opens_and_closes_from_one_request(self):
        downloader=Mock(return_value=self.fixture())
        with patch.dict(sys.modules,{'yfinance':SimpleNamespace(download=downloader)}):
            close,opening=download_yahoo_daily_bars({'QQQ':'QQQ'})
        downloader.assert_called_once()
        self.assertFalse(downloader.call_args.kwargs['auto_adjust'])
        self.assertEqual(close.QQQ.tolist(),[55.,55.])
        self.assertEqual(opening.QQQ.tolist(),[50.,50.])


if __name__=='__main__': unittest.main()
