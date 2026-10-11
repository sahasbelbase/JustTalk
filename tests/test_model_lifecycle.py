from just_talk.model_lifecycle import ModelLifecycle


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeModel:
    def __init__(self, name):
        self.name, self.loaded, self.unloads = name, True, 0

    def target(self):
        return (self.name, lambda: self.loaded, self.unload)

    def unload(self):
        self.loaded = False
        self.unloads += 1


def make(minutes=10):
    clock, model = Clock(), FakeModel("stt")
    return clock, model, ModelLifecycle(lambda: [model.target()], lambda: minutes, clock)


def test_unloads_after_idle_limit():
    clock, model, lc = make(10)
    clock.t += 9 * 60
    assert lc.unload_if_idle() == []
    clock.t += 2 * 60
    assert lc.unload_if_idle() == ["stt"]
    assert not model.loaded


def test_never_unloads_when_setting_is_zero():
    clock, model, lc = make(0)
    clock.t += 10_000
    assert lc.unload_if_idle() == []
    assert model.loaded


def test_busy_job_blocks_unload_and_restarts_idle_time():
    clock, model, lc = make(5)
    with lc.busy():
        clock.t += 60 * 60
        assert lc.unload_if_idle() == []
    # the job just ended: idle time starts from now, not from before the job
    clock.t += 4 * 60
    assert lc.unload_if_idle() == []
    clock.t += 2 * 60
    assert lc.unload_if_idle() == ["stt"]


def test_touch_resets_idle_time():
    clock, model, lc = make(5)
    clock.t += 4 * 60
    lc.touch()
    clock.t += 4 * 60
    assert lc.unload_if_idle() == []


def test_only_loaded_models_are_unloaded_and_failures_dont_stop_others():
    clock = Clock()
    a, b = FakeModel("a"), FakeModel("b")
    a.loaded = False

    def boom():
        raise RuntimeError("x")

    lc = ModelLifecycle(
        lambda: [("bad", lambda: True, boom), a.target(), b.target()], lambda: 1, clock
    )
    clock.t += 120
    assert lc.unload_if_idle() == ["b"]
    assert a.unloads == 0


def test_second_check_after_unload_is_a_noop():
    clock, model, lc = make(1)
    clock.t += 120
    lc.unload_if_idle()
    clock.t += 120
    assert lc.unload_if_idle() == []
    assert model.unloads == 1
