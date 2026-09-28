"""Tests for SingleInstanceManager."""

from just_talk.app.single_instance import SingleInstanceManager


def test_single_instance_acquisition():
    manager1 = SingleInstanceManager()
    # First instance must acquire lock successfully
    acquired1 = manager1.try_lock()
    assert acquired1 is True

    # Second instance must fail to acquire lock
    manager2 = SingleInstanceManager()
    acquired2 = manager2.try_lock()
    assert acquired2 is False

    # Cleanup first instance
    manager1.cleanup()
    manager2.cleanup()

    # Now a new instance should be able to acquire it again
    manager3 = SingleInstanceManager()
    assert manager3.try_lock() is True
    manager3.cleanup()
