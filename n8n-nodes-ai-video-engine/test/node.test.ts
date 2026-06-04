import { describe, expect, it, vi } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AiVideoEngineApi } from '../src/credentials/AiVideoEngineApi.credentials';
import { AiVideoEngine } from '../src/nodes/AiVideoEngine/AiVideoEngine.node';
import { AiVideoEngineTrigger } from '../src/nodes/AiVideoEngineTrigger/AiVideoEngineTrigger.node';

type Params = Record<string, unknown>;

function optionValues(node: AiVideoEngine, propertyName: string): string[] {
	const property = node.description.properties.find((item) => item.name === propertyName) as
		| { options?: Array<{ value: string }> }
		| undefined;
	return property?.options?.map((item) => item.value) ?? [];
}

function propertyDescription(node: AiVideoEngine, propertyName: string): string {
	const property = node.description.properties.find((item) => item.name === propertyName);
	return String(property?.description ?? '');
}

function nodeContext(params: Params, response: unknown = { id: 'job-1', status: 'done' }) {
	const httpRequestWithAuthentication = vi.fn(async (_credentialName: string, options: unknown) => {
		const request = options as { url: string };
		if (request.url.endsWith('/jobs')) {
			return response;
		}
		if (request.url.includes('/jobs?')) {
			return response;
		}
		return response;
	});
	return {
		getInputData: () => [{ json: {}, binary: params.binary as never }],
		continueOnFail: () => false,
		getNode: () => ({ name: 'Mewocamm Video Editor', type: 'aiVideoEngine', typeVersion: 1, position: [0, 0] }),
		getCredentials: vi.fn(async () => ({ baseUrl: 'http://localhost:6666///', apiKey: 'key', authType: 'apiKey' })),
		getNodeParameter: (name: string, _itemIndex: number, defaultValue?: unknown) => params[name] ?? defaultValue,
		helpers: {
			httpRequestWithAuthentication,
			getBinaryDataBuffer: vi.fn(async () => Buffer.from('video bytes')),
		},
	};
}

describe('Mewocamm Video Editor node description', () => {
	it('uses the Mewocamm public brand while keeping stable internal names', () => {
		const node = new AiVideoEngine();
		const trigger = new AiVideoEngineTrigger();
		const credential = new AiVideoEngineApi();

		expect(node.description.displayName).toBe('Mewocamm Video Editor');
		expect(node.description.name).toBe('aiVideoEngine');
		expect(node.description.description).toContain('Mewocamm Video Editor');
		expect(node.description.defaults?.name).toBe('Mewocamm Video Editor');
		expect(trigger.description.displayName).toBe('Mewocamm Video Editor Trigger');
		expect(trigger.description.name).toBe('aiVideoEngineTrigger');
		expect(credential.displayName).toBe('Mewocamm Video Editor API');
		expect(credential.name).toBe('aiVideoEngineApi');
	});

	it('declares professional local SVG icons for both nodes', () => {
		const node = new AiVideoEngine();
		const trigger = new AiVideoEngineTrigger();

		expect(node.description.icon).toBe('file:aiVideoEngine.svg');
		expect(trigger.description.icon).toBe('file:aiVideoEngine.svg');
		expect(existsSync(join(__dirname, '..', 'src', 'nodes', 'AiVideoEngine', 'aiVideoEngine.svg'))).toBe(true);
		expect(existsSync(join(__dirname, '..', 'src', 'nodes', 'AiVideoEngineTrigger', 'aiVideoEngine.svg'))).toBe(true);
	});

	it('keeps aliases for Mewocamm and the old AI Video Engine name', () => {
		const actionMetadata = JSON.parse(readFileSync(join(__dirname, '..', 'src', 'nodes', 'AiVideoEngine', 'AiVideoEngine.node.json'), 'utf8')) as { alias: string[] };
		const triggerMetadata = JSON.parse(readFileSync(join(__dirname, '..', 'src', 'nodes', 'AiVideoEngineTrigger', 'AiVideoEngineTrigger.node.json'), 'utf8')) as { alias: string[] };

		expect(actionMetadata.alias).toEqual(expect.arrayContaining(['mewocamm', 'ai video engine', 'video editor', 'lồng tiếng', 'phụ đề', 'cắt video']));
		expect(triggerMetadata.alias).toEqual(expect.arrayContaining(['mewocamm', 'ai video engine', 'video editor']));
	});

	it('adds Vietnamese descriptions to important fields', () => {
		const node = new AiVideoEngine();
		for (const propertyName of ['sourceMode', 'pipelineType', 'payloadJson', 'intervalSeconds', 'outputMode']) {
			expect(propertyDescription(node, propertyName), propertyName).toMatch(/[à-ỹĐđ]/);
		}
	});

	it('exposes job and preset resources', () => {
		const node = new AiVideoEngine();

		expect(optionValues(node, 'resource')).toEqual(['job', 'preset']);
	});

	it('exposes all job operations', () => {
		const node = new AiVideoEngine();

		expect(optionValues(node, 'jobOperation')).toEqual([
			'cancel',
			'createCustom',
			'get',
			'list',
			'uploadAndCreate',
			'wait',
		]);
	});

	it('exposes all preset operations', () => {
		const node = new AiVideoEngine();

		expect(optionValues(node, 'presetOperation')).toEqual([
			'dubbing',
			'extractAudio',
			'extractFrames',
			'lowLevel',
			'silenceCut',
			'subtitle',
			'splitVideo',
		]);
	});
});

