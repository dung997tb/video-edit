import type {
	IDataObject,
	IExecuteFunctions,
	IHttpRequestMethods,
	IHttpRequestOptions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
} from 'n8n-workflow';
import { NodeConnectionTypes, NodeOperationError } from 'n8n-workflow';

import {
	buildLowLevelOperations,
	createJobRequest,
	jobToExecutionData,
	mergeJsonFields,
	normalizeBaseUrl,
	parseJsonObject,
	pollJobUntilTerminal,
} from '../../shared/helpers';
import type { JobResponse, OutputMode, SourceMode } from '../../shared/types';

const CREDENTIAL_NAME = 'aiVideoEngineApi';

type AiVideoEngineCredentials = {
	baseUrl: string;
	apiKey: string;
	authType: 'apiKey' | 'bearer';
};

export class AiVideoEngine implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'AI Video Engine',
		name: 'aiVideoEngine',
		icon: 'file:aiVideoEngine.svg',
		group: ['transform'],
		version: 1,
		description: 'Create, monitor, and manage AI Video Engine jobs',
		defaults: {
			name: 'AI Video Engine',
		},
		inputs: [NodeConnectionTypes.Main],
		outputs: [NodeConnectionTypes.Main],
		credentials: [
			{
				name: CREDENTIAL_NAME,
				required: true,
			},
		],
		properties: [
			{
				displayName: 'Resource',
				name: 'resource',
				type: 'options',
				noDataExpression: true,
				options: [
					{
						name: 'Job',
						value: 'job',
					},
					{
						name: 'Preset Pipeline',
						value: 'preset',
					},
				],
				default: 'job',
			},
			{
				displayName: 'Operation',
				name: 'jobOperation',
				type: 'options',
				noDataExpression: true,
				displayOptions: {
					show: {
						resource: ['job'],
					},
				},
				options: [
					{
						name: 'Cancel',
						value: 'cancel',
						action: 'Cancel a job',
					},
					{
						name: 'Create Custom',
						value: 'createCustom',
						action: 'Create a custom job',
					},
					{
						name: 'Get',
						value: 'get',
						action: 'Get a job',
					},
					{
						name: 'List',
						value: 'list',
						action: 'List jobs',
					},
					{
						name: 'Upload And Create',
						value: 'uploadAndCreate',
						action: 'Upload binary data and create a job',
					},
					{
						name: 'Wait',
						value: 'wait',
						action: 'Wait for a job to finish',
					},
				],
				default: 'createCustom',
			},
			{
				displayName: 'Operation',
				name: 'presetOperation',
				type: 'options',
				noDataExpression: true,
				displayOptions: {
					show: {
						resource: ['preset'],
					},
				},
				options: [
					{
						name: 'Dubbing',
						value: 'dubbing',
						action: 'Create a dubbing job',
					},
					{
						name: 'Extract Audio',
						value: 'extractAudio',
						action: 'Create an audio extraction job',
					},
					{
						name: 'Extract Frames',
						value: 'extractFrames',
						action: 'Create a frame extraction job',
					},
					{
						name: 'Low Level Edit',
						value: 'lowLevel',
						action: 'Create a low-level edit job',
					},
					{
						name: 'Silence Cut',
						value: 'silenceCut',
						action: 'Create a silence cut job',
					},
					{
						name: 'Subtitle',
						value: 'subtitle',
						action: 'Create a subtitle job',
					},
				],
				default: 'lowLevel',
			},
			...jobFields(),
			...presetFields(),
			...outputFields(),
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];

		for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
			try {
				const resource = this.getNodeParameter('resource', itemIndex) as string;
				if (resource === 'job') {
					returnData.push(...(await executeJobOperation.call(this, itemIndex, items)));
				} else {
					returnData.push(...(await executePresetOperation.call(this, itemIndex)));
				}
			} catch (error) {
				if (this.continueOnFail()) {
					returnData.push({
						json: {
							error: error instanceof Error ? error.message : String(error),
						},
						pairedItem: { item: itemIndex },
					});
					continue;
				}
				throw error;
			}
		}

		return [returnData];
	}
}

