# Stage 6: Remote Deployment

### Objective

Deploy the system to a remote server that can clone repositories on demand, provision isolated execution environments, and manage credentials securely. Users interact via the web client — no local setup required.

### Architecture

```mermaid
graph TB
    subgraph "User Devices"
        BROWSER["Browser"]
        CLI2["CLI (optional)"]
    end

    subgraph "Edge / Load Balancer"
        LB["Nginx / Caddy"]
    end

    subgraph "Application Tier"
        API2["FastAPI + LangGraph Platform"]
        REDIS["Redis (task queue)"]
        PG["PostgreSQL (checkpoints + metadata)"]
    end

    subgraph "Worker Pool"
        W1["Worker Container 1"]
        W2["Worker Container 2"]
        W3["Worker Container N"]
    end

    subgraph "Worker Container Internals"
        CLONE["Git Clone"]
        VENV["Virtualenv / Node Modules"]
        TOOLS2["Tool Sandbox"]
        RUNNER["Graph Executor"]
    end

    subgraph "External Services"
        GH["GitHub / GitLab API"]
        VAULT["Secret Manager"]
        REG["Container Registry"]
    end

    BROWSER --> LB
    CLI2 --> LB
    LB --> API2
    API2 --> REDIS
    API2 --> PG
    REDIS --> W1
    REDIS --> W2
    REDIS --> W3
    W1 --> CLONE
    CLONE --> VENV
    VENV --> TOOLS2
    TOOLS2 --> RUNNER
    RUNNER --> PG
    W1 --> GH
    API2 --> VAULT
    W1 --> VAULT

    style "User Devices" fill:#1a1a2e,stroke:#4a4a6a,color:#e0e0e8
    style "Application Tier" fill:#1a1a2e,stroke:#4a4a6a,color:#e0e0e8
    style "Worker Pool" fill:#1a1a2e,stroke:#4a4a6a,color:#e0e0e8
    style "Worker Container Internals" fill:#1a1a2e,stroke:#4a4a6a,color:#e0e0e8
    style "External Services" fill:#1a1a2e,stroke:#4a4a6a,color:#e0e0e8
```

### Workspace Manager

Each session gets an isolated workspace — a fresh clone of the repository with its own environment.

```python
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Workspace:
    session_id: str
    path: Path
    repo_url: str
    branch: str
    environment: str        # "python" | "node" | "mixed"
    created_at: datetime

class WorkspaceManager:
    def __init__(self, base_dir: str = "/workspaces", vault=None):
        self.base_dir = Path(base_dir)
        self.vault = vault

    async def provision(
        self,
        session_id: str,
        repo_url: str,
        base_branch: str = "main",
    ) -> Workspace:
        work_dir = self.base_dir / session_id
        work_dir.mkdir(parents=True, exist_ok=True)

        # Get scoped credentials
        git_token = await self.vault.get_token(repo_url)
        authed_url = self._inject_token(repo_url, git_token)

        # Clone
        await async_run(f"git clone --depth=100 -b {base_branch} {authed_url} {work_dir}/repo")
        repo_path = work_dir / "repo"

        # Configure git identity
        await async_run(f"git -C {repo_path} config user.name 'agent-bot'")
        await async_run(f"git -C {repo_path} config user.email 'agent@system'")

        # Create feature branch
        branch = f"agent/{session_id[:8]}"
        await async_run(f"git -C {repo_path} checkout -b {branch}")

        # Detect and setup environment
        env_type = self._detect_environment(repo_path)
        await self._setup_environment(repo_path, env_type)

        return Workspace(
            session_id=session_id,
            path=repo_path,
            repo_url=repo_url,
            branch=branch,
            environment=env_type,
            created_at=datetime.now(),
        )

    def _detect_environment(self, repo_path: Path) -> str:
        if (repo_path / "pyproject.toml").exists():
            return "python"
        if (repo_path / "requirements.txt").exists():
            return "python"
        if (repo_path / "package.json").exists():
            return "node"
        if (repo_path / "Cargo.toml").exists():
            return "rust"
        return "unknown"

    async def _setup_environment(self, repo_path: Path, env_type: str):
        if env_type == "python":
            await async_run(f"python -m venv {repo_path}/.venv")
            pip = f"{repo_path}/.venv/bin/pip"
            if (repo_path / "pyproject.toml").exists():
                await async_run(f"{pip} install -e '{repo_path}[dev]'")
            elif (repo_path / "requirements.txt").exists():
                await async_run(f"{pip} install -r {repo_path}/requirements.txt")
        elif env_type == "node":
            await async_run(f"npm install --prefix {repo_path}")

    async def teardown(self, workspace: Workspace):
        shutil.rmtree(workspace.path.parent, ignore_errors=True)
```

### Container Isolation

Each worker runs in a Docker container with resource limits and network restrictions.

```yaml
# docker-compose.worker.yml
services:
  worker:
    build: ./worker
    deploy:
      replicas: 4
      resources:
        limits:
          cpus: "2.0"
          memory: 4G
        reservations:
          cpus: "0.5"
          memory: 1G
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:size=2G
    volumes:
      - workspaces:/workspaces
    networks:
      - worker-net
    environment:
      - REDIS_URL=redis://redis:6379
      - DATABASE_URL=postgres://...
      - VAULT_ADDR=http://vault:8200

networks:
  worker-net:
    driver: bridge
    internal: false # needs outbound for git clone, pip install
```

