import pandas as pd


def test_numeric_is_done_values_produce_boolean_remaining_mask():
    snapshots = pd.DataFrame({"IsDone": [0, 1, None], "story_points": [3.0, 5.0, 2.0]})

    is_done = snapshots["IsDone"].fillna(False).astype(bool).to_numpy(dtype=bool)

    assert snapshots.loc[~is_done, "story_points"].sum() == 5.0