async function executeJobOperation(
	this: IExecuteFunctions,
	itemIndex: number,
	items: INodeExecutionData[],
): Promise<INodeExecutionData[]> {
	const operation = this.getNodeParameter('jobOperation', itemIndex) as string;
	const outputMode = this.getNodeParameter('outputMode', itemIndex, 'job') as OutputMode;

	if (operation === 'createCustom') {
		const job = await createCustomJob.call(this, itemIndex);
		return jobToExecutionData(job, outputMode, itemIndex);
	}

	if (operation === 'uploadAndCreate') {
		const job = await uploadAndCreateJob.call(this, itemIndex, items[itemIndex]);
		return jobToExecutionData(job, outputMode, itemIndex);
	}

	if (operation === 'get') {
		const jobId = this.getNodeParameter('jobId', itemIndex) as string;
		const job = await apiRequest.call(this, 'GET', `/jobs/${encodeURIComponent(jobId)}`) as JobResponse;
		return jobToExecutionData(job, outputMode, itemIndex);
	}

	if (operation === 'list') {
		const status = this.getNodeParameter('status', itemIndex, '') as string;
		const limit = this.getNodeParameter('limit', itemIndex, 50) as number;
		const response = await apiRequest.call(this, 'GET', '/jobs', undefined, {
			limit,
			...(status ? { status } : {}),
		}) as { items?: JobResponse[] };
		return (response.items ?? []).map((job) => ({
			json: jobToExecutionData(job, 'job', itemIndex)[0].json,
			pairedItem: { item: itemIndex },
		}));
	}

	if (operation === 'cancel') {
		const jobId = this.getNodeParameter('jobId', itemIndex) as string;
		const response = await apiRequest.call(this, 'POST', `/jobs/${encodeURIComponent(jobId)}/cancel`) as IDataObject;
		return [{ json: response, pairedItem: { item: itemIndex } }];
	}

	if (operation === 'wait') {
		const jobId = this.getNodeParameter('jobId', itemIndex) as string;
		const intervalSeconds = this.getNodeParameter('intervalSeconds', itemIndex, 15) as number;
		const timeoutSeconds = this.getNodeParameter('timeoutSeconds', itemIndex, 900) as number;
		const failOnTerminalError = this.getNodeParameter('failOnTerminalError', itemIndex, true) as boolean;
		const job = await pollJobUntilTerminal(
			async () => apiRequest.call(this, 'GET', `/jobs/${encodeURIComponent(jobId)}`) as Promise<JobResponse>,
			{ intervalSeconds, timeoutSeconds, failOnTerminalError },
		);
		return jobToExecutionData(job, outputMode, itemIndex);
	}

	throw new NodeOperationError(this.getNode(), `Unsupported job operation: ${operation}`, { itemIndex });
}