### Worker Dockerfile

```dockerfile
FROM python:3.12-slim

# System tools needed by the executor
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ripgrep \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Verification tools
RUN pip install ruff mypy pytest semgrep

# Application
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . /app
WORKDIR /app

CMD ["python", "-m", "worker.main"]
```

### Credential Management

```python
class CredentialVault:
    """Manages scoped, short-lived credentials for each session."""

    async def get_token(self, repo_url: str) -> str:
        """Get a scoped GitHub installation token for this repo."""
        # Option 1: GitHub App installation token (preferred)
        # Scoped to specific repos, expires in 1 hour
        installation = await self.github_app.get_installation(repo_url)
        token = await installation.create_token(
            permissions={"contents": "write", "pull_requests": "write"},
            repositories=[self._extract_repo_name(repo_url)],
        )
        return token.token

    async def revoke_token(self, token: str):
        """Revoke token when session ends."""
        await self.github_app.revoke_installation_token(token)
```

### Queue-Based Execution

```python
# worker/main.py
import redis.asyncio as redis
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async def worker_loop():
    r = redis.from_url(REDIS_URL)
    checkpointer = AsyncPostgresSaver.from_conn_string(DATABASE_URL)
    workspace_mgr = WorkspaceManager(vault=CredentialVault())

    while True:
        # Block until a task arrives
        _, task_data = await r.brpop("agent:tasks")
        task = json.loads(task_data)

        try:
            # Provision workspace
            ws = await workspace_mgr.provision(
                session_id=task["session_id"],
                repo_url=task["repo_url"],
                base_branch=task.get("base_branch", "main"),
            )

            # Build and run graph
            llm = init_chat_model(task.get("model", "claude-sonnet-4-5-20250929"))
            graph = build_graph(llm, checkpointer=checkpointer)
            config = {"configurable": {"thread_id": task["session_id"]}}

            await graph.ainvoke(
                {
                    "raw_goal": task["goal"],
                    "repo_path": str(ws.path),
                },
                config,
            )
        except Exception as e:
            await r.publish(
                f"agent:events:{task['session_id']}",
                json.dumps({"type": "error", "data": str(e)})
            )
        finally:
            await workspace_mgr.teardown(ws)
```

### Deployment Configuration

```yaml
# docker-compose.yml
services:
  api:
    build: ./server
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgres://agent:pass@postgres:5432/agent
      - REDIS_URL=redis://redis:6379
    depends_on:
      - postgres
      - redis

  worker:
    build: ./worker
    deploy:
      replicas: 4
    environment:
      - DATABASE_URL=postgres://agent:pass@postgres:5432/agent
      - REDIS_URL=redis://redis:6379
      - GITHUB_APP_ID=${GITHUB_APP_ID}
      - GITHUB_APP_PRIVATE_KEY=${GITHUB_APP_PRIVATE_KEY}
    volumes:
      - workspaces:/workspaces
    depends_on:
      - postgres
      - redis

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: agent
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: pass
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine

  client:
    build: ./client
    ports:
      - "3000:80"

volumes:
  pgdata:
  workspaces:
```

### Monitoring and Observability

```mermaid
graph LR
    WORKERS["Workers"] --> OTEL["OpenTelemetry Collector"]
    API3["API Server"] --> OTEL
    OTEL --> PROM["Prometheus (metrics)"]
    OTEL --> LOKI["Loki (logs)"]
    OTEL --> TEMPO["Tempo (traces)"]
    PROM --> GRAF["Grafana"]
    LOKI --> GRAF
    TEMPO --> GRAF

    style WORKERS fill:#1a4a2e,stroke:#4ade80,color:#e0e0e8
    style GRAF fill:#2a1a4a,stroke:#a78bfa,color:#e0e0e8
```

Key metrics to track:

- **Session lifecycle**: creation rate, completion rate, average duration, failure rate.
- **Agent performance**: tokens consumed per session, LLM latency per node, verification pass rate.
- **Infrastructure**: worker utilization, queue depth, workspace disk usage, container memory.
- **Git operations**: commits per session, PR merge rate, verification retry rate.

### Deliverables

| Artifact                | Description                            |
| ----------------------- | -------------------------------------- |
| `worker/main.py`        | Queue consumer and graph executor      |
| `worker/workspace.py`   | Workspace provisioning and teardown    |
| `worker/credentials.py` | GitHub App token management            |
| `worker/Dockerfile`     | Worker container image                 |
| `docker-compose.yml`    | Full stack deployment                  |
| `infra/monitoring/`     | Grafana dashboards, Prometheus rules   |
| `docs/deployment.md`    | Deployment runbook                     |
| `docs/security.md`      | Credential scoping and isolation model |

### Exit Criteria

- [ ] A session started from the web client clones a GitHub repo and runs the full workflow.
- [ ] The agent writes real code, commits, pushes, and opens a PR.
- [ ] Workspace is cleaned up after session completion or timeout.
- [ ] 4 concurrent sessions run without interference.
- [ ] Git tokens are scoped to the specific repo and expire after the session.
- [ ] A killed worker doesn't lose state — the session can resume on another worker.
- [ ] Grafana dashboard shows session metrics and worker health.
