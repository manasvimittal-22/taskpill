from taskpill.services.idle_quit import IdleQuit


def test_quits_after_the_idle_time(clock):
    busy = [False]
    q = IdleQuit(clock, lambda: busy[0], minutes=10)
    clock.advance(9 * 60)
    assert not q.should_quit()
    clock.advance(60)
    assert q.should_quit()


def test_being_busy_resets_the_wait(clock):
    busy = [False]
    q = IdleQuit(clock, lambda: busy[0], minutes=10)
    clock.advance(9 * 60)
    busy[0] = True
    assert not q.should_quit()
    busy[0] = False
    assert not q.should_quit()  # idle again from now
    clock.advance(9 * 60)
    assert not q.should_quit()
    clock.advance(60)
    assert q.should_quit()


def test_never(clock):
    q = IdleQuit(clock, lambda: False, minutes=0)
    clock.advance(10**6)
    assert not q.should_quit()


def test_minutes_can_change(clock):
    q = IdleQuit(clock, lambda: False, minutes=60)
    clock.advance(6 * 60)
    q.set_minutes(5)
    assert q.should_quit()
