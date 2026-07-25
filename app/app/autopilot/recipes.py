from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Protocol

from sqlalchemy.engine import Engine

from app.autopilot.exports import RecipeExportResult, refresh_recipe_exports


@dataclass(frozen=True, slots=True)
class RecipeRegenerationResult:
    recipe_id: int
    generation_run_id: int
    export_result: RecipeExportResult | None


def _noop_checkpoint() -> None:
    pass


class RecipeRegenerationAdapter(Protocol):
    def affected_recipe_ids(self, affected_playlist_ids: set[int]) -> list[int]: ...

    def regenerate(self, recipe_id: int) -> RecipeRegenerationResult: ...


@dataclass(slots=True)
class SonicRecipeRegenerationAdapter:
    """Narrow adapter between automation and disposable sonic snapshots."""

    engine: Engine
    lease_checkpoint: Callable[[], None] = _noop_checkpoint

    def affected_recipe_ids(self, affected_playlist_ids: set[int]) -> list[int]:
        from app.sonic.models import SONIC_SOURCE_STREAMING_PLAYLISTS
        from app.sonic.store import SonicStore

        if not affected_playlist_ids:
            return []
        recipe_ids: list[int] = []
        for recipe in SonicStore(engine=self.engine).list_generation_recipes(
            enabled_only=True
        ):
            if not recipe.regenerate_on_change:
                continue
            source = recipe.source_filter_json
            if source.get("source_type") != SONIC_SOURCE_STREAMING_PLAYLISTS:
                recipe_ids.append(recipe.id)
                continue
            configured_ids = {
                value
                for value in source.get("streaming_playlist_ids", [])
                if isinstance(value, int) and not isinstance(value, bool)
            }
            if configured_ids & affected_playlist_ids:
                recipe_ids.append(recipe.id)
        return recipe_ids

    def regenerate(self, recipe_id: int) -> RecipeRegenerationResult:
        from app.sonic.jobs import run_playlist_generation_job
        from app.sonic.models import (
            PLAYLIST_GENERATION_STATUS_COMPLETED,
            PLAYLIST_GENERATION_TRIGGER_AUTOPILOT,
        )
        from app.sonic.store import SonicStore

        store = SonicStore(engine=self.engine)
        recipe = store.get_generation_recipe(recipe_id)
        if recipe is None:
            raise ValueError(f"Generation recipe not found: {recipe_id}")
        if not recipe.enabled or not recipe.regenerate_on_change:
            raise ValueError(
                f"Generation recipe is not enabled for automation: {recipe_id}"
            )
        self.lease_checkpoint()
        run = store.create_generation_run(
            generation_config=recipe.generation_config_json,
            recipe_id=recipe.id,
            run_name=recipe.name,
            source_filter=recipe.source_filter_json,
            trigger=PLAYLIST_GENERATION_TRIGGER_AUTOPILOT,
        )
        self.lease_checkpoint()
        self.lease_checkpoint()
        run_playlist_generation_job(run.id)
        self.lease_checkpoint()
        completed = store.get_generation_run(run.id)
        if (
            completed is None
            or completed.status != PLAYLIST_GENERATION_STATUS_COMPLETED
        ):
            status = completed.status if completed is not None else "missing"
            raise RuntimeError(
                f"Recipe generation run {run.id} did not complete: {status}"
            )
        self.lease_checkpoint()
        store.mark_generation_recipe_regenerated(recipe.id, run_id=run.id)
        self.lease_checkpoint()
        export_result = refresh_recipe_exports(
            engine=self.engine,
            export_config=recipe.export_config_json,
            lease_checkpoint=self.lease_checkpoint,
            recipe_id=recipe.id,
            run_id=run.id,
        )
        return RecipeRegenerationResult(
            recipe_id=recipe.id,
            generation_run_id=run.id,
            export_result=export_result,
        )
