# n8n-nodes-ai-video-engine

Community nodes for using AI Video Engine from n8n.

AI Video Engine is an asynchronous video-processing API. These nodes let n8n create jobs, upload source media, wait for completion, cancel jobs, and receive webhook callbacks without hand-building HTTP Request nodes for every workflow.

## Nodes

- **AI Video Engine**: action node for jobs and preset pipelines.
- **AI Video Engine Trigger**: webhook trigger for `job.completed`, `job.failed`, and `job.cancelled` callbacks.

## Credentials

Create an **AI Video Engine API** credential:

- **Base URL**: for example `http://localhost:6666` or `https://api.example.com`
- **Authentication Type**: `X-API-Key` or `Bearer`
- **API Key**: the server `API_SECRET_KEY`

The credential test calls `GET /jobs?limit=1`, which is a protected endpoint.

## Action Node Operations

### Resource: Job

- **Create Custom**: create any pipeline job with JSON payload.
- **Upload And Create**: upload incoming n8n binary data and create a job through `/jobs/upload`.
- **Get**: fetch one job by ID.
- **List**: list jobs, optionally filtered by status.
- **Cancel**: request cancellation.
- **Wait**: bounded polling until `done`, `failed`, or `cancelled`.

### Resource: Preset Pipeline

- **Low Level Edit**: common FFmpeg-style transforms and custom operations JSON.
- **Dubbing**: source/target language, translator, TTS voice/rate.
- **Subtitle**: generate or burn subtitles.
- **Silence Cut**: remove silent sections.
- **Extract Audio**: create an audio file.
- **Extract Frames**: export frames as images.

All create operations support **Advanced Payload JSON**, merged into the generated payload so backend-specific fields can be added without a node release.

## Output

Every operation returns the raw job response plus normalized fields:

- `job_id`
- `status`
- `progress`
- `current_step`
- `output_path`
- `result_items`
- `error`
- `error_detail`

The **Output Mode** option can return the whole job or one item per `metadata.result_items` entry.

Binary result download is intentionally not included in V1 because the current backend does not expose a public output download route. Once the backend adds signed artifact URLs or a route such as `GET /outputs/{job_id}/{file}`, the node can add a `Download Result to Binary` toggle.

## Long Jobs

The **Wait** operation uses polling. Polling keeps an n8n execution worker occupied while the video renders. The default interval is 15 seconds and the default timeout is 900 seconds.

For long renders, prefer:

1. Create a job with `webhook_url`.
2. Use **AI Video Engine Trigger** to receive the callback.

## Local Development

```bash
cd n8n-nodes-ai-video-engine
npm install
npm run build
npm test
```

Run in local n8n with the node CLI:

```bash
npm run dev
```

Manual fallback:

```bash
npm run build
npm link
cd ~/.n8n/custom
npm link n8n-nodes-ai-video-engine
```

Restart n8n after linking.

## Publishing

The package is prepared for npm community-node publishing:

- package name: `n8n-nodes-ai-video-engine`
- keyword: `n8n-community-node-package`
- `package.json > n8n` declares nodes and credentials
- GitHub Actions workflow can publish with npm provenance

Update the GitHub repository metadata in `package.json` before the first public release.
