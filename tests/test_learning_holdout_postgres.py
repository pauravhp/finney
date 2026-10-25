from uuid import uuid4

import psycopg
import pytest
from test_finance_postgres import database as database  # noqa: PLC0414
from test_finance_postgres import state as state  # noqa: PLC0414


def test_final_dataset_is_consumed_once_across_candidates(state):
    conn, org, run, _ = state
    first = conn.execute("select claim_finance_learning_holdout(%s,%s,%s,%s,%s)",
        (org,run,uuid4(),"a"*64,"b"*64)).fetchone()[0]
    assert first["claimed"]
    again = conn.execute("select claim_finance_learning_holdout(%s,%s,%s,%s,%s)",
        (org,run,uuid4(),"a"*64,"c"*64)).fetchone()[0]
    assert not again["claimed"]
    conn.execute("reset role")
    conn.execute("set role authenticated")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select claim_finance_learning_holdout(%s,%s,%s,%s,%s)",
            (org,run,uuid4(),"d"*64,"e"*64))
