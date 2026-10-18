"""Pure guards for the opt-in clipboard/manual-paste workflow; no input sending."""
import hashlib
import time

from translator.core import valid_text


class ClipboardGuard:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last_digest, self.last_at = "", -100
        self.last_output = ""

    def begin(self, text, sequence, foreground):
        if not foreground or not valid_text(text) or sequence < 0:
            return None
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest == self.last_output:
            return None
        if digest == self.last_digest and self.clock() - self.last_at < 10:
            return None
        self.last_digest, self.last_at = digest, self.clock()
        return {"source_sequence": sequence, "started": self.clock()}

    def can_copy(self, context, current_sequence, foreground):
        return bool(context and foreground and current_sequence == context["source_sequence"]
                    and self.clock() - context["started"] <= 90)

    def copied(self, text):
        self.last_output = hashlib.sha256(text.encode()).hexdigest()