async function executePresetOperation(this: IExecuteFunctions, itemIndex: number): Promise<INodeExecutionData[]> {
	const operation = this.getNodeParameter('presetOperation', itemIndex) as string;
	const outputMode = this.getNodeParameter('outputMode', itemIndex, 'job') as OutputMode;
	const sourceMode = this.getNodeParameter('sourceMode', itemIndex) as SourceMode;
	const inputUri = this.getNodeParameter('inputUri', itemIndex, '') as string;
	const sourceKey = this.getNodeParameter('sourceKey', itemIndex, '') as string;
	const priority = this.getNodeParameter('priority', itemIndex, 0) as number;
	const metadata = parseJsonObject(this.getNodeParameter('metadataJson', itemIndex, '{}'), 'Metadata JSON');
	const webhookUrl = this.getNodeParameter('webhookUrl', itemIndex, '') as string;
	const outputName = this.getNodeParameter('outputName', itemIndex, '') as string;
	const advancedPayload = parseJsonObject(
		this.getNodeParameter('advancedPayloadJson', itemIndex, '{}'),
		'Advanced Payload JSON',
	);

	let pipelineType = '';
	let payload: IDataObject = {};

	if (operation === 'lowLevel') {
		pipelineType = 'low_level';
		payload = {
			operations: buildLowLevelOperations({
				operationTemplate: this.getNodeParameter('operationTemplate', itemIndex),
				cutStart: this.getNodeParameter('cutStart', itemIndex, 0),
				cutDuration: this.getNodeParameter('cutDuration', itemIndex, 10),
				scaleWidth: this.getNodeParameter('scaleWidth', itemIndex, 1080),
				scaleHeight: this.getNodeParameter('scaleHeight', itemIndex, 1920),
				portraitWidth: this.getNodeParameter('portraitWidth', itemIndex, 1080),
				portraitHeight: this.getNodeParameter('portraitHeight', itemIndex, 1920),
				borderSize: this.getNodeParameter('borderSize', itemIndex, 0),
				borderColor: this.getNodeParameter('borderColor', itemIndex, '#000000'),
				autoZoomIntervalSeconds: this.getNodeParameter('autoZoomIntervalSeconds', itemIndex, 5),
				secondVideoUri: this.getNodeParameter('secondVideoUri', itemIndex, ''),
				hstackWidth: this.getNodeParameter('hstackWidth', itemIndex, 1280),
				hstackHeight: this.getNodeParameter('hstackHeight', itemIndex, 720),
				brollVideoUri: this.getNodeParameter('brollVideoUri', itemIndex, ''),
				splitRatio: this.getNodeParameter('splitRatio', itemIndex, 0.5),
				audioSource: this.getNodeParameter('audioSource', itemIndex, 'mix'),
				semitones: this.getNodeParameter('semitones', itemIndex, 2),
				fadeDuration: this.getNodeParameter('fadeDuration', itemIndex, 0.5),
				volume: this.getNodeParameter('volume', itemIndex, 0.9),
				operationsJson: this.getNodeParameter('operationsJson', itemIndex, '{"operations": []}'),
			}),
		};
	} else if (operation === 'dubbing') {
		pipelineType = 'dubbing';
		payload = {
			source_language: this.getNodeParameter('sourceLanguage', itemIndex, 'auto'),
			target_language: this.getNodeParameter('targetLanguage', itemIndex, 'vi'),
			translator_service: this.getNodeParameter('translatorService', itemIndex, 'google'),
			tts_voice: this.getNodeParameter('ttsVoice', itemIndex, 'vi-VN-HoaiMyNeural'),
			tts_rate: this.getNodeParameter('ttsRate', itemIndex, '-5%'),
		};
	} else if (operation === 'subtitle') {
		pipelineType = 'subtitle';
		payload = {
			language: this.getNodeParameter('subtitleLanguage', itemIndex, 'auto'),
			burn_subtitle: this.getNodeParameter('burnSubtitle', itemIndex, true),
			font_size: this.getNodeParameter('fontSize', itemIndex, 28),
			font_color: this.getNodeParameter('fontColor', itemIndex, 'white'),
			stroke_color: this.getNodeParameter('strokeColor', itemIndex, 'black'),
			stroke_width: this.getNodeParameter('strokeWidth', itemIndex, 2),
		};
	} else if (operation === 'silenceCut') {
		pipelineType = 'silence_cut';
		payload = {
			min_silence_duration: this.getNodeParameter('minSilenceDuration', itemIndex, 0.3),
			silence_threshold_db: this.getNodeParameter('silenceThresholdDb', itemIndex, -35),
		};
	} else if (operation === 'extractAudio') {
		pipelineType = 'audio-extract';
		payload = {
			format: this.getNodeParameter('audioFormat', itemIndex, 'wav'),
			sample_rate: this.getNodeParameter('sampleRate', itemIndex, 44100),
		};
	} else if (operation === 'extractFrames') {
		pipelineType = 'extract_frames';
		payload = {
			fps: this.getNodeParameter('fps', itemIndex, 1),
			format: this.getNodeParameter('imageFormat', itemIndex, 'jpg'),
			max_frames: this.getNodeParameter('maxFrames', itemIndex, 10),
		};
	} else {
		throw new NodeOperationError(this.getNode(), `Unsupported preset operation: ${operation}`, { itemIndex });
	}

	if (webhookUrl) {
		payload.webhook_url = webhookUrl;
	}
	if (outputName) {
		payload.output_name = outputName;
	}
	payload = {
		...payload,
		...advancedPayload,
	};

	const request = createJobRequest({
		pipelineType,
		sourceMode,
		inputUri,
		sourceKey,
		payload,
		metadata,
		priority,
	});
	const job = await apiRequest.call(this, 'POST', '/jobs', request) as JobResponse;
	return jobToExecutionData(job, outputMode, itemIndex);
}

