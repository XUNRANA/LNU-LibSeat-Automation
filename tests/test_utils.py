import datetime

import core.utils as utils


def test_get_beijing_time_tz_aware():
    t = utils.get_beijing_time()
    assert t.tzinfo is not None
    # Beijing is UTC+8
    assert t.utcoffset() == datetime.timedelta(hours=8)
