# HealthOmics historic data migration tools

## Ingest existing workflows 
### Overview

`hydrate_workflow_records.py` is a utility script that allows you to populate the monitoring and observability solution with existing AWS HealthOmics workflows. This is useful for:

- Ingesting workflows that were created before the monitoring solution was deployed
- Ensuring all workflows (both PRIVATE and READY2RUN) are tracked in the monitoring system
- Reprocessing workflows after fixing issues in the Lambda functions

### Prerequisites

- Python 3.9+
- AWS CLI configured with appropriate permissions
- The monitoring and observability solution must be deployed
- Required Python packages: boto3

### Usage

```bash
python hydrate_workflow_records.py [OPTIONS]
```

#### Options

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview what would be processed without actually invoking Lambda functions |
| `--sleep-between-api-calls N` | Duration in seconds between each API call to prevent throttling (default: 0.2) |
| `--lambda-timeout N` | Timeout in seconds for Lambda invocation (default: 300, max: 900) |
| `--lambda-function-name NAME` | Name of the Lambda function to invoke (default: healthomics_workflow_records_lambda) |

#### Examples

Preview processing without executing:
```bash
python hydrate_workflow_records.py --dry-run
```

Process workflows with a custom Lambda function name:
```bash
python hydrate_workflow_records.py --lambda-function-name my_custom_lambda_function
```

Process workflows with longer Lambda timeout:
```bash
python hydrate_workflow_records.py --lambda-timeout 600
```

Increase delay between API calls to prevent throttling:
```bash
python hydrate_workflow_records.py --sleep-between-api-calls 1
```

### How It Works

1. The script retrieves all READY2RUN and PRIVATE workflows from AWS HealthOmics
2. For each workflow, it fetches detailed information and all available versions
3. It creates event payloads that mimic the EventBridge "Workflow Status Change" events
4. It invokes the specified Lambda function synchronously for each workflow and version
5. Results are printed to the console

### Troubleshooting

- **Lambda Timeouts**: If Lambda functions time out, increase the `--lambda-timeout` value
- **API Throttling**: If you encounter throttling, increase the `--sleep-between-api-calls` value
- **Permission Errors**: Verify your AWS credentials have the necessary permissions to access HealthOmics resources

## Reprocess Runs
### Overview

`reprocess_runs.py` is a utility script that allows you to reprocess existing AWS HealthOmics workflow runs through the monitoring and observability Lambda functions. This is useful for:

- Processing historical runs that were executed before the monitoring solution was deployed
- Reprocessing runs after fixing issues in the Lambda functions
- Generating metrics for runs that failed to process correctly

### Prerequisites

- Python 3.9+
- AWS CLI configured with appropriate permissions
- The monitoring and observability solution must be deployed
- Required Python packages: boto3

### Usage

```bash
python reprocess_runs.py [OPTIONS]
```

#### Options

| Option | Description |
|--------|-------------|
| `--limit N` | Maximum number of runs to process (default: 50) |
| `--processors [TYPES]` | Specify which log processors to run: `run_analyzer`, `manifest`, `run_status_change_event`, or `ALL` (default: `ALL`) |
| `--dry-run` | Preview what would be processed without actually invoking Lambda functions |
| `--sleep-between-runs N` | Duration in seconds between each run to prevent API throttling (default: 1) |
| `--lambda-timeout N` | Timeout in seconds for Lambda invocation (default: 300, max: 900) |
| `--run-ids IDS` | CSV list of specific run IDs to process (ignores the --limit parameter) |

#### Examples

Process the 10 most recent runs with all processors:
```bash
python reprocess_runs.py --limit 10
```

Process runs with only the run analyzer:
```bash
python reprocess_runs.py --processors run_analyzer
```

Process specific run IDs:
```bash
python reprocess_runs.py --run-ids 123456,789012,345678
```

Preview processing without executing:
```bash
python reprocess_runs.py --dry-run
```

Process runs with longer Lambda timeout:
```bash
python reprocess_runs.py --lambda-timeout 600
```

### How It Works

1. The script retrieves Lambda function names from SSM Parameter Store
2. It fetches the most recent HealthOmics workflow runs or uses provided run IDs
3. For each run, it creates an event payload similar to the EventBridge events
4. It invokes the specified Lambda functions synchronously
5. Results are printed to the console

### Troubleshooting

- **Lambda Timeouts**: If Lambda functions time out, increase the `--lambda-timeout` value
- **API Throttling**: If you encounter throttling, increase the `--sleep-between-runs` value
- **Missing SSM Parameters**: Ensure the monitoring solution is properly deployed
- **Permission Errors**: Verify your AWS credentials have the necessary permissions