async function createCustomJob(this: IExecuteFunctions, itemIndex: number): Promise<JobResponse> {
	const pipelineType = this.getNodeParameter('pipelineType', itemIndex) as string;
	const sourceMode = this.getNodeParameter('sourceMode', itemIndex) as SourceMode;
	const inputUri = this.getNodeParameter('inputUri', itemIndex, '') as string;
	const sourceKey = this.getNodeParameter('sourceKey', itemIndex, '') as string;
	const priority = this.getNodeParameter('priority', itemIndex, 0) as number;
	const payload = mergeJsonFields(
		this.getNodeParameter('payloadJson', itemIndex, '{}'),
		this.getNodeParameter('advancedPayloadJson', itemIndex, '{}'),
		'Payload JSON',
	);
	const metadata = parseJsonObject(this.getNodeParameter('metadataJson', itemIndex, '{}'), 'Metadata JSON');
	const request = createJobRequest({ pipelineType, sourceMode, inputUri, sourceKey, payload, metadata, priority });
	return apiRequest.call(this, 'POST', '/jobs', request) as Promise<JobResponse>;
}

async function uploadAndCreateJob(
	this: IExecuteFunctions,
	itemIndex: number,
	item: INodeExecutionData,
): Promise<JobResponse> {
	const binaryPropertyName = this.getNodeParameter('binaryPropertyName', itemIndex, 'data') as string;
	const binary = item.binary?.[binaryPropertyName];
	if (!binary) {
		throw new NodeOperationError(this.getNode(), `No binary data found in property "${binaryPropertyName}"`, {
			itemIndex,
		});
	}

	const buffer = await this.helpers.getBinaryDataBuffer(itemIndex, binaryPropertyName);
	const pipelineType = this.getNodeParameter('pipelineType', itemIndex) as string;
	const payload = mergeJsonFields(
		this.getNodeParameter('payloadJson', itemIndex, '{}'),
		this.getNodeParameter('advancedPayloadJson', itemIndex, '{}'),
		'Payload JSON',
	);
	const metadata = parseJsonObject(this.getNodeParameter('metadataJson', itemIndex, '{}'), 'Metadata JSON');
	const form = new FormData();
	form.append(
		'file',
		new Blob([buffer], { type: binary.mimeType ?? 'application/octet-stream' }),
		binary.fileName ?? 'input.bin',
	);
	form.append('pipeline_type', pipelineType);
	form.append('payload_json', JSON.stringify(payload));
	form.append('metadata_json', JSON.stringify(metadata));

	return apiRequest.call(this, 'POST', '/jobs/upload', form, undefined, false) as Promise<JobResponse>;
}

async function apiRequest(
	this: IExecuteFunctions,
	method: IHttpRequestMethods,
	path: string,
	body?: IDataObject | FormData,
	qs?: IDataObject,
	json = true,
): Promise<unknown> {
	const credentials = await this.getCredentials<AiVideoEngineCredentials>(CREDENTIAL_NAME);
	const baseUrl = normalizeBaseUrl(credentials.baseUrl);
	const requestOptions: IHttpRequestOptions = {
		method,
		url: `${baseUrl}${path}`,
		json,
	};
	if (body !== undefined) {
		requestOptions.body = body;
	}
	if (qs !== undefined) {
		requestOptions.qs = qs;
	}
	try {
		return await this.helpers.httpRequestWithAuthentication.call(this, CREDENTIAL_NAME, requestOptions);
	} catch (error) {
		if (error instanceof Error) {
			throw new NodeOperationError(this.getNode(), error.message);
		}
		throw error;
	}
}

