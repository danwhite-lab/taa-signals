"""Freeze inputs for the health-only cash reconstruction. No live app requests.

Usage: PYTHONPATH=src python scripts/build_cm_cash_health_inputs.py \
    --factors-zip /path/F-F_Research_Data_Factors_CSV.zip --bil-pickle /path/bil.pkl

BIL input is yf.download('BIL', start='2007-05-01', end='2016-08-01',
                       auto_adjust=False). Only actual last-session prices count.
"""
import argparse
import csv
import io
from zipfile import ZipFile

import pandas as pd

from haa.deep_history import DEEP_HISTORY_DIR
from haa.market_sessions import us_equity_sessions


def build(factors_zip, bil_pickle):
    with ZipFile(factors_zip) as archive:
        raw = archive.read(archive.namelist()[0]).decode('utf-8-sig')
    rows = []
    for row in csv.reader(io.StringIO(raw)):
        if len(row) == 5 and row[0].strip().isdigit() and len(row[0].strip()) == 6:
            stamp = pd.to_datetime(row[0].strip(), format='%Y%m')
            if pd.Timestamp('1928-04-01') <= stamp <= pd.Timestamp('2007-05-01'):
                rows.append((stamp.year, stamp.month, float(row[-1]) / 100))
    pd.DataFrame(rows, columns=['year', 'month', 'nominalReturn']).to_csv(
        DEEP_HISTORY_DIR / 'cm_cash_health_tbill_proxy.csv', index=False)
    raw = pd.read_pickle(bil_pickle)
    prices = raw['Adj Close'].squeeze().dropna()
    sessions = us_equity_sessions('2007-05-01', '2016-07-31')
    ends = sessions.to_series().groupby(sessions.to_period('M')).last()
    records = []
    for month in pd.period_range('2007-06', '2016-07', freq='M'):
        prior, date = ends[month - 1], ends[month]
        old, new = float(prices.loc[prior]), float(prices.loc[date])
        records.append(dict(year=month.year, month=month.month, nominalReturn=new / old - 1,
                            previousObservationDate=str(prior.date()), previousAdjustedClose=old,
                            observationDate=str(date.date()), adjustedClose=new,
                            source='Yahoo Finance adjusted close', ticker='BIL', currency='USD',
                            history_kind='Actual ETF history'))
    pd.DataFrame(records).to_csv(DEEP_HISTORY_DIR / 'cm_cash_health_bil.csv', index=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factors-zip', required=True)
    parser.add_argument('--bil-pickle', required=True)
    args = parser.parse_args()
    build(args.factors_zip, args.bil_pickle)
