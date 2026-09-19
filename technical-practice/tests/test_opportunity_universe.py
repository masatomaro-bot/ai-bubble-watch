"""Coverage and freshness of reused market data, without network access."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import market_climate as mc


def frame(end='2026-09-17', volume=1_000_000):
    return pd.DataFrame({'Close': [100.0]*260, 'Volume': [volume]*260},
                        index=pd.bdate_range(end=end, periods=260))


def test_export_is_not_top_twenty_and_filters_stale_and_illiquid():
    frames = {f'T{i:02}': frame() for i in range(25)}
    frames['STALE'] = frame(end='2026-09-16')
    frames['THIN'] = frame(volume=1)
    ranks = {t: 95.0 for t in frames}
    result = mc.build_opportunity_universe(frames, ranks, '2026-09-17', 'test')
    assert result['eligible_count'] == 25
    assert result['ranked_count'] == 27
    assert result['excluded_stale_count'] == 1
    assert all(r['observed_date'] == '2026-09-17' for r in result['rows'])
    assert not {'STALE', 'THIN'} & {r['ticker'] for r in result['rows']}


def test_empty_export_does_not_invent_rows():
    assert mc.build_opportunity_universe({}, {}, '2026-09-17', 'test')['rows'] == []
