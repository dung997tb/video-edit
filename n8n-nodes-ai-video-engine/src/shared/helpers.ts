import type { IDataObject, INodeExecutionData } from 'n8n-workflow';

import type { CreateJobRequest, JobResponse, OutputMode, ResultItem, SourceMode, WaitOptions } from './types';

export const TERMINAL_STATUSES = new Set(['done', 'failed', 'cancelled']);

export function normalizeBaseUrl(baseUrl: string): string {
	return baseUrl.trim().replace(/\/+$/, '');
}

export function parseJsonObject(value: unknown, label: string): IDataObject {
	if (value === undefined || value === null || value === '') {
		return {};
	}
	if (typeof value === 'object' && !Array.isArray(value)) {
		return value as IDataObject;
	}
	if (typeof value !== 'string') {
		throw new Error(`${label} must be a JSON object`);
	}
	try {
		const parsed = JSON.parse(value) as unknown;
		if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
			throw new Error(`${label} must be a JSON object`);
		}
		return parsed as IDataObject;
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		throw new Error(`${label} is not valid JSON: ${message}`);
	}
}

export function deepMerge<T extends IDataObject>(base: T, override: IDataObject): T {
	const output: IDataObject = { ...base };
	for (const [key, value] of Object.entries(override)) {
		const existing = output[key];
		if (isPlainObject(existing) && isPlainObject(value)) {
			output[key] = deepMerge(existing, value);
		} else {
			output[key] = value as IDataObject[keyof IDataObject];
		}
	}
	return output as T;
}

export function mergeJsonFields(baseJson: unknown, advancedJson: unknown, baseLabel: string): IDataObject {
	const base = parseJsonObject(baseJson, baseLabel);
	const advanced = parseJsonObject(advancedJson, 'Advanced Payload JSON');
	return deepMerge(base, advanced);
}

export function sourceFields(sourceMode: SourceMode, inputUri?: string, sourceKey?: string): IDataObject {
	if (sourceMode === 'inputUri') {
		return inputUri ? { input_uri: inputUri } : {};
	}
	return sourceKey ? { source_key: sourceKey } : {};
}

export function createJobRequest(input: {
	pipelineType: string;
	sourceMode: SourceMode;
	inputUri?: string;
	sourceKey?: string;
	payload: IDataObject;
	metadata?: IDataObject;
	priority?: number;
}): CreateJobRequest {
	const request: CreateJobRequest = {
		pipeline_type: input.pipelineType,
		...sourceFields(input.sourceMode, input.inputUri, input.sourceKey),
		payload: input.payload,
	};
	if (input.metadata && Object.keys(input.metadata).length > 0) {
		request.metadata = input.metadata;
	}
	if (typeof input.priority === 'number') {
		request.priority = input.priority;
	}
	return request;
}

export function normalizeJob(job: JobResponse): IDataObject {
	const resultItems = getResultItems(job);
	return {
		...job,
		job_id: job.id,
		status: job.status,
		progress: job.progress ?? 0,
		current_step: job.current_step ?? null,
		output_path: job.output_path ?? null,
		result_items: resultItems,
		error: job.error ?? null,
		error_detail: job.error_detail ?? null,
	};
}

export function getResultItems(job: JobResponse): ResultItem[] {
	const metadata = job.metadata ?? {};
	const resultItems = metadata.result_items;
	return Array.isArray(resultItems) ? resultItems : [];
}

export function jobToExecutionData(job: JobResponse, outputMode: OutputMode, itemIndex: number): INodeExecutionData[] {
	if (outputMode === 'resultItems') {
		const resultItems = getResultItems(job);
		if (resultItems.length > 0) {
			return resultItems.map((item) => ({
				json: {
					...item,
					job_id: job.id,
					job_status: job.status,
					output_path: job.output_path ?? null,
				},
				pairedItem: { item: itemIndex },
			}));
		}
	}
	return [{ json: normalizeJob(job), pairedItem: { item: itemIndex } }];
}

