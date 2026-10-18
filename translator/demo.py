from translator.core import ApiFailure

# Clearly synthetic samples, never presented as a real Dota integration.
SAMPLES = [
    ("Нужен вард на Рошане, потом пушим мид", "Need a ward at Roshan, then we push mid."),
    ("No peleen sin BKB, esperen mi TP", "Don't fight without BKB; wait for my TP."),
    ("先打肉山，然后一起推中", "Take Roshan first, then push mid together."),
    ("gg wp", "gg wp"),
]
OUTGOING = {
    "Russian": "Пушим мид после Рошана.",
    "Spanish": "Pusheen mid después de Roshan.",
    "Chinese": "打完肉山后推中。",
    "English": "Push mid after Roshan.",
}


class DemoApi:
    async def translate(self, text, target):
        if target == "English":
            for original, translation in SAMPLES:
                if text == original:
                    return translation
        if text.lower().strip().rstrip(".") == "push mid after roshan":
            return OUTGOING[target]
        raise ApiFailure()  # Demo intentionally cannot translate arbitrary input.

    async def close(self):
        pass
