import { describe, expect, it, vi } from 'vitest';

import {
	buildLowLevelOperations,
	createJobRequest,
	deepMerge,
	jobToExecutionData,
	normalizeBaseUrl,
	parseJsonObject,
	pollJobUntilTerminal,
} from '../src/shared/helpers';
import type { JobResponse } from '../src/shared/types';

describe('shared helpers', () => {
	it('normalizes base URLs', () => {
		expect(normalizeBaseUrl(' http://localhost:6666/// ')).toBe('http://localhost:6666');
	});

	it('parses JSON objects and rejects arrays', () => {
		expect(parseJsonObject('{"a":1}', 'Payload')).toEqual({ a: 1 });
		expect(() => parseJsonObject('[1]', 'Payload')).toThrow('Payload must be a JSON object');
	});

	it('deep merges advanced payload JSON', () => {
		expect(
			deepMerge(
				{
					payload: { voice: 'a', nested: { first: true } },
				},
				{
					payload: { nested: { second: true } },
				},
			),
		).toEqual({
			payload: { voice: 'a', nested: { first: true, second: true } },
		});
	});

	it('builds portable create job requests', () => {
		expect(
			createJobRequest({
				pipelineType: 'low_level',
				sourceMode: 'inputUri',
				inputUri: 'https://example.com/video.mp4',
				payload: { operations: [] },
				priority: 5,
			}),
		).toEqual({
			pipeline_type: 'low_level',
			input_uri: 'https://example.com/video.mp4',
			payload: { operations: [] },
			priority: 5,
		});
	});

	it('normalizes job output and can explode result items', () => {
		const job: JobResponse = {
			id: 'job-1',
			status: 'done',
			output_path: 'output/job/final.mp4',
			metadata: {
				result_items: [{ path: 'output/job/final.mp4', media_type: 'video' }],
			},
		};

		expect(jobToExecutionData(job, 'job', 0)[0].json).toMatchObject({
			job_id: 'job-1',
			status: 'done',
			result_items: [{ path: 'output/job/final.mp4', media_type: 'video' }],
		});
		expect(jobToExecutionData(job, 'resultItems', 0)[0].json).toEqual({
			path: 'output/job/final.mp4',
			media_type: 'video',
			job_id: 'job-1',
			job_status: 'done',
			output_path: 'output/job/final.mp4',
		});
	});

	it('builds low-level templates', () => {
		expect(
			buildLowLevelOperations({
				operationTemplate: 'cutScale',
				cutStart: 1,
				cutDuration: 5,
				scaleWidth: 1280,
				scaleHeight: 720,
			}),
		).toEqual([
			{ type: 'cut', params: { start: 1, duration: 5 } },
			{ type: 'scale', params: { width: 1280, height: 720 } },
		]);
	});

	it('polls until a terminal job status', async () => {
		const fetchJob = vi
			.fn<() => Promise<JobResponse>>()
			.mockResolvedValueOnce({ id: 'job-1', status: 'running' })
			.mockResolvedValueOnce({ id: 'job-1', status: 'done' });
		const sleep = vi.fn(async () => undefined);

		await expect(
			pollJobUntilTerminal(fetchJob, { intervalSeconds: 15, timeoutSeconds: 900, failOnTerminalError: true }, sleep),
		).resolves.toMatchObject({ status: 'done' });
		expect(fetchJob).toHaveBeenCalledTimes(2);
		expect(sleep).toHaveBeenCalledWith(15000);
	});

	it('fails on failed terminal status when configured', async () => {
		await expect(
			pollJobUntilTerminal(
				async () => ({
					id: 'job-1',
					status: 'failed',
					error_detail: { code: 'FFMPEG_FAILED', message: 'render failed' },
				}),
				{ intervalSeconds: 1, timeoutSeconds: 1, failOnTerminalError: true },
				async () => undefined,
			),
		).rejects.toThrow('FFMPEG_FAILED');
	});
});
