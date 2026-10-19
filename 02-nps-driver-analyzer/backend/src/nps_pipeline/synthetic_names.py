"""Demo name vocabulary shared by survey generation and PII redaction.

Keep the canonical sequences stable so seeded survey generation is unchanged.
Accented spellings are accepted by the redactor without changing generated data.
This is a synthetic vocabulary, not a general-purpose person-name detector.
"""

FIRST_NAMES = ("Maria", "Jose", "Laura", "Miguel", "Ana", "Luis", "Carmen", "Pedro")
LAST_NAMES = ("Gomez", "Herrera", "Vargas", "Morales", "Silva", "Torres", "Ramos")

FIRST_NAME_SPELLINGS = (*FIRST_NAMES, "María", "José")
LAST_NAME_SPELLINGS = (*LAST_NAMES, "Gómez")
