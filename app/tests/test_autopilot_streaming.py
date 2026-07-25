from __future__ import annotations

from app.streaming.models import (
    metadata,
    streaming_accounts_table,
    streaming_playlists_table,
)
from app.streaming.router import create_router
from app.streaming.schemas import UpdatePlaylistAutomationLevelRequest
from sqlalchemy import create_engine, insert


def _route(router, method: str, path: str):
    return next(
        route
        for route in router.routes
        if route.path == path and method in route.methods
    )


def test_dedicated_automation_endpoint_preserves_sync_mode(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'streaming-automation.db'}")
    metadata.create_all(engine)
    with engine.begin() as connection:
        account_id = connection.execute(
            insert(streaming_accounts_table).values(
                provider="youtube_music",
                display_name="Listener",
                auth_token_blob="encrypted",
                auth_state="connected",
            )
        ).inserted_primary_key[0]
        playlist_id = connection.execute(
            insert(streaming_playlists_table).values(
                account_id=account_id,
                provider_playlist_id="PL1",
                title="Keep fresh",
                sync_mode="match_only",
            )
        ).inserted_primary_key[0]

    endpoint = _route(
        create_router(require_redis_url=lambda: "redis://unused"),
        "PATCH",
        "/streaming/playlists/{playlist_id}/automation-level",
    ).endpoint
    response = endpoint(
        playlist_id=playlist_id,
        payload=UpdatePlaylistAutomationLevelRequest(automation_level="full"),
        engine=engine,
    )

    assert response.automation_level == "full"
    assert response.sync_mode == "match_only"