function sourceInputFields(displayOperations: string[], resource: string): INodeTypeDescription['properties'] {
	const sourceModeDisplay = showFor(resource, displayOperations);
	const sourceModeShow = sourceModeDisplay.show as IDataObject;
	return [
		{
			displayName: 'Source Mode',
			name: 'sourceMode',
			type: 'options',
			options: [
				{
					name: 'Input URI',
					value: 'inputUri',
				},
				{
					name: 'Source Key',
					value: 'sourceKey',
				},
			],
			default: 'inputUri',
			description: 'Portable source selection; local input_path is intentionally not exposed',
			displayOptions: sourceModeDisplay,
		},
		{
			displayName: 'Input URI',
			name: 'inputUri',
			type: 'string',
			default: '',
			placeholder: 'https://example.com/video.mp4',
			description: 'HTTP or HTTPS URL of the source media',
			displayOptions: {
				show: {
					...sourceModeShow,
					sourceMode: ['inputUri'],
				},
			},
		},
		{
			displayName: 'Source Key',
			name: 'sourceKey',
			type: 'string',
			default: '',
			placeholder: 'uploads/sha256/input.mp4',
			description: 'Artifact-store key already available to AI Video Engine',
			displayOptions: {
				show: {
					...sourceModeShow,
					sourceMode: ['sourceKey'],
				},
			},
		},
	];
}

function jobFields(): INodeTypeDescription['properties'] {
	const createOps = ['createCustom'];
	const uploadOps = ['uploadAndCreate'];
	const idOps = ['get', 'cancel', 'wait'];
	return [
		{
			displayName: 'Pipeline Type',
			name: 'pipelineType',
			type: 'string',
			default: 'low_level',
			placeholder: 'low_level',
			displayOptions: {
				show: {
					resource: ['job'],
					jobOperation: [...createOps, ...uploadOps],
				},
			},
		},
		...sourceInputFields(createOps, 'job'),
		{
			displayName: 'Binary Property',
			name: 'binaryPropertyName',
			type: 'string',
			default: 'data',
			description: 'Name of the incoming binary property to upload',
			displayOptions: showFor('job', uploadOps),
		},
		{
			displayName: 'Job ID',
			name: 'jobId',
			type: 'string',
			default: '',
			required: true,
			displayOptions: showFor('job', idOps),
		},
		{
			displayName: 'Status',
			name: 'status',
			type: 'options',
			options: [
				{ name: 'Any', value: '' },
				{ name: 'Pending', value: 'pending' },
				{ name: 'Running', value: 'running' },
				{ name: 'Done', value: 'done' },
				{ name: 'Failed', value: 'failed' },
				{ name: 'Cancelled', value: 'cancelled' },
			],
			default: '',
			displayOptions: showFor('job', ['list']),
		},
		{
			displayName: 'Limit',
			name: 'limit',
			type: 'number',
			typeOptions: {
				minValue: 1,
				maxValue: 200,
			},
			default: 50,
			displayOptions: showFor('job', ['list']),
		},
		{
			displayName: 'Payload JSON',
			name: 'payloadJson',
			type: 'json',
			default: '{}',
			description: 'Pipeline payload JSON object',
			displayOptions: showFor('job', [...createOps, ...uploadOps]),
		},
		...commonJobOptions('job', [...createOps, ...uploadOps]),
		...waitFields('job'),
	];
}

