from typing import Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class CharacterSetting(BaseModel):
    speed: float = 1.0
    pitch: float = 0.0


class DialogueItem(BaseModel):
    character: str
    line: str
    emotion: Optional[str] = None


class TimelineItem(BaseModel):
    startTime: float
    duration: float


class ProjectJson(BaseModel):
    characterSettings: Dict[str, CharacterSetting] = Field(default_factory=dict)
    voiceAssignments: Dict[str, str] = Field(default_factory=dict)
    dialogues: List[DialogueItem]
    timeline: List[TimelineItem]
    genre: Optional[str] = None
    clientTimestamp: Optional[str] = None

    @model_validator(mode="after")
    def check_lengths(self):
        if len(self.dialogues) != len(self.timeline):
            raise ValueError(
                f"dialogues ({len(self.dialogues)}) aur timeline ({len(self.timeline)}) ki length match nahi karti"
            )
        return self


class JobStatus(BaseModel):
    job_id: str
    state: str  # queued | processing | done | error
    progress: int = 0
    message: str = ""
    video_ready: bool = False
    error: Optional[str] = None
