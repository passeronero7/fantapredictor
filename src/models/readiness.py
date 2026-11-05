"""Observed availability evidence, distinct from an uncalibrated health score."""
from __future__ import annotations

import pandas as pd

from src.models.form_features import visible_history

STATES = {'absent', 'individual_training', 'group_training', 'called_up', 'minutes_limited', 'unknown'}


def readiness_snapshot(evidence: pd.DataFrame, cutoff) -> pd.DataFrame:
    required = {'state', 'source_url', 'expires_at', 'reason'}
    if required - set(evidence):
        raise ValueError(f'Missing evidence columns: {sorted(required - set(evidence))}')
    data = visible_history(evidence, cutoff)
    if not data.state.isin(STATES).all():
        raise ValueError('Unknown availability state')
    if data.source_url.isna().any() or data.source_url.astype(str).str.strip().eq('').any():
        raise ValueError('Availability requires a source URL')
    data = data.sort_values(['available_at', 'event_time']).drop_duplicates('entity_id', keep='last')
    expiration = pd.to_datetime(data.expires_at, utc=True, errors='raise')
    data = data[expiration.notna() & (expiration > pd.Timestamp(cutoff))]
    output = data[['entity_id', 'state', 'reason', 'source_url', 'available_at', 'expires_at']].copy()
    output['physical_condition'] = 'unobserved'
    output['probability_status'] = 'not_estimated_no_calibrated_model'
    return output.reset_index(drop=True)
