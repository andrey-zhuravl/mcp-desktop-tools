# Integrations (C1)

This guide illustrates how to connect MCP Desktop Tools to *Lab agents, MLflow tracking stores, and Jenkins pipelines.

## *Lab Python client

```python
from mcp_desktop_tools.integrations.lab_client import LabClient

client = LabClient.auto("demo")
response = client.snapshot(
    rel_path="proj",
    mlflow_logging=False,
    include_env=False,
)
if response.ok:
    print("Artifact written to", response.data.artifact)
else:
    raise RuntimeError(response.error)
```

* `LabClient.auto(workspace_id)` loads `workspaces.yaml` using the same precedence as the CLI (`MCPDT_CONFIG`, default path).
* Override the configuration location via `LabClient.from_config_path(workspace_id, Path("/path/to/workspaces.yaml"))`.
* Additional snapshot arguments align with the CLI flags (`include_git`, `largest_files`, `mlflow_uri`, `tags`, etc.).

## MLflow homelab integration

1. Ensure `mlflow>=2.14` is installed (included in the default package dependencies).
2. Export your tracking URI and default experiment:

   ```bash
   export MLFLOW_TRACKING_URI="file:///srv/mlruns"
   export MLFLOW_EXPERIMENT_NAME="homelab"
   ```

3. Capture a snapshot with tags that describe the build or workspace:

   ```bash
   mcp-tools --workspace demo snapshot --rel-path proj \
     --run-name "$BUILD_TAG" \
     --tag repo=proj --tag stage=C1 \
     --artifact-path repo_snapshot.json \
     --json
   ```

4. Each run records tags (`workspace_id`, `snapshot.generated_at`, `snapshot.repo_root` plus custom tags) and uploads the JSON artifact. Failed uploads degrade gracefully with warnings while still writing the local file.

To fetch artifacts programmatically:

```python
from mlflow.tracking import MlflowClient

client = MlflowClient(tracking_uri="file:///srv/mlruns")
run = client.get_run("<run_id>")
print(run.data.tags)
artifacts = client.list_artifacts(run.info.run_id)
print([artifact.path for artifact in artifacts])
```

## Jenkins pipeline fragment

Include the following stage to archive both the CLI output (`snapshot.json`) and the uploaded artifact (`repo_snapshot.json`):

```groovy
stage('Snapshot') {
  steps {
    sh '''
      mcp-tools --workspace ai-projects snapshot                 --rel-path GardenKeeper                 --mlflow-uri "$MLFLOW_TRACKING_URI"                 --experiment homelab                 --run-name "$BUILD_TAG"                 --tag repo=GardenKeeper --tag stage=C1                 --artifact-path repo_snapshot.json --json > snapshot.json
    '''
  }
  post {
    always {
      archiveArtifacts artifacts: 'snapshot.json, repo_snapshot.json', fingerprint: true
    }
  }
}
```

Adjust the workspace identifier, relative path, and tags to match your environment. The CLI prints warnings to `stderr`, making it suitable for pipeline logs while keeping JSON output machine-readable.