function presetFields(): INodeTypeDescription['properties'] {
	const presetOps = ['lowLevel', 'dubbing', 'subtitle', 'silenceCut', 'extractAudio', 'extractFrames'];
	return [
		...sourceInputFields(presetOps, 'preset'),
		{
			displayName: 'Operation Template',
			name: 'operationTemplate',
			type: 'options',
			options: [
				{ name: 'Audio Operations', value: 'audioOps' },
				{ name: 'Custom JSON', value: 'customJson' },
				{ name: 'Cut And Scale', value: 'cutScale' },
				{ name: 'Portrait Reframe', value: 'portrait' },
				{ name: 'Split Screen', value: 'splitScreen' },
				{ name: 'Split Screen HStack', value: 'hstack' },
			],
			default: 'cutScale',
			displayOptions: showFor('preset', ['lowLevel']),
		},
		...lowLevelFields(),
		...dubbingFields(),
		...subtitleFields(),
		...silenceCutFields(),
		...extractFields(),
		{
			displayName: 'Webhook URL',
			name: 'webhookUrl',
			type: 'string',
			default: '',
			placeholder: 'https://n8n.example/webhook/ai-video-engine',
			description: 'Optional callback URL. Prefer this with the trigger node for long renders.',
			displayOptions: showFor('preset', presetOps),
		},
		{
			displayName: 'Output Name',
			name: 'outputName',
			type: 'string',
			default: '',
			description: 'Optional output folder/name hint passed to the backend payload',
			displayOptions: showFor('preset', presetOps),
		},
		...commonJobOptions('preset', presetOps),
	];
}

function lowLevelFields(): INodeTypeDescription['properties'] {
	return [
		{
			displayName: 'Cut Start',
			name: 'cutStart',
			type: 'number',
			default: 0,
			displayOptions: showForLowLevelTemplate(['cutScale']),
		},
		{
			displayName: 'Cut Duration',
			name: 'cutDuration',
			type: 'number',
			default: 10,
			displayOptions: showForLowLevelTemplate(['cutScale']),
		},
		{
			displayName: 'Width',
			name: 'scaleWidth',
			type: 'number',
			default: 1080,
			displayOptions: showForLowLevelTemplate(['cutScale']),
		},
		{
			displayName: 'Height',
			name: 'scaleHeight',
			type: 'number',
			default: 1920,
			displayOptions: showForLowLevelTemplate(['cutScale']),
		},
		{
			displayName: 'Portrait Width',
			name: 'portraitWidth',
			type: 'number',
			default: 1080,
			displayOptions: showForLowLevelTemplate(['portrait']),
		},
		{
			displayName: 'Portrait Height',
			name: 'portraitHeight',
			type: 'number',
			default: 1920,
			displayOptions: showForLowLevelTemplate(['portrait']),
		},
		{
			displayName: 'Border Size',
			name: 'borderSize',
			type: 'number',
			default: 0,
			displayOptions: showForLowLevelTemplate(['portrait']),
		},
		{
			displayName: 'Border Color',
			name: 'borderColor',
			type: 'string',
			default: '#000000',
			displayOptions: showForLowLevelTemplate(['portrait']),
		},
		{
			displayName: 'Auto Zoom Interval Seconds',
			name: 'autoZoomIntervalSeconds',
			type: 'number',
			default: 5,
			displayOptions: showForLowLevelTemplate(['portrait']),
		},
		{
			displayName: 'Second Video URI or Path',
			name: 'secondVideoUri',
			type: 'string',
			default: '',
			displayOptions: showForLowLevelTemplate(['hstack']),
		},
		{
			displayName: 'Output Width',
			name: 'hstackWidth',
			type: 'number',
			default: 1280,
			displayOptions: showForLowLevelTemplate(['hstack']),
		},
		{
			displayName: 'Output Height',
			name: 'hstackHeight',
			type: 'number',
			default: 720,
			displayOptions: showForLowLevelTemplate(['hstack']),
		},
		{
			displayName: 'B-Roll Video URI or Path',
			name: 'brollVideoUri',
			type: 'string',
			default: '',
			displayOptions: showForLowLevelTemplate(['splitScreen']),
		},
		{
			displayName: 'Split Ratio',
			name: 'splitRatio',
			type: 'number',
			default: 0.5,
			displayOptions: showForLowLevelTemplate(['splitScreen']),
		},
		{
			displayName: 'Audio Source',
			name: 'audioSource',
			type: 'options',
			options: [
				{ name: 'Main', value: 'main' },
				{ name: 'B-Roll', value: 'broll' },
				{ name: 'Mix', value: 'mix' },
			],
			default: 'mix',
			displayOptions: showForLowLevelTemplate(['splitScreen']),
		},
		{
			displayName: 'Semitones',
			name: 'semitones',
			type: 'number',
			default: 2,
			displayOptions: showForLowLevelTemplate(['audioOps']),
		},
		{
			displayName: 'Fade Duration',
			name: 'fadeDuration',
			type: 'number',
			default: 0.5,
			displayOptions: showForLowLevelTemplate(['audioOps']),
		},
		{
			displayName: 'Volume',
			name: 'volume',
			type: 'number',
			default: 0.9,
			displayOptions: showForLowLevelTemplate(['audioOps']),
		},
		{
			displayName: 'Operations JSON',
			name: 'operationsJson',
			type: 'json',
			default: '{\n  "operations": [\n    {"type": "cut", "params": {"start": 0, "duration": 5}}\n  ]\n}',
			description: 'JSON object with an operations array',
			displayOptions: showForLowLevelTemplate(['customJson']),
		},
	];
}

