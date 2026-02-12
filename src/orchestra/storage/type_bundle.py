from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orchestra.storage.cxdb_client import CxdbClient

BUNDLE_ID = "dev.orchestra.v3"

ORCHESTRA_TYPE_BUNDLE: dict[str, Any] = {
    "registry_version": 1,
    "bundle_id": BUNDLE_ID,
    "types": {
        "dev.orchestra.PipelineLifecycle": {
            "versions": {
                "1": {
                    "fields": {
                        "1": {"name": "pipeline_name", "type": "string"},
                        "2": {"name": "goal", "type": "string", "optional": True},
                        "3": {"name": "status", "type": "string"},
                        "4": {
                            "name": "duration_ms",
                            "type": "u64",
                            "optional": True,
                            "semantic": "unix_ms",
                        },
                        "5": {"name": "error", "type": "string", "optional": True},
                        "6": {
                            "name": "session_display_id",
                            "type": "string",
                            "optional": True,
                        },
                    }
                },
                "2": {
                    "fields": {
                        "1": {"name": "pipeline_name", "type": "string"},
                        "2": {"name": "goal", "type": "string", "optional": True},
                        "3": {"name": "status", "type": "string"},
                        "4": {
                            "name": "duration_ms",
                            "type": "u64",
                            "optional": True,
                            "semantic": "unix_ms",
                        },
                        "5": {"name": "error", "type": "string", "optional": True},
                        "6": {
                            "name": "session_display_id",
                            "type": "string",
                            "optional": True,
                        },
                        "7": {
                            "name": "dot_file_path",
                            "type": "string",
                            "optional": True,
                        },
                        "8": {
                            "name": "graph_hash",
                            "type": "string",
                            "optional": True,
                        },
                    }
                },
            }
        },
        "dev.orchestra.NodeExecution": {
            "versions": {
                "1": {
                    "fields": {
                        "1": {"name": "node_id", "type": "string"},
                        "2": {"name": "handler_type", "type": "string"},
                        "3": {"name": "status", "type": "string"},
                        "4": {"name": "prompt", "type": "string", "optional": True},
                        "5": {"name": "response", "type": "string", "optional": True},
                        "6": {"name": "outcome", "type": "string", "optional": True},
                        "7": {"name": "duration_ms", "type": "u64", "optional": True},
                    }
                }
            }
        },
        "dev.orchestra.Checkpoint": {
            "versions": {
                "1": {
                    "fields": {
                        "1": {"name": "current_node", "type": "string"},
                        "2": {
                            "name": "completed_nodes",
                            "type": "array",
                            "items": "string",
                        },
                        "3": {"name": "context_snapshot", "type": "map"},
                        "4": {
                            "name": "retry_counters",
                            "type": "map",
                            "optional": True,
                        },
                    }
                },
                "2": {
                    "fields": {
                        "1": {"name": "current_node", "type": "string"},
                        "2": {
                            "name": "completed_nodes",
                            "type": "array",
                            "items": "string",
                        },
                        "3": {"name": "context_snapshot", "type": "map"},
                        "4": {
                            "name": "retry_counters",
                            "type": "map",
                            "optional": True,
                        },
                        "5": {
                            "name": "next_node_id",
                            "type": "string",
                            "optional": True,
                        },
                        "6": {
                            "name": "visited_outcomes",
                            "type": "map",
                            "optional": True,
                        },
                        "7": {
                            "name": "reroute_count",
                            "type": "u64",
                            "optional": True,
                        },
                    }
                },
            }
        },
        "dev.orchestra.AgentTurn": {
            "versions": {
                "1": {
                    "fields": {
                        "1": {"name": "turn_number", "type": "u64"},
                        "2": {"name": "node_id", "type": "string"},
                        "3": {"name": "model", "type": "string", "optional": True},
                        "4": {"name": "provider", "type": "string", "optional": True},
                        "5": {"name": "messages", "type": "string", "optional": True},
                        "6": {
                            "name": "tool_calls",
                            "type": "string",
                            "optional": True,
                        },
                        "7": {
                            "name": "files_written",
                            "type": "array",
                            "items": "string",
                            "optional": True,
                        },
                        "8": {
                            "name": "token_usage",
                            "type": "map",
                            "optional": True,
                        },
                        "9": {
                            "name": "agent_state",
                            "type": "string",
                            "optional": True,
                        },
                    }
                }
            }
        },
        "dev.orchestra.ParallelExecution": {
            "versions": {
                "1": {
                    "fields": {
                        "1": {"name": "node_id", "type": "string"},
                        "2": {"name": "branch_count", "type": "u64"},
                        "3": {
                            "name": "branch_contexts",
                            "type": "array",
                            "items": "string",
                            "optional": True,
                        },
                        "4": {
                            "name": "success_count",
                            "type": "u64",
                            "optional": True,
                        },
                        "5": {
                            "name": "failure_count",
                            "type": "u64",
                            "optional": True,
                        },
                        "6": {
                            "name": "duration_ms",
                            "type": "u64",
                            "optional": True,
                            "semantic": "unix_ms",
                        },
                        "7": {"name": "status", "type": "string", "optional": True},
                    }
                }
            }
        },
    },
}


def _build_field_maps() -> (
    tuple[dict[tuple[str, int], dict[str, int]], dict[tuple[str, int], dict[int, str]]]
):
    """Build forward and reverse field maps."""
    forward: dict[tuple[str, int], dict[str, int]] = {}
    reverse: dict[tuple[str, int], dict[int, str]] = {}
    for type_id, type_def in ORCHESTRA_TYPE_BUNDLE["types"].items():
        for ver_str, ver_def in type_def["versions"].items():
            name_to_tag: dict[str, int] = {}
            tag_to_name: dict[int, str] = {}
            for tag_str, field_def in ver_def["fields"].items():
                tag = int(tag_str)
                name_to_tag[field_def["name"]] = tag
                tag_to_name[tag] = field_def["name"]
            key = (type_id, int(ver_str))
            forward[key] = name_to_tag
            reverse[key] = tag_to_name
    return forward, reverse


_FIELD_MAPS, _REVERSE_MAPS = _build_field_maps()


def to_tagged_data(type_id: str, type_version: int, data: dict[str, Any]) -> dict[int, Any]:
    """Convert data dict from string keys to numeric field tags for msgpack encoding."""
    field_map = _FIELD_MAPS.get((type_id, type_version))
    if field_map is None:
        return data  # type: ignore[return-value]
    return {field_map[k]: v for k, v in data.items() if k in field_map}


def from_tagged_data(type_id: str, type_version: int, data: dict[int, Any]) -> dict[str, Any]:
    """Convert data dict from numeric field tags back to string keys."""
    reverse_map = _REVERSE_MAPS.get((type_id, type_version))
    if reverse_map is None:
        return data  # type: ignore[return-value]
    return {reverse_map[k]: v for k, v in data.items() if k in reverse_map}


def publish_orchestra_types(client: CxdbClient) -> None:
    client.publish_type_bundle(BUNDLE_ID, ORCHESTRA_TYPE_BUNDLE)
