
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.experiments import assign_variant, get_active_experiment
from app.models import Prompt
from app.prompts import MissingVariables, render_template
from app.schemas import ChatRequest


@dataclass
class RequestPlan:
    system_text: str | None = None
    model: str | None = None
    prompt_name: str | None = None
    prompt_version: int | None = None
    experiment_id: uuid.UUID | None = None
    variant: str | None = None

    def meta(self) -> dict:
        
        out: dict = {}
        if self.prompt_name:
            out["prompt"] = {"name": self.prompt_name, "version": self.prompt_version}
        if self.experiment_id:
            out["experiment_id"] = str(self.experiment_id)
            out["variant"] = self.variant
        return out


async def load_prompt(db: AsyncSession, user_id, name: str, version: int | None) -> Prompt | None:
    query = select(Prompt).where(Prompt.user_id == user_id, Prompt.name == name)
    query = query.where(Prompt.version == version) if version else query.order_by(Prompt.version.desc()).limit(1)
    return (await db.execute(query)).scalar_one_or_none()


async def resolve_plan(user_id, req: ChatRequest) -> RequestPlan:
    plan = RequestPlan()
    async with SessionLocal() as db:
        variant = None
        if req.feature_tag:
            experiment = await get_active_experiment(db, user_id, req.feature_tag)
            if experiment is not None:
                variant = await assign_variant(db, experiment, req.subject_id)
                plan.experiment_id = experiment.id
                plan.variant = variant["name"]

        if variant and variant.get("prompt_name"):
            prompt_name, prompt_version = variant["prompt_name"], variant.get("prompt_version")
        else:
            prompt_name, prompt_version = req.prompt, req.prompt_version

        prompt = None
        if prompt_name:
            prompt = await load_prompt(db, user_id, prompt_name, prompt_version)
            if prompt is None:
                where = f"{prompt_name} v{prompt_version}" if prompt_version else prompt_name
                raise HTTPException(status_code=404, detail=f"Prompt not found: {where}")
            try:
                plan.system_text = render_template(prompt.template, req.variables)
            except MissingVariables as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Prompt {prompt.name} v{prompt.version} needs variables: {', '.join(e.names)}",
                )
            plan.prompt_name, plan.prompt_version = prompt.name, prompt.version

        plan.model = (variant or {}).get("model") or req.model or (prompt.target_model if prompt else None)
    return plan
