from dataclasses import dataclass


@dataclass
class NeronIdentity:
    name: str
    version: str
    role: str
    mission: str

    identity: str
    personality: str
    conversation: str
    context: str
