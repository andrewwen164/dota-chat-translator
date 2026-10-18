"""Keep console signals out of Qt's native callback stack."""
import signal


class ShutdownSignals:
    def __init__(self):
        self.requested = False
        self.handled = False
        self.previous = {}

    def request(self, signum, frame):
        # A Python signal can arrive inside any Qt override. Only set a flag;
        # let a normal GUI timer perform teardown outside the native callback.
        self.requested = True

    def poll(self, quit_callback):
        if self.requested and not self.handled:
            self.handled = True
            quit_callback()

    def __enter__(self):
        signals = [signal.SIGINT]
        if hasattr(signal, "SIGBREAK"):
            signals.append(signal.SIGBREAK)
        for signum in signals:
            self.previous[signum] = signal.signal(signum, self.request)
        return self

    def __exit__(self, *exc):
        for signum, previous in self.previous.items():
            signal.signal(signum, previous)
