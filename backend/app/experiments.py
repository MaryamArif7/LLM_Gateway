"""Split test helpers: which variant does a request get?"""
import hashlib
import logging
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Experiment, ExperimentAssignment

logger = logging.getLogger(__name__)


def bucket_for(experiment_id: uuid.UUID, subject_id: str) -> int:
    digest = hashlib.sha256(f"{experiment_id}:{subject_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100


def pick_variant(variants: list[dict], bucket: int) -> dict:
    upper = 0
    for variant in variants:
        upper += variant["percent"]
        if bucket < upper:
            return variant
    return variants[-1] 


async def get_active_experiment(db: AsyncSession, user_id, feature_tag: str) -> Experiment | None:
    result = await db.execute(
        select(Experiment).where(
            Experiment.user_id == user_id,
            Experiment.feature_tag == feature_tag,
            Experiment.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def assign_variant(db: AsyncSession, experiment: Experiment, subject_id: str | None) -> dict:
  
    if not subject_id:
        return pick_variant(experiment.variants, secrets.randbelow(100))

    variant = pick_variant(experiment.variants, bucket_for(experiment.id, subject_id))
    try:
        await db.execute(
            pg_insert(ExperimentAssignment)
            .values(experiment_id=experiment.id, subject_id=subject_id, variant=variant["name"])
            .on_conflict_do_nothing()
        )
        await db.commit()
    except Exception:
  
        await db.rollback()
        logger.warning("could not record experiment assignment", exc_info=True)
    return variant