describe('Mewocamm Video Editor node API execution', () => {
	it('creates custom jobs with POST /jobs', async () => {
		const node = new AiVideoEngine();
		const context = nodeContext({
			resource: 'job',
			jobOperation: 'createCustom',
			pipelineType: 'low_level',
			sourceMode: 'inputUri',
			inputUri: 'https://example.com/video.mp4',
			payloadJson: '{"operations":[{"type":"cut"}]}',
			metadataJson: '{"case":"custom"}',
			advancedPayloadJson: '{}',
			priority: 5,
			outputMode: 'job',
		});

		await node.execute.call(context as never);

		expect(context.helpers.httpRequestWithAuthentication).toHaveBeenCalledWith('aiVideoEngineApi', expect.objectContaining({
			method: 'POST',
			url: 'http://localhost:6666/jobs',
		}));
	});

	it('uploads binary data with POST /jobs/upload', async () => {
		const node = new AiVideoEngine();
		const context = nodeContext({
			resource: 'job',
			jobOperation: 'uploadAndCreate',
			pipelineType: 'low_level',
			binaryPropertyName: 'data',
			payloadJson: '{"operations":[{"type":"cut"}]}',
			metadataJson: '{}',
			advancedPayloadJson: '{}',
			outputMode: 'job',
			binary: { data: { mimeType: 'video/mp4', fileName: 'clip.mp4' } },
		});

		await node.execute.call(context as never);

		expect(context.helpers.httpRequestWithAuthentication).toHaveBeenCalledWith('aiVideoEngineApi', expect.objectContaining({
			method: 'POST',
			url: 'http://localhost:6666/jobs/upload',
			json: false,
		}));
	});

	it('rejects upload without the configured binary property', async () => {
		const node = new AiVideoEngine();
		const context = nodeContext({
			resource: 'job',
			jobOperation: 'uploadAndCreate',
			pipelineType: 'low_level',
			binaryPropertyName: 'data',
			payloadJson: '{}',
			metadataJson: '{}',
			advancedPayloadJson: '{}',
			outputMode: 'job',
		});

		await expect(node.execute.call(context as never)).rejects.toThrow('No binary data found in property "data"');
	});

	it('gets, lists, cancels, and waits with expected API paths', async () => {
		const node = new AiVideoEngine();
		const cases = [
			{ jobOperation: 'get', expected: { method: 'GET', url: 'http://localhost:6666/jobs/job-1' } },
			{ jobOperation: 'list', expected: { method: 'GET', url: 'http://localhost:6666/jobs' } },
			{ jobOperation: 'cancel', expected: { method: 'POST', url: 'http://localhost:6666/jobs/job-1/cancel' } },
			{ jobOperation: 'wait', expected: { method: 'GET', url: 'http://localhost:6666/jobs/job-1' } },
		];

		for (const item of cases) {
			const response = item.jobOperation === 'list' ? { items: [{ id: 'job-1', status: 'done' }] } : { id: 'job-1', status: 'done' };
			const context = nodeContext({
				resource: 'job',
				jobOperation: item.jobOperation,
				jobId: 'job-1',
				status: '',
				limit: 50,
				intervalSeconds: 1,
				timeoutSeconds: 1,
				failOnTerminalError: true,
				outputMode: 'job',
			}, response);

			await node.execute.call(context as never);

			expect(context.helpers.httpRequestWithAuthentication).toHaveBeenCalledWith('aiVideoEngineApi', expect.objectContaining(item.expected));
		}
	});

	it('creates preset jobs through POST /jobs', async () => {
		const node = new AiVideoEngine();
		for (const presetOperation of ['lowLevel', 'dubbing', 'subtitle', 'silenceCut', 'extractAudio', 'extractFrames', 'splitVideo']) {
			const context = nodeContext({
				resource: 'preset',
				presetOperation,
				sourceMode: 'inputUri',
				inputUri: 'https://example.com/video.mp4',
				operationTemplate: 'cutScale',
				cutStart: 0,
				cutDuration: 5,
				scaleWidth: 1280,
				scaleHeight: 720,
				metadataJson: '{}',
				advancedPayloadJson: '{}',
				webhookUrl: '',
				outputName: '',
				priority: 0,
				outputMode: 'job',
			});

			await node.execute.call(context as never);

			expect(context.helpers.httpRequestWithAuthentication).toHaveBeenCalledWith('aiVideoEngineApi', expect.objectContaining({
				method: 'POST',
				url: 'http://localhost:6666/jobs',
			}));
		}
	});

	it('creates splitVideo preset jobs with the direct split_video contract', async () => {
		const node = new AiVideoEngine();
		const context = nodeContext({
			resource: 'preset',
			presetOperation: 'splitVideo',
			sourceMode: 'inputUri',
			inputUri: 'https://example.com/video.mp4',
			splitMode: 'auto',
			segmentSeconds: 15,
			splitStart: 3,
			splitEnd: 33,
			metadataJson: '{}',
			advancedPayloadJson: '{}',
			webhookUrl: '',
			outputName: '',
			priority: 0,
			outputMode: 'job',
		});

		await node.execute.call(context as never);

		expect(context.helpers.httpRequestWithAuthentication).toHaveBeenCalledWith('aiVideoEngineApi', expect.objectContaining({
			method: 'POST',
			url: 'http://localhost:6666/jobs',
			body: expect.objectContaining({
				pipeline_type: 'split_video',
				payload: {
					segment_seconds: 15,
					start: 3,
					end: 33,
				},
			}),
		}));
		const request = context.helpers.httpRequestWithAuthentication.mock.calls[0][1] as { body: { payload: Record<string, unknown> } };
		expect(request.body.payload).not.toHaveProperty('operations');
	});
});

