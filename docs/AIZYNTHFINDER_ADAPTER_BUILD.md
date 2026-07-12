# AiZynthFinder Adapter Build Notes

AiZynthFinder is now wired as the retrosynthesis planner behind the synthesis workflow.

## What Is Included

- `src/medagent/services/aizynthfinder_adapter.py`
  - detects local Python package, local `aizynthcli`, and Docker image modes
  - writes a temporary `.smi` input file before invoking `aizynthcli`
  - parses JSON output from AiZynthFinder table output
  - returns safe fallback labels when the tool, config, or output is unavailable
- `docker/aizynthfinder/Dockerfile`
  - builds `aizynthfinder:latest` with `aizynthcli` as entrypoint
- `docker-compose.yml`
  - adds the `aizynthfinder` service under the `tools` profile
- `scripts/manage_docker_tools.py`
  - adds status/build/test/start/stop support for `aizynthfinder`
- `configs/tools.yaml`
  - records image, config environment variables, input data directory, and output directory

## Required Model Configuration

The Docker image installs the tool, but it does not bundle policy models or stock files. A real run needs an AiZynthFinder config file that points at your local policy, template, and stock assets.

Set one of these environment variables to the config file:

```powershell
$env:AIZYNTHFINDER_CONFIG="C:\path\to\aizynthfinder\config.yml"
```

or:

```powershell
$env:MEDAGENT_AIZYNTHFINDER_CONFIG="C:\path\to\aizynthfinder\config.yml"
```

For Docker runs, put the config and the files it references under `data/aizynthfinder/` when possible. The adapter mounts the config directory as `/data/config` and runs `aizynthcli` from that directory so relative paths in the config can resolve.

If the referenced model/stock files live somewhere else, set:

```powershell
$env:AIZYNTHFINDER_DATA_DIR="C:\path\to\aizynthfinder\data"
```

or:

```powershell
$env:MEDAGENT_AIZYNTHFINDER_DATA_DIR="C:\path\to\aizynthfinder\data"
```

When that directory exists, Docker runs mount it as `/data/aizynthfinder`.

## Commands

Build only AiZynthFinder:

```powershell
scripts\build_tools.bat aizynthfinder
```

Build all scientific tool images:

```powershell
scripts\build_tools.bat all
```

Check status:

```powershell
python scripts\check_tools.py --verbose --test
python scripts\manage_docker_tools.py status
```

## Fallback Behavior

If AiZynthFinder is unavailable or no config file is set, the synthesis workflow still falls back to the RDKit/rule-based retrosynthesis estimate. The result includes warnings such as:

- `aizynthfinder_not_installed`
- `aizynthfinder_config_not_configured`
- `aizynthfinder_config_missing`
- `retrosynthesis_estimated_not_actual`