function dubbingFields(): INodeTypeDescription['properties'] {
	return [
		{
			displayName: 'Source Language',
			name: 'sourceLanguage',
			type: 'string',
			default: 'auto',
			displayOptions: showFor('preset', ['dubbing']),
		},
		{
			displayName: 'Target Language',
			name: 'targetLanguage',
			type: 'string',
			default: 'vi',
			displayOptions: showFor('preset', ['dubbing']),
		},
		{
			displayName: 'Translator Service',
			name: 'translatorService',
			type: 'options',
			options: [
				{ name: 'Google', value: 'google' },
				{ name: 'DeepL', value: 'deepl' },
				{ name: 'LibreTranslate', value: 'libretranslate' },
			],
			default: 'google',
			displayOptions: showFor('preset', ['dubbing']),
		},
		{
			displayName: 'TTS Voice',
			name: 'ttsVoice',
			type: 'string',
			default: 'vi-VN-HoaiMyNeural',
			displayOptions: showFor('preset', ['dubbing']),
		},
		{
			displayName: 'TTS Rate',
			name: 'ttsRate',
			type: 'string',
			default: '-5%',
			displayOptions: showFor('preset', ['dubbing']),
		},
	];
}

function subtitleFields(): INodeTypeDescription['properties'] {
	return [
		{
			displayName: 'Language',
			name: 'subtitleLanguage',
			type: 'string',
			default: 'auto',
			displayOptions: showFor('preset', ['subtitle']),
		},
		{
			displayName: 'Burn Subtitle',
			name: 'burnSubtitle',
			type: 'boolean',
			default: true,
			displayOptions: showFor('preset', ['subtitle']),
		},
		{
			displayName: 'Font Size',
			name: 'fontSize',
			type: 'number',
			default: 28,
			displayOptions: showFor('preset', ['subtitle']),
		},
		{
			displayName: 'Font Color',
			name: 'fontColor',
			type: 'string',
			default: 'white',
			displayOptions: showFor('preset', ['subtitle']),
		},
		{
			displayName: 'Stroke Color',
			name: 'strokeColor',
			type: 'string',
			default: 'black',
			displayOptions: showFor('preset', ['subtitle']),
		},
		{
			displayName: 'Stroke Width',
			name: 'strokeWidth',
			type: 'number',
			default: 2,
			displayOptions: showFor('preset', ['subtitle']),
		},
	];
}

function silenceCutFields(): INodeTypeDescription['properties'] {
	return [
		{
			displayName: 'Minimum Silence Duration',
			name: 'minSilenceDuration',
			type: 'number',
			default: 0.3,
			displayOptions: showFor('preset', ['silenceCut']),
		},
		{
			displayName: 'Silence Threshold DB',
			name: 'silenceThresholdDb',
			type: 'number',
			default: -35,
			displayOptions: showFor('preset', ['silenceCut']),
		},
	];
}

