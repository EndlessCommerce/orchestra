from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orchestra.storage.cxdb_client import CxdbClient

BUNDLE_ID = "dev.orchestra.v1"

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
                }
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
                }
            }
        },
    },
}


def publish_orchestra_types(client: CxdbClient) -> None:
    client.publish_type_bundle(BUNDLE_ID, ORCHESTRA_TYPE_BUNDLE)