describe('Mewocamm Video Editor trigger node', () => {
	it('accepts completed, failed, and cancelled callbacks', async () => {
		const trigger = new AiVideoEngineTrigger();
		for (const event of ['job.completed', 'job.failed', 'job.cancelled']) {
			const response = await trigger.webhook.call({
				getBodyData: () => ({
					event,
					job_id: 'job-1',
					status: event.replace('job.', ''),
					output_path: 'output.mp4',
					metadata: { result_items: [{ path: 'output.mp4' }] },
					error: event === 'job.failed' ? 'boom' : null,
					error_detail: event === 'job.failed' ? { code: 'FFMPEG_FAILED' } : null,
				}),
				getNodeParameter: () => ['job.completed', 'job.failed', 'job.cancelled'],
			} as never);

			expect(response.workflowData?.[0]?.[0]?.json).toMatchObject({
				event,
				job_id: 'job-1',
				output_path: 'output.mp4',
				result_items: [{ path: 'output.mp4' }],
			});
		}
	});

	it('ignores events not selected in the events parameter', async () => {
		const trigger = new AiVideoEngineTrigger();

		const response = await trigger.webhook.call({
			getBodyData: () => ({ event: 'job.failed' }),
			getNodeParameter: () => ['job.completed'],
		} as never);

		expect(response.noWebhookResponse).toBe(true);
		expect(response.webhookResponse).toEqual({ ignored: true, event: 'job.failed' });
	});
});