export async function pollJobUntilTerminal(
	fetchJob: () => Promise<JobResponse>,
	options: WaitOptions,
	sleepFn: (milliseconds: number) => Promise<void> = sleep,
	nowFn: () => number = Date.now,
): Promise<JobResponse> {
	const start = nowFn();
	const timeoutMs = Math.max(1, options.timeoutSeconds) * 1000;
	const intervalMs = Math.max(1, options.intervalSeconds) * 1000;
	let lastJob: JobResponse | undefined;

	while (nowFn() - start <= timeoutMs) {
		lastJob = await fetchJob();
		if (TERMINAL_STATUSES.has(String(lastJob.status))) {
			if (options.failOnTerminalError && ['failed', 'cancelled'].includes(String(lastJob.status))) {
				throw new Error(jobErrorMessage(lastJob));
			}
			return lastJob;
		}
		await sleepFn(intervalMs);
	}

	const status = lastJob ? ` Last status: ${lastJob.status}.` : '';
	throw new Error(`Timed out waiting for AI Video Engine job after ${options.timeoutSeconds} seconds.${status}`);
}

export function jobErrorMessage(job: JobResponse): string {
	const detail = job.error_detail;
	const detailMessage = detail && typeof detail.message === 'string' ? detail.message : undefined;
	const code = detail && typeof detail.code === 'string' ? ` (${detail.code})` : '';
	return `AI Video Engine job ${job.id} ended with status ${job.status}${code}: ${detailMessage ?? job.error ?? 'No error detail returned'}`;
}

export function buildLowLevelOperations(input: IDataObject): IDataObject[] {
	const template = String(input.operationTemplate ?? 'customJson');
	switch (template) {
		case 'cutScale':
			return [
				{
					type: 'cut',
					params: {
						start: asNumber(input.cutStart, 0),
						duration: asNumber(input.cutDuration, 10),
					},
				},
				{
					type: 'scale',
					params: {
						width: asNumber(input.scaleWidth, 1080),
						height: asNumber(input.scaleHeight, 1920),
					},
				},
			];
		case 'portrait':
			return [
				{
					type: 'blur_bg_portrait',
					params: {
						output_width: asNumber(input.portraitWidth, 1080),
						output_height: asNumber(input.portraitHeight, 1920),
					},
				},
				{
					type: 'pad_border',
					params: {
						size: asNumber(input.borderSize, 0),
						color: String(input.borderColor ?? '#000000'),
					},
				},
				{
					type: 'auto_zoom',
					params: {
						interval_seconds: asNumber(input.autoZoomIntervalSeconds, 5),
					},
				},
			];
		case 'hstack':
			return [
				{
					type: 'hstack',
					params: {
						second_video: String(input.secondVideoUri ?? ''),
						layout: 'horizontal',
						output_width: asNumber(input.hstackWidth, 1280),
						output_height: asNumber(input.hstackHeight, 720),
					},
				},
			];
		case 'splitScreen':
			return [
				{
					type: 'split_screen',
					params: {
						b_roll_video: String(input.brollVideoUri ?? ''),
						split_ratio: asNumber(input.splitRatio, 0.5),
						audio_source: String(input.audioSource ?? 'mix'),
					},
				},
			];
		case 'audioOps':
			return [
				{
					type: 'audio_pitch',
					params: {
						semitones: asNumber(input.semitones, 2),
						preserve_tempo: true,
					},
				},
				{ type: 'audio_normalize', params: {} },
				{
					type: 'audio_fade',
					params: {
						type: 'in',
						duration: asNumber(input.fadeDuration, 0.5),
					},
				},
				{
					type: 'audio_volume',
					params: {
						volume: asNumber(input.volume, 0.9),
					},
				},
			];
		case 'customJson': {
			const parsed = parseJsonObject(input.operationsJson, 'Operations JSON');
			const operations = parsed.operations;
			if (!Array.isArray(operations)) {
				throw new Error('Operations JSON must contain an operations array');
			}
			return operations as IDataObject[];
		}
		default:
			throw new Error(`Unsupported low-level operation template: ${template}`);
	}
}

function asNumber(value: unknown, fallback: number): number {
	const parsed = Number(value ?? fallback);
	return Number.isFinite(parsed) ? parsed : fallback;
}

function isPlainObject(value: unknown): value is IDataObject {
	return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function sleep(milliseconds: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
