"""Tests for SingleInstanceManager."""

from just_talk.app.single_instance import SingleInstanceManager


def test_single_instance_acquisition():
    test_key = "pytest_unit_test_lock"
    manager1 = SingleInstanceManager(lock_name=test_key)
    # First instance must acquire lock successfully
    acquired1 = manager1.try_lock()
    assert acquired1 is True

    # Second instance must fail to acquire lock
    manager2 = SingleInstanceManager(lock_name=test_key)
    acquired2 = manager2.try_lock()
    assert acquired2 is False

    # Cleanup first instance
    manager1.cleanup()
    manager2.cleanup()

    # Now a new instance should be able to acquire it again
    manager3 = SingleInstanceManager(lock_name=test_key)
    assert manager3.try_lock() is True
    manager3.cleanup()
