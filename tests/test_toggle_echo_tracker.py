from pistomp_midi_bridge.midi import ToggleEchoTracker


def test_first_press_for_a_cc_is_not_a_miss():
    tracker = ToggleEchoTracker()

    assert tracker.observe_press(cc_num=110, value_before_send=0.0) is False


def test_press_with_changed_value_is_not_a_miss():
    tracker = ToggleEchoTracker()
    tracker.observe_press(cc_num=110, value_before_send=0.0)

    assert tracker.observe_press(cc_num=110, value_before_send=1.0) is False


def test_press_with_unchanged_value_is_a_miss():
    tracker = ToggleEchoTracker()
    tracker.observe_press(cc_num=110, value_before_send=0.0)

    assert tracker.observe_press(cc_num=110, value_before_send=0.0) is True


def test_repeated_unchanged_value_warns_only_once():
    tracker = ToggleEchoTracker()
    tracker.observe_press(cc_num=110, value_before_send=0.0)

    assert tracker.observe_press(cc_num=110, value_before_send=0.0) is True
    assert tracker.observe_press(cc_num=110, value_before_send=0.0) is False


def test_value_changing_again_rearms_the_warning():
    tracker = ToggleEchoTracker()
    tracker.observe_press(cc_num=110, value_before_send=0.0)
    tracker.observe_press(cc_num=110, value_before_send=0.0)  # first miss, warned

    assert (
        tracker.observe_press(cc_num=110, value_before_send=1.0) is False
    )  # recovered
    assert (
        tracker.observe_press(cc_num=110, value_before_send=1.0) is True
    )  # miss again


def test_each_cc_is_tracked_independently():
    tracker = ToggleEchoTracker()
    tracker.observe_press(cc_num=110, value_before_send=0.0)
    tracker.observe_press(cc_num=111, value_before_send=0.0)

    assert tracker.observe_press(cc_num=110, value_before_send=0.0) is True
    assert tracker.observe_press(cc_num=111, value_before_send=1.0) is False


def test_reset_clears_all_tracked_state():
    """Called on pedalboard load: values from the old board are meaningless
    for judging whether the new board's mappings are working."""
    tracker = ToggleEchoTracker()
    tracker.observe_press(cc_num=110, value_before_send=0.0)
    tracker.observe_press(cc_num=110, value_before_send=0.0)  # warned

    tracker.reset()

    assert tracker.observe_press(cc_num=110, value_before_send=0.0) is False
