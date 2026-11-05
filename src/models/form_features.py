"""Point-in-time multi-window features; input rows must have observed availability."""
from __future__ import annotations

import numpy as np
import pandas as pd

WINDOWS = (3, 5, 10, 20)


def visible_history(frame: pd.DataFrame, cutoff) -> pd.DataFrame:
    """Keep the latest revision actually known before a prediction cutoff.

    Date-only evidence is not silently upgraded to an intraday timestamp.
    Callers own the eligibility denominator and stable entity/event identifiers.
    """
    required = {'entity_id', 'event_id', 'event_time', 'available_at', 'observed_at'}
    missing = required - set(frame)
    if missing:
        raise ValueError(f'Missing temporal columns: {sorted(missing)}')
    data = frame.copy()
    if data[['entity_id', 'event_id']].isna().any().any():
        raise ValueError('Missing entity or event identity')
    for col in ('event_time', 'available_at', 'observed_at'):
        if any(pd.Timestamp(value).tzinfo is None for value in data[col]):
            raise ValueError(f'{col} must include timezones')
        data[col] = pd.to_datetime(data[col], utc=True, errors='raise')
        if data[col].isna().any():
            raise ValueError(f'Unknown {col}: cannot reconstruct historical availability')
    if (data.available_at < data.observed_at).any():
        raise ValueError('available_at precedes observed_at')
    t = pd.Timestamp(cutoff)
    if t.tzinfo is None:
        raise ValueError('cutoff must include a timezone')
    data = data[(data.event_time < t) & (data.available_at <= t)]
    if data.duplicated(['entity_id', 'event_id', 'available_at']).any():
        raise ValueError('Ambiguous revisions at the same availability timestamp')
    return data.sort_values(['available_at']).drop_duplicates(['entity_id', 'event_id'], keep='last').sort_values(['event_time', 'event_id'])


def form_snapshot(frame: pd.DataFrame, cutoff, metrics=('vote', 'fantavoto', 'minutes'),
                  windows=WINDOWS) -> pd.DataFrame:
    """Summarize observed events and appearances separately, retaining missingness.

    Rows must include non-playing eligible events for event-window denominators.
    Missing minutes never imply a non-appearance. No prior is fabricated here.
    """
    data = visible_history(frame, cutoff)
    missing = set(metrics) - set(data)
    if missing:
        raise ValueError(f'Missing metric columns: {sorted(missing)}')
    if any(not isinstance(n, int) or n < 1 for n in windows):
        raise ValueError('Windows must be positive integers')
    records = []
    for entity, block in data.groupby('entity_id', sort=False):
        result = {'entity_id': entity, 'events_observed': len(block),
                  'data_age_days': (pd.Timestamp(cutoff) - block.event_time.max()).total_seconds() / 86400}
        for metric in metrics:
            values = pd.to_numeric(block[metric], errors='raise')
            if np.isinf(values.to_numpy(dtype=float)).any():
                raise ValueError(f'Infinite {metric}')
            valid = values.dropna()
            result[f'{metric}_history_mean'] = valid.mean()
            for n in windows:
                tail = values.tail(n)
                prefix = f'{metric}_events_last{n}'
                result[prefix + '_mean'] = tail.mean()
                result[prefix + '_count'] = int(tail.count())
                result[prefix + '_coverage'] = float(tail.count() / len(tail))
                result[prefix + '_std'] = tail.std(ddof=1)
                result[prefix + '_missing'] = bool(tail.count() == 0)
            for h in (3, 5, 10):
                result[f'{metric}_ewma{h}'] = values.ewm(halflife=h, adjust=False, ignore_na=False).mean().iloc[-1]
            if 5 in windows and 20 in windows:
                result[f'{metric}_delta5_20'] = (result[f'{metric}_events_last5_mean'] - result[f'{metric}_events_last20_mean']) if values.tail(5).count() >= 3 else np.nan
        if 'minutes' in block:
            minutes = pd.to_numeric(block.minutes, errors='raise')
            block = block.assign(minutes=minutes)
            if ((minutes < 0) | (minutes > 130)).any():
                raise ValueError('Invalid minutes')
            appeared = block.loc[minutes.gt(0)]
            for metric in metrics:
                for n in windows:
                    tail = pd.to_numeric(appeared[metric], errors='raise').tail(n)
                    result[f'{metric}_appearances_last{n}_mean'] = tail.mean()
                    result[f'{metric}_appearances_last{n}_count'] = int(tail.count())
            for days in (7, 14, 28):
                recent = block[block.event_time >= pd.Timestamp(cutoff) - pd.Timedelta(days=days)]
                result[f'minutes_last{days}d'] = recent.minutes.sum(min_count=1)
                result[f'minutes_last{days}d_count'] = int(recent.minutes.count())
            result['physical_condition'] = 'unobserved'
        records.append(result)
    return pd.DataFrame(records)
