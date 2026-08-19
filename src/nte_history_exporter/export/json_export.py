from __future__ import annotations

from typing import Any

from nte_history_exporter import __version__
from nte_history_exporter.constants import (
    ARC_BANNER_ID,
    BANNER_ID,
    EXPORTER_NAME,
    GAME_NAME,
    POOL_META,
    MYSTERY_BOX_BANNER_ID,
)
from nte_history_exporter.decoder.server_region import account_region_for_server
from nte_history_exporter.decoder.achievement import AchievementRecord
from nte_history_exporter.mappings import ACHIEVEMENTS_BY_CASEFOLD


def build_export_json(
    rows: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    *,
    source: str = "packet_capture",
    capture_source: str | None = None,
    user_uid: str | None = None,
    server_id: str | None = None,
    flow_index: int | None = None,
    candidate_request_response_pairs: int | None = None,
    pages_seen: list[int] | None = None,
) -> dict[str, Any]:
    exported = [r for r in rows if r.get("export_record") is True]
    representative = exported[0] if exported else (rows[0] if rows else {})
    pool_group_id = representative.get("pool_group_id", BANNER_ID)
    pool = next((meta for meta in POOL_META.values() if meta["id"] == pool_group_id), POOL_META["permanent"])
    scan: dict[str, Any] = {
        "mode": "stable_only",
        "boundary_policy": "export_ordinal_stable_groups",
        "decoded_records": len(rows),
        "exported_records": len(exported),
        "skipped_records": len(rows) - len(exported),
        "warnings": warnings,
    }
    if flow_index is not None:
        scan["udp_flow_index"] = flow_index
    if candidate_request_response_pairs is not None:
        scan["candidate_request_response_pairs"] = candidate_request_response_pairs
    if pages_seen is not None:
        scan["pages_seen"] = pages_seen

    normalized_user_uid = user_uid.strip() if user_uid else ""
    normalized_server_id = str(server_id).strip() if server_id else ""
    export: dict[str, Any] = {
        "format": "nte-history-export",
        "format_version": 1,
        "game": GAME_NAME,
        "source": source,
    }
    if capture_source:
        export["capture_source"] = capture_source
    export["exporter"] = {"name": EXPORTER_NAME, "version": __version__}
    export.update(
        {
            "banner": {
                "id": pool["id"],
                "name": pool["name"],
                "system": pool["system"],
                "shared_pity": pool["shared_pity"],
            },
            "scan": scan,
        }
    )
    if normalized_user_uid:
        export["user_uid"] = normalized_user_uid
    if normalized_server_id:
        export["server_id"] = normalized_server_id
        account_region = account_region_for_server(normalized_server_id)
        if account_region:
            export["account_region"] = account_region
    export["records"] = [_record_for_export(r) for r in exported]
    return export


def build_achievement_export_json(
    achievement_records: list[AchievementRecord],
    *,
    source: str = "packet_capture",
    capture_source: str | None = None,
    user_uid: str | None = None,
    server_id: str | None = None,
) -> dict[str, Any]:
    categories: dict[str, list[dict[str, Any]]] = {}
    scan = {
        "in_game": {
            "total_achievements": 0,
            "completed_achievements": 0,
            "in_progress_achievements": 0,
        },
        "playstation": {
            "total_achievements": 0,
            "completed_achievements": 0,
            "in_progress_achievements": 0,
        },
    }
    for achievement in achievement_records:
        achievement_id = achievement.achievement_id
        is_playstation = achievement_id.casefold().startswith("playstation_")
        summary = scan["playstation" if is_playstation else "in_game"]
        summary["total_achievements"] += 1
        if achievement.completed:
            summary["completed_achievements"] += 1
        else:
            summary["in_progress_achievements"] += 1
        category, separator, _number = achievement_id.partition("_")
        category_key = category.casefold() if separator else "uncategorized"
        record = {
            "id": achievement_id,
            "platform": "playstation" if is_playstation else "in_game",
            "status": achievement.status,
            "progress": achievement.progress,
            "completed": achievement.completed,
            "completed_at": achievement.completed_at,
        }
        metadata = ACHIEVEMENTS_BY_CASEFOLD.get(achievement_id.casefold())
        if metadata:
            record.update(
                {
                    "name": metadata["name"],
                    "description": metadata["description"],
                    "quality": metadata["quality"],
                    "target": metadata["target"],
                    "rewards": metadata["rewards"],
                }
            )
        categories.setdefault(category_key, []).append(record)

    export: dict[str, Any] = {
        "format": "nte-achievement-export",
        "format_version": 1,
        "game": GAME_NAME,
        "source": source,
    }
    if capture_source:
        export["capture_source"] = capture_source
    export["exporter"] = {"name": EXPORTER_NAME, "version": __version__}
    export["scan"] = scan

    normalized_user_uid = user_uid.strip() if user_uid else ""
    normalized_server_id = str(server_id).strip() if server_id else ""
    if normalized_user_uid:
        export["user_uid"] = normalized_user_uid
    if normalized_server_id:
        export["server_id"] = normalized_server_id
        account_region = account_region_for_server(normalized_server_id)
        if account_region:
            export["account_region"] = account_region
    export["categories"] = categories
    return export


def _record_for_export(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("pool_group_id") == ARC_BANNER_ID:
        return {
            "uid": row.get("uid"),
            "pool_group_id": row.get("pool_group_id"),
            "timestamp": row.get("timestamp_decoded"),
            "timestamp_group_ordinal": row.get("timestamp_group_ordinal"),
            "reward_type": row.get("reward_type"),
            "reward_id": row.get("reward_id"),
            "reward_name": row.get("reward_name"),
            "reward_rank": row.get("reward_rank"),
            "source_type": row.get("source_type"),
        }

    if row.get("pool_group_id") == MYSTERY_BOX_BANNER_ID:
        return {
            "uid": row.get("uid"),
            "pool_group_id": row.get("pool_group_id"),
            "timestamp": row.get("timestamp_decoded"),
            "timestamp_group_ordinal": row.get("timestamp_group_ordinal"),
            "result_type": "single_pull",
            "reward_type": row.get("reward_type"),
            "reward_id": row.get("reward_id"),
            "reward_name": row.get("reward_name"),
            "reward_rank": row.get("reward_rank"),
            "quantity": row.get("quantity"),
            "source_type": row.get("source_type"),
        }

    return {
        "uid": row.get("uid"),
        "pool_group_id": row.get("pool_group_id", BANNER_ID),
        "timestamp": row.get("timestamp_decoded"),
        "timestamp_group_ordinal": row.get("timestamp_group_ordinal"),
        "roll_result": row.get("dice"),
        "result_type": row.get("result_type") or ("points_gift" if row.get("dice") == 0 else "dice"),
        "reward_type": row.get("reward_type"),
        "reward_id": row.get("reward_id"),
        "reward_name": row.get("reward_name"),
        "reward_rank": row.get("reward_rank"),
        "quantity": row.get("quantity"),
    }