function extractFields(): INodeTypeDescription['properties'] {
	return [
		{
			displayName: 'Audio Format',
			name: 'audioFormat',
			type: 'options',
			options: [
				{ name: 'WAV', value: 'wav' },
				{ name: 'MP3', value: 'mp3' },
				{ name: 'M4A', value: 'm4a' },
			],
			default: 'wav',
			displayOptions: showFor('preset', ['extractAudio']),
		},
		{
			displayName: 'Sample Rate',
			name: 'sampleRate',
			type: 'number',
			default: 44100,
			displayOptions: showFor('preset', ['extractAudio']),
		},
		{
			displayName: 'FPS',
			name: 'fps',
			type: 'number',
			default: 1,
			displayOptions: showFor('preset', ['extractFrames']),
		},
		{
			displayName: 'Image Format',
			name: 'imageFormat',
			type: 'options',
			options: [
				{ name: 'JPG', value: 'jpg' },
				{ name: 'PNG', value: 'png' },
				{ name: 'WEBP', value: 'webp' },
			],
			default: 'jpg',
			displayOptions: showFor('preset', ['extractFrames']),
		},
		{
			displayName: 'Max Frames',
			name: 'maxFrames',
			type: 'number',
			default: 10,
			displayOptions: showFor('preset', ['extractFrames']),
		},
	];
}

function commonJobOptions(resource: string, operations: string[]): INodeTypeDescription['properties'] {
	return [
		{
			displayName: 'Priority',
			name: 'priority',
			type: 'number',
			default: 0,
			typeOptions: {
				minValue: 0,
			},
			displayOptions: showFor(resource, operations),
		},
		{
			displayName: 'Metadata JSON',
			name: 'metadataJson',
			type: 'json',
			default: '{}',
			description: 'Optional job metadata JSON object',
			displayOptions: showFor(resource, operations),
		},
		{
			displayName: 'Advanced Payload JSON',
			name: 'advancedPayloadJson',
			type: 'json',
			default: '{}',
			description: 'JSON object merged into the generated payload. Values here override preset fields.',
			displayOptions: showFor(resource, operations),
		},
	];
}

function waitFields(resource: string): INodeTypeDescription['properties'] {
	return [
		{
			displayName: 'Poll Interval Seconds',
			name: 'intervalSeconds',
			type: 'number',
			default: 15,
			description: 'Polling keeps the n8n execution worker occupied. Use a webhook trigger for long renders.',
			displayOptions: showFor(resource, ['wait']),
		},
		{
			displayName: 'Timeout Seconds',
			name: 'timeoutSeconds',
			type: 'number',
			default: 900,
			description: 'Maximum time to wait for the job to reach done, failed, or cancelled',
			displayOptions: showFor(resource, ['wait']),
		},
		{
			displayName: 'Fail on Failed or Cancelled',
			name: 'failOnTerminalError',
			type: 'boolean',
			default: true,
			displayOptions: showFor(resource, ['wait']),
		},
	];
}

function outputFields(): INodeTypeDescription['properties'] {
	return [
		{
			displayName: 'Output Mode',
			name: 'outputMode',
			type: 'options',
			options: [
				{
					name: 'Job',
					value: 'job',
					description: 'Return the normalized job response',
				},
				{
					name: 'Result Items',
					value: 'resultItems',
					description: 'Return one n8n item per metadata.result_items entry when available',
				},
			],
			default: 'job',
			description: 'Binary result download is not available in V1 because the backend has no public output route yet.',
		},
	];
}

function showFor(resource: string, operations: string[]): IDataObject {
	const operationKey = resource === 'job' ? 'jobOperation' : 'presetOperation';
	return {
		show: {
			resource: [resource],
			[operationKey]: operations,
		},
	};
}

function showForLowLevelTemplate(templates: string[]): IDataObject {
	return {
		show: {
			resource: ['preset'],
			presetOperation: ['lowLevel'],
			operationTemplate: templates,
		},
	};
}
