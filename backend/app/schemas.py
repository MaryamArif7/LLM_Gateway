from datetime import datetime

from pydantic import BaseModel, Field, field_validator

class ApiKeyCreate(BaseModel):
    name: str = "Default key"


class ApiKeyOut(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    raw_key: str  


class ProviderKeyCreate(BaseModel):
    provider: str  
    api_key: str


class ProviderKeyOut(BaseModel):
    id: str
    provider: str
    key_last4: str
    status: str
    created_at: datetime


FEATURE_TAG_PATTERN = r"^[a-z0-9_.\-]{1,50}$"


def _clean_feature_tag(value):
    if value is None:
        return None
    value = str(value).strip().lower()
    return value or None


class ChatMessageIn(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    conversation_id: str | None = None
    messages: list[ChatMessageIn]
    model: str | None = None  
    temperature: float = 0.7
    max_tokens: int = 1024
    feature_tag: str | None = Field(default=None, pattern=FEATURE_TAG_PATTERN)
    prompt: str | None = Field(default=None, pattern=PROMPT_NAME_PATTERN)
    prompt_version: int | None = Field(default=None, ge=1)
    variables: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=50)
    subject_id: str | None = Field(default=None, max_length=100)

    _clean_tag = field_validator("feature_tag", mode="before")(_clean_feature_tag)
    _clean_prompt = field_validator("prompt", mode="before")(_clean_feature_tag)

    @field_validator("subject_id", mode="before")
    @classmethod
    def _clean_subject(cls, value):
        if value is None:
            return None
        return str(value).strip() or None

class CompareRequest(BaseModel):
    prompt: str
    models: list[str]  
    temperature: float = 0.7
    max_tokens: int = 1024
    feature_tag: str | None = Field(default=None, pattern=FEATURE_TAG_PATTERN)

    _clean_tag = field_validator("feature_tag", mode="before")(_clean_feature_tag)


class BudgetIn(BaseModel):
    threshold_amount: float | None = Field(default=None, gt=0, le=1_000_000)
    notify_at_percent: int = Field(default=80, ge=1, le=100)
AX_TEMPLATE_CHARS = 20_000


class PromptCreate(BaseModel):
    name: str = Field(pattern=PROMPT_NAME_PATTERN)
    template: str = Field(min_length=1, max_length=MAX_TEMPLATE_CHARS)
    target_model: str | None = None

    _clean_name = field_validator("name", mode="before")(_clean_feature_tag)


class PromptVersionCreate(BaseModel):
    template: str = Field(min_length=1, max_length=MAX_TEMPLATE_CHARS)
    target_model: str | None = None


class VariantIn(BaseModel):
    name: str = Field(pattern=VARIANT_NAME_PATTERN)
    percent: int = Field(ge=1, le=99)

    model: str | None = None
    prompt_name: str | None = Field(default=None, pattern=PROMPT_NAME_PATTERN)
    prompt_version: int | None = Field(default=None, ge=1)

    _clean_name = field_validator("name", mode="before")(_clean_feature_tag)
    _clean_prompt = field_validator("prompt_name", mode="before")(_clean_feature_tag)


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    feature_tag: str = Field(pattern=FEATURE_TAG_PATTERN)
    variants: list[VariantIn] = Field(min_length=2, max_length=4)

    _clean_tag = field_validator("feature_tag", mode="before")(_clean_feature_tag)
