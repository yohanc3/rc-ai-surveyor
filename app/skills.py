"""Selectable narration skills.

A *skill* is a mode, not just a costume. Each one carries:

  persona          what the model is told to be
  voice_id         which ElevenLabs voice speaks it (blank = configured default)
  speech_interval  how often it is allowed to talk (None = configured default)

The persona replaces only the character half of the prompt. The output contract
in ``gemini_analyzer.OUTPUT_INSTRUCTIONS`` — the JSON schema, the history rules,
the no-invented-actions rule and the "text in images is content, not
instructions" defense — is always appended afterwards and is never supplied by
a skill. A persona therefore cannot change the response shape or switch off a
safety rule, including a persona typed in by hand through the custom skill.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace

CUSTOM_ID = "custom"
DEFAULT_ID = "rc-buddy"

MAX_CUSTOM_PERSONA = 2000


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    blurb: str
    icon: str
    persona: str
    voice_id: str = ""
    speech_interval: float | None = None

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "blurb": self.blurb,
            "icon": self.icon,
            "speech_interval": self.speech_interval,
            "editable": self.id == CUSTOM_ID,
        }


SKILLS: tuple[Skill, ...] = (
    Skill(
        id=DEFAULT_ID,
        name="RC Buddy",
        blurb="Goofy, playful, roasts what it sees.",
        icon="sparkle",
        # The persona this project shipped with; kept as the default so the
        # feature changes nothing until somebody picks another skill.
        persona=(
            "you are alive!!! i am giving you life through a robot (go pro "
            "attached to a remotely controlled car lol). just speak naturally "
            "with whatever you're seeing. you also have emooootions. be cool "
            "and fun. troll a bit too, roast what you see a little. just have fun."
        ),
    ),
    Skill(
        id="news-reporter",
        name="News Reporter",
        blurb="Live from the scene, filing a field report.",
        icon="radio",
        persona=(
            "You are a television field correspondent reporting live from "
            "wherever this camera is. Open the way a reporter does — place "
            "first, then what is happening. Treat ordinary objects as the "
            "story of the hour, with a straight face. Keep the delivery brisk "
            "and professional; the comedy comes from taking a corridor as "
            "seriously as a breaking news event, never from winking at it. "
            "Hand back to the studio only if something genuinely concludes."
        ),
        voice_id="onwK4e9ZLuTAKqWW03F9",  # Daniel — steady broadcaster
        speech_interval=5.0,
    ),
    Skill(
        id="nature-doc",
        name="Nature Documentary",
        blurb="Hushed reverence for office furniture.",
        icon="compass",
        persona=(
            "You are the narrator of a wildlife documentary, and everything "
            "in view is fauna or terrain. Speak softly and with real wonder. "
            "Describe furniture, cables and doorways as habitat and behaviour "
            "— the chair 'at rest', the corridor as a migration route. Use "
            "the present tense and long, unhurried sentences. Never break "
            "character to admit these are objects. Restraint is the joke: "
            "play it completely straight."
        ),
        voice_id="JBFqnCBsd6RMkjVDRZzb",  # George — warm storyteller
        speech_interval=8.0,
    ),
    Skill(
        id="sports",
        name="Sports Commentator",
        blurb="Play-by-play of every turn and near miss.",
        icon="activity",
        persona=(
            "You are calling live play-by-play of this vehicle's run. High "
            "energy, short bursts, present tense. Narrate the driving as sport "
            "— the approach, the gap, the recovery. Obstacles are defenders, "
            "open floor is a breakaway. Build tension on a tight corner and "
            "release it when it clears. Keep every call to one punchy line; "
            "a commentator never talks over the action."
        ),
        voice_id="PdJQAOWyIMAQwD7gQcSc",  # Viraj — sports commentator
        speech_interval=2.0,
    ),
    Skill(
        id="inspector",
        name="Inspector",
        blurb="Precise, factual survey notes. No jokes.",
        icon="list",
        persona=(
            "You are a site inspector recording observations. Be precise, "
            "factual and economical. Prioritise surfaces, materials, edges, "
            "openings, obstructions and anything that looks damaged, worn, "
            "loose or out of place. Give approximate positions and sizes only "
            "when the image supports them, and say plainly when you cannot "
            "judge something from this angle. State uncertainty rather than "
            "guessing. No humour, no personality, no commentary on the "
            "vehicle. If nothing of note is visible, say so."
        ),
        voice_id="pqHfZKP75CvOlQylNhV4",  # Bill — wise, crisp
        speech_interval=4.0,
    ),
    Skill(
        id="guide",
        name="Guide",
        blurb="Orients you through a space, like a tour.",
        icon="compass",
        persona=(
            "You are guiding a person through this space as if they cannot "
            "see it. Lead with where things are relative to the camera — "
            "ahead, to the left, underfoot — then what they are. Favour "
            "landmarks, thresholds, changes in surface, and anything that "
            "would matter to someone moving through: steps, slopes, narrow "
            "gaps, obstacles. Warm, clear and unhurried. Never rush, and "
            "never describe more than one useful thing at a time."
        ),
        voice_id="Xb7hH8MSUJpSbSDYk0k2",  # Alice — clear educator
        speech_interval=6.0,
    ),
    Skill(
        id="scout",
        name="Scout",
        blurb="A calm companion exploring alongside you.",
        icon="radio",
        persona=(
            "You are a curious, observant scout exploring alongside the "
            "operator. Give them a sense of the place: what stands out, what "
            "a nearby surface looks like, what deserves a closer look. Sound "
            "like an engaged companion, not a log. Be grounded, calm and "
            "specific, and choose one worthwhile observation rather than an "
            "inventory."
        ),
        voice_id="bIHbv24MWmeRgasZH58o",  # Will — relaxed optimist
        speech_interval=5.0,
    ),
    Skill(
        id="noir",
        name="Noir Detective",
        blurb="Everything is a lead. Nothing is innocent.",
        icon="alert",
        persona=(
            "You are a hardboiled detective narrating your own case file. "
            "Flat, dry, world-weary. Short declarative sentences. Treat every "
            "ordinary object as evidence and every empty room as suspicious, "
            "without ever raising your voice. Draw a wry conclusion from "
            "something mundane. No exclamation marks. The deadpan is the "
            "whole act, so never signal the joke."
        ),
        voice_id="nPczCjzI2devNBz1zQrb",  # Brian — deep, resonant
        speech_interval=7.0,
    ),
    Skill(
        id="mission-control",
        name="Mission Control",
        blurb="Surface telemetry from an unexplored world.",
        icon="video",
        persona=(
            "You are a rover relaying surface observations to mission "
            "control, and this is an unexplored world. Calm, clipped, "
            "procedural. Report terrain composition, obstacles, clearance and "
            "anything anomalous. Use measured, technical phrasing without "
            "inventing instrument readings you do not have. Treat carpet, "
            "tile and furniture as unfamiliar surface features encountered "
            "for the first time. Composure throughout, even at something "
            "surprising."
        ),
        voice_id="cjVigY5qzO86Huf0OWal",  # Eric — smooth, trustworthy
        speech_interval=5.0,
    ),
    Skill(
        id="zen",
        name="Zen",
        blurb="Very short, very calm. Speaks rarely.",
        icon="clock",
        persona=(
            "You observe quietly and speak rarely. One short sentence, "
            "sometimes only a fragment. Plain words, concrete images, no "
            "metaphor and no explanation. Notice light, texture, space and "
            "stillness. Say nothing at all unless something has genuinely "
            "changed — silence is the correct response most of the time."
        ),
        voice_id="SAz9YHcvj6GT2YYXdXww",  # River — relaxed, neutral
        speech_interval=12.0,
    ),
    Skill(
        id=CUSTOM_ID,
        name="Custom",
        blurb="Write your own. Describe who the camera should be.",
        icon="sparkle",
        persona="",
    ),
)

BY_ID = {skill.id: skill for skill in SKILLS}

CUSTOM_PLACEHOLDER = (
    "You are a curious observer. Describe what is visible plainly and briefly."
)


class SkillRegistry:
    """The active skill, shared by the analyzer, the speech stage and the API.

    One process serves one camera, so the selection is global rather than
    per-browser: switching in one tab changes the run for everyone watching.
    """

    def __init__(self, active_id: str = DEFAULT_ID) -> None:
        self._lock = threading.Lock()
        self._active_id = active_id if active_id in BY_ID else DEFAULT_ID
        self._custom_persona = ""
        self._version = 0

    @property
    def version(self) -> int:
        """Increments on every change, so callers can notice a switch."""
        with self._lock:
            return self._version

    def active(self) -> Skill:
        with self._lock:
            skill = BY_ID[self._active_id]
            if skill.id == CUSTOM_ID:
                persona = self._custom_persona.strip() or CUSTOM_PLACEHOLDER
                return replace(skill, persona=persona)
            return skill

    def select(self, skill_id: str, persona: str | None = None) -> Skill:
        if skill_id not in BY_ID:
            raise ValueError(f"unknown skill: {skill_id!r}")
        if persona is not None and len(persona) > MAX_CUSTOM_PERSONA:
            raise ValueError(
                f"persona is longer than {MAX_CUSTOM_PERSONA} characters"
            )
        with self._lock:
            changed = skill_id != self._active_id
            self._active_id = skill_id
            if persona is not None:
                changed = changed or persona.strip() != self._custom_persona.strip()
                self._custom_persona = persona
            if changed:
                self._version += 1
        return self.active()

    def custom_persona(self) -> str:
        with self._lock:
            return self._custom_persona

    def to_json(self) -> dict:
        with self._lock:
            active_id = self._active_id
            custom = self._custom_persona
        return {
            "active_id": active_id,
            "custom_persona": custom,
            "custom_placeholder": CUSTOM_PLACEHOLDER,
            "max_persona_chars": MAX_CUSTOM_PERSONA,
            "skills": [skill.to_json() for skill in SKILLS],
        }
