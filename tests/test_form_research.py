import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.models.form_features import form_snapshot, visible_history
from src.models.research_store import publish_bundle, verify_bundle, record_shadow


def history():
    return pd.DataFrame([dict(entity_id='anonymous', event_id=str(i), event_time=f'2026-01-{i:02d}T12:00:00Z', available_at=f'2026-01-{i:02d}T23:00:00Z', observed_at=f'2026-01-{i:02d}T22:00:00Z', vote=6+i/10, fantavoto=6+i/10, minutes=0 if i == 4 else 90) for i in range(1, 7)])


def test_future_and_late_revision_do_not_change_past():
    frame = history()
    cutoff = '2026-01-05T00:00:00Z'
    base = form_snapshot(frame.iloc[:4], cutoff)
    late = frame.iloc[:1].copy()
    late['available_at'] = '2026-02-01T00:00:00Z'
    late['vote'] = 10
    pd.testing.assert_frame_equal(base, form_snapshot(pd.concat([frame, late]), cutoff))
    assert base.iloc[0].minutes_events_last3_mean == 60
    assert base.iloc[0].minutes_appearances_last3_mean == 90


def test_missing_and_zero_are_distinct():
    frame = history()
    frame['minutes'] = float('nan')
    row = form_snapshot(frame, '2026-02-01T00:00:00Z').iloc[0]
    assert row.minutes_events_last5_missing
    assert row.minutes_appearances_last5_count == 0
    assert pd.isna(row.minutes_last7d)
    frame['available_at'] = None
    with pytest.raises(ValueError):
        visible_history(frame, '2026-02-01T00:00:00Z')


def test_bundle_integrity_and_immutability(tmp_path):
    weights = tmp_path / 'weights.bin'
    weights.write_bytes(b'anonymous test artifact')
    meta = dict(training_cutoff='2026-01-01', data_hash='test', code_sha='test', features=['x'], model_type='fixture')
    root = tmp_path / 'registry'
    directory = publish_bundle(root, 'v1', {'weights.bin': weights}, meta)
    assert verify_bundle(root, 'v1')['status'] == 'trained'
    with pytest.raises(FileExistsError):
        publish_bundle(root, 'v1', {'weights.bin': weights}, meta)
    (directory / 'weights.bin').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='integrity'):
        verify_bundle(root, 'v1')
    with pytest.raises(ValueError):
        publish_bundle(root, 'v2', {'weights.bin': weights}, dict(meta, status='approved'))


def test_shadow_cannot_be_rewritten_or_backdated(tmp_path):
    cutoff = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    target = record_shadow(tmp_path, 'run1', cutoff, [{'player': 'anonymous', 'mean': 6}], {'source': 'baseline'})
    assert json.loads(target.read_text())['predictions'][0]['mean'] == 6
    with pytest.raises(FileExistsError):
        record_shadow(tmp_path, 'run1', cutoff, [], {})
    with pytest.raises(ValueError):
        record_shadow(tmp_path, 'run2', '2000-01-01T00:00:00Z', [], {})


def test_readiness_excludes_expired_evidence():
    from src.models.readiness import readiness_snapshot
    frame = history().iloc[:1].assign(state='group_training', source_url='https://example.org/club', expires_at='2026-01-03T00:00:00Z', reason='training')
    assert readiness_snapshot(frame, '2026-01-04T00:00:00Z').empty
    row = readiness_snapshot(frame, '2026-01-02T00:00:00Z').iloc[0]
    assert row.physical_condition == 'unobserved'
    assert row.probability_status == 'not_estimated_no_calibrated_model'


def test_expired_new_readiness_does_not_revive_old_state():
    from src.models.readiness import readiness_snapshot
    frame = history().iloc[:2].assign(state=['absent', 'group_training'], source_url='https://example.org/club', expires_at=['2026-02-01T00:00:00Z', '2026-01-03T00:00:00Z'], reason='training')
    assert readiness_snapshot(frame, '2026-01-04T00:00:00Z').empty
