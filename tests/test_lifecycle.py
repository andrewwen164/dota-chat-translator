import signal
import unittest

from translator.lifecycle import ShutdownSignals


class SignalTests(unittest.TestCase):
    def test_sigint_requests_shutdown_without_keyboard_interrupt(self):
        callbacks = []
        with ShutdownSignals() as shutdown:
            signal.raise_signal(signal.SIGINT)
            self.assertTrue(shutdown.requested)
            self.assertEqual(callbacks, [])  # No GUI operation in signal handler.
            shutdown.poll(lambda: callbacks.append("quit"))
            self.assertEqual(callbacks, ["quit"])

    def test_repeated_interrupts_only_quit_once(self):
        callbacks = []
        with ShutdownSignals() as shutdown:
            signal.raise_signal(signal.SIGINT)
            shutdown.poll(lambda: callbacks.append("quit"))
            signal.raise_signal(signal.SIGINT)
            shutdown.poll(lambda: callbacks.append("quit"))
        self.assertEqual(callbacks, ["quit"])

    def test_previous_handler_restored(self):
        previous = signal.getsignal(signal.SIGINT)
        with ShutdownSignals():
            self.assertNotEqual(signal.getsignal(signal.SIGINT), previous)
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)

    def test_no_signal_does_not_quit(self):
        callbacks = []
        with ShutdownSignals() as shutdown:
            shutdown.poll(lambda: callbacks.append("quit"))
        self.assertEqual(callbacks, [])
