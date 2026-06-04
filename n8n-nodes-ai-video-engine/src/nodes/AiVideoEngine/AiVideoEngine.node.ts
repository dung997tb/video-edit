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
		displayName: 'Mewocamm Video Editor',
		name: 'aiVideoEngine',
		icon: 'file:aiVideoEngine.svg',
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["resource"] === "job" ? "Job: " + $parameter["jobOperation"] : "Tác vụ: " + $parameter["presetOperation"]}}',
		description: 'Tạo, chạy, theo dõi và quản lý job xử lý video bằng Mewocamm Video Editor.',
		defaults: {
			name: 'Mewocamm Video Editor',
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
				description: 'Chọn nhóm thao tác: quản lý job trực tiếp hoặc dùng preset xử lý video dựng sẵn.',
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
						description: 'Gửi yêu cầu hủy job đang chờ hoặc đang chạy.',
						action: 'Hủy một job video',
					},
					{
						name: 'Create Custom',
						value: 'createCustom',
						description: 'Tạo job bằng pipeline_type và Payload JSON tự viết.',
						action: 'Tạo job video tùy chỉnh',
					},
					{
						name: 'Get',
						value: 'get',
						description: 'Lấy trạng thái và metadata của một job theo Job ID.',
						action: 'Lấy thông tin một job',
					},
					{
						name: 'List',
						value: 'list',
						description: 'Liệt kê các job gần đây, có thể lọc theo trạng thái.',
						action: 'Liệt kê job video',
					},
					{
						name: 'Upload And Create',
						value: 'uploadAndCreate',
						description: 'Upload binary video từ node trước rồi tạo job xử lý.',
						action: 'Upload video và tạo job',
					},
					{
						name: 'Wait',
						value: 'wait',
						description: 'Chờ job hoàn tất bằng polling. Nên dùng Trigger cho render dài.',
						action: 'Chờ job hoàn tất',
					},
				],
				default: 'createCustom',
				description: 'Chọn thao tác quản lý job muốn chạy.',
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
						description: 'Tạo job lồng tiếng hoặc dịch giọng sang ngôn ngữ đích.',
						action: 'Tạo job lồng tiếng',
					},
					{
						name: 'Extract Audio',
						value: 'extractAudio',
						description: 'Tách âm thanh từ video thành file audio.',
						action: 'Tách âm thanh từ video',
					},
					{
						name: 'Extract Frames',
						value: 'extractFrames',
						description: 'Trích xuất frame ảnh từ video theo FPS và giới hạn số lượng.',
						action: 'Trích xuất frame từ video',
					},
					{
						name: 'Low Level Edit',
						value: 'lowLevel',
						description: 'Chạy các thao tác FFmpeg như cắt, scale, reframe, split screen hoặc JSON tùy chỉnh.',
						action: 'Tạo job cắt ghép video',
					},
					{
						name: 'Silence Cut',
						value: 'silenceCut',
						description: 'Tự động loại bỏ đoạn im lặng hoặc ít tiếng trong video.',
						action: 'Cắt khoảng lặng trong video',
					},
					{
						name: 'Subtitle',
						value: 'subtitle',
						description: 'Tạo phụ đề hoặc burn phụ đề trực tiếp lên video.',
						action: 'Tạo job phụ đề',
					},
					{
						name: 'Split Video — Chia clip thành nhiều đoạn',
						value: 'splitVideo',
						description: 'Chia 1 clip thành nhiều đoạn nhỏ: tự động theo thời lượng cố định hoặc tùy chỉnh từng mốc cắt.',
						action: 'Chia video thành nhiều clip',
					},
				],
				default: 'lowLevel',
				description: 'Chọn preset video/audio dựng sẵn để tạo job nhanh.',
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
	} else if (operation === 'splitVideo') {
		pipelineType = 'split_video';
		const splitMode = this.getNodeParameter('splitMode', itemIndex, 'auto') as string;
		if (splitMode === 'auto') {
			const segmentSeconds = this.getNodeParameter('segmentSeconds', itemIndex, 30) as number;
			const splitStart = this.getNodeParameter('splitStart', itemIndex, 0) as number;
			const splitEnd = this.getNodeParameter('splitEnd', itemIndex, 0) as number;
			payload = {
				segment_seconds: segmentSeconds,
				...(splitStart > 0 ? { start: splitStart } : {}),
				...(splitEnd > 0 ? { end: splitEnd } : {}),
			};
		} else {
			// custom segments mode
			const segmentsJson = this.getNodeParameter('segmentsJson', itemIndex, '[]') as string;
			let segments: unknown;
			try {
				segments = JSON.parse(segmentsJson);
			} catch {
				throw new NodeOperationError(this.getNode(), 'Segments JSON không hợp lệ. Phải là array JSON.', { itemIndex });
			}
			if (!Array.isArray(segments) || segments.length === 0) {
				throw new NodeOperationError(this.getNode(), 'Segments JSON phải là array có ít nhất 1 phần tử.', { itemIndex });
			}
			payload = {
				segments,
			};
		}
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
			description: 'Chọn nguồn video portable: URL HTTP/HTTPS hoặc source_key đã có trong artifact store. Không expose input_path local để tránh phụ thuộc máy chạy.',
			displayOptions: sourceModeDisplay,
		},
		{
			displayName: 'Input URI',
			name: 'inputUri',
			type: 'string',
			default: '',
			placeholder: 'https://example.com/video.mp4',
			description: 'URL HTTP/HTTPS của video nguồn mà backend Mewocamm có thể tải được.',
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
			description: 'Khóa artifact đã tồn tại trong kho lưu trữ của Mewocamm Video Editor.',
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
			description: 'Loại pipeline video muốn chạy, ví dụ low_level, dubbing, subtitle, silence_cut, audio-extract hoặc extract_frames.',
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
			description: 'Tên binary property từ node trước chứa file video cần upload. Mặc định là data.',
			displayOptions: showFor('job', uploadOps),
		},
		{
			displayName: 'Job ID',
			name: 'jobId',
			type: 'string',
			default: '',
			required: true,
			description: 'ID của job Mewocamm cần lấy trạng thái, hủy hoặc chờ hoàn tất.',
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
			description: 'Lọc danh sách job theo trạng thái. Any sẽ lấy mọi trạng thái.',
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
			description: 'Số lượng job tối đa trả về khi liệt kê.',
			displayOptions: showFor('job', ['list']),
		},
		{
			displayName: 'Payload JSON',
			name: 'payloadJson',
			type: 'json',
			default: '{}',
			description: 'Cấu hình xử lý video gửi vào backend Mewocamm. Đây là JSON object truyền vào payload của job.',
			displayOptions: showFor('job', [...createOps, ...uploadOps]),
		},
		...commonJobOptions('job', [...createOps, ...uploadOps]),
		...waitFields('job'),
	];
}

function presetFields(): INodeTypeDescription['properties'] {
	const presetOps = ['lowLevel', 'dubbing', 'subtitle', 'silenceCut', 'extractAudio', 'extractFrames', 'splitVideo'];
	return [
		...sourceInputFields(presetOps, 'preset'),
		{
			displayName: 'Operation Template',
			name: 'operationTemplate',
			type: 'options',
			options: [
				{ name: 'Audio Operations', value: 'audioOps', description: 'Thử nhanh các thao tác âm thanh như pitch, fade và volume.' },
				{ name: 'Custom JSON', value: 'customJson', description: 'Tự viết mảng operations để gọi low_level pipeline.' },
				{ name: 'Cut And Scale', value: 'cutScale', description: 'Cắt một đoạn video rồi scale về kích thước mong muốn.' },
				{ name: 'Portrait Reframe', value: 'portrait', description: 'Đổi video sang khung dọc 9:16 cho TikTok/Reels/Shorts.' },
				{ name: 'Split Screen', value: 'splitScreen', description: 'Ghép video chính và B-roll theo bố cục chia màn hình.' },
				{ name: 'Split Screen HStack', value: 'hstack', description: 'Ghép hai video cạnh nhau theo chiều ngang.' },
			],
			default: 'cutScale',
			description: 'Chọn template low-level edit để node tự tạo operations JSON phù hợp.',
			displayOptions: showFor('preset', ['lowLevel']),
		},
		...lowLevelFields(),
		...dubbingFields(),
		...subtitleFields(),
		...silenceCutFields(),
		...extractFields(),
		...splitVideoFields(),
		{
			displayName: 'Webhook URL',
			name: 'webhookUrl',
			type: 'string',
			default: '',
			placeholder: 'https://n8n.example/webhook/ai-video-engine',
			description: 'URL callback tùy chọn. Với render dài, nên dùng cùng Mewocamm Video Editor Trigger thay vì Wait polling.',
			displayOptions: showFor('preset', presetOps),
		},
		{
			displayName: 'Output Name',
			name: 'outputName',
			type: 'string',
			default: '',
			description: 'Tên gợi ý cho thư mục hoặc file output để dễ nhận biết artifact sau khi job hoàn tất.',
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
			description: 'Thời điểm bắt đầu cắt, tính bằng giây.',
			displayOptions: showForLowLevelTemplate(['cutScale']),
		},
		{
			displayName: 'Cut Duration',
			name: 'cutDuration',
			type: 'number',
			default: 10,
			description: 'Độ dài đoạn video cần giữ lại, tính bằng giây.',
			displayOptions: showForLowLevelTemplate(['cutScale']),
		},
		{
			displayName: 'Width',
			name: 'scaleWidth',
			type: 'number',
			default: 1080,
			description: 'Chiều rộng output sau khi scale.',
			displayOptions: showForLowLevelTemplate(['cutScale']),
		},
		{
			displayName: 'Height',
			name: 'scaleHeight',
			type: 'number',
			default: 1920,
			description: 'Chiều cao output sau khi scale.',
			displayOptions: showForLowLevelTemplate(['cutScale']),
		},
		{
			displayName: 'Portrait Width',
			name: 'portraitWidth',
			type: 'number',
			default: 1080,
			description: 'Chiều rộng output portrait.',
			displayOptions: showForLowLevelTemplate(['portrait']),
		},
		{
			displayName: 'Portrait Height',
			name: 'portraitHeight',
			type: 'number',
			default: 1920,
			description: 'Chiều cao output portrait.',
			displayOptions: showForLowLevelTemplate(['portrait']),
		},
		{
			displayName: 'Border Size',
			name: 'borderSize',
			type: 'number',
			default: 0,
			description: 'Độ dày viền khi reframe portrait.',
			displayOptions: showForLowLevelTemplate(['portrait']),
		},
		{
			displayName: 'Border Color',
			name: 'borderColor',
			type: 'string',
			default: '#000000',
			description: 'Màu viền khi reframe portrait, ví dụ #000000.',
			displayOptions: showForLowLevelTemplate(['portrait']),
		},
		{
			displayName: 'Auto Zoom Interval Seconds',
			name: 'autoZoomIntervalSeconds',
			type: 'number',
			default: 5,
			description: 'Khoảng thời gian giữa các lần auto zoom, tính bằng giây.',
			displayOptions: showForLowLevelTemplate(['portrait']),
		},
		{
			displayName: 'Second Video URI or Path',
			name: 'secondVideoUri',
			type: 'string',
			default: '',
			description: 'URL hoặc path của video thứ hai để ghép cạnh video chính.',
			displayOptions: showForLowLevelTemplate(['hstack']),
		},
		{
			displayName: 'Output Width',
			name: 'hstackWidth',
			type: 'number',
			default: 1280,
			description: 'Chiều rộng output khi ghép ngang hai video.',
			displayOptions: showForLowLevelTemplate(['hstack']),
		},
		{
			displayName: 'Output Height',
			name: 'hstackHeight',
			type: 'number',
			default: 720,
			description: 'Chiều cao output khi ghép ngang hai video.',
			displayOptions: showForLowLevelTemplate(['hstack']),
		},
		{
			displayName: 'B-Roll Video URI or Path',
			name: 'brollVideoUri',
			type: 'string',
			default: '',
			description: 'URL hoặc path của video B-roll dùng trong bố cục split screen.',
			displayOptions: showForLowLevelTemplate(['splitScreen']),
		},
		{
			displayName: 'Split Ratio',
			name: 'splitRatio',
			type: 'number',
			default: 0.5,
			description: 'Tỷ lệ chia màn hình giữa video chính và B-roll.',
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
			description: 'Chọn nguồn âm thanh khi ghép split screen.',
			displayOptions: showForLowLevelTemplate(['splitScreen']),
		},
		{
			displayName: 'Semitones',
			name: 'semitones',
			type: 'number',
			default: 2,
			description: 'Số bán cung dùng cho thao tác đổi pitch âm thanh.',
			displayOptions: showForLowLevelTemplate(['audioOps']),
		},
		{
			displayName: 'Fade Duration',
			name: 'fadeDuration',
			type: 'number',
			default: 0.5,
			description: 'Thời lượng fade in/out âm thanh, tính bằng giây.',
			displayOptions: showForLowLevelTemplate(['audioOps']),
		},
		{
			displayName: 'Volume',
			name: 'volume',
			type: 'number',
			default: 0.9,
			description: 'Hệ số âm lượng đầu ra, ví dụ 1.0 giữ nguyên, 0.9 giảm nhẹ.',
			displayOptions: showForLowLevelTemplate(['audioOps']),
		},
		{
			displayName: 'Operations JSON',
			name: 'operationsJson',
			type: 'json',
			default: '{\n  "operations": [\n    {"type": "cut", "params": {"start": 0, "duration": 5}}\n  ]\n}',
			description: 'JSON object có mảng operations để gửi trực tiếp vào low_level pipeline.',
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
			description: 'Ngôn ngữ gốc của video. Dùng auto nếu muốn backend tự nhận diện.',
			displayOptions: showFor('preset', ['dubbing']),
		},
		{
			displayName: 'Target Language',
			name: 'targetLanguage',
			type: 'string',
			default: 'vi',
			description: 'Ngôn ngữ muốn lồng tiếng đầu ra, ví dụ vi, en, ja.',
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
			description: 'Dịch vụ dịch văn bản dùng trước khi tạo giọng đọc.',
			displayOptions: showFor('preset', ['dubbing']),
		},
		{
			displayName: 'TTS Voice',
			name: 'ttsVoice',
			type: 'string',
			default: 'vi-VN-HoaiMyNeural',
			description: 'Tên giọng TTS dùng để đọc bản dịch.',
			displayOptions: showFor('preset', ['dubbing']),
		},
		{
			displayName: 'TTS Rate',
			name: 'ttsRate',
			type: 'string',
			default: '-5%',
			description: 'Tốc độ đọc của TTS, ví dụ -5% để chậm hơn một chút.',
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
			description: 'Ngôn ngữ phụ đề. Dùng auto nếu muốn backend tự nhận diện.',
			displayOptions: showFor('preset', ['subtitle']),
		},
		{
			displayName: 'Burn Subtitle',
			name: 'burnSubtitle',
			type: 'boolean',
			default: true,
			description: 'Bật để đóng cứng phụ đề lên video; tắt nếu chỉ muốn tạo artifact phụ đề.',
			displayOptions: showFor('preset', ['subtitle']),
		},
		{
			displayName: 'Font Size',
			name: 'fontSize',
			type: 'number',
			default: 28,
			description: 'Cỡ chữ phụ đề khi burn lên video.',
			displayOptions: showFor('preset', ['subtitle']),
		},
		{
			displayName: 'Font Color',
			name: 'fontColor',
			type: 'string',
			default: 'white',
			description: 'Màu chữ phụ đề, ví dụ white hoặc #ffffff.',
			displayOptions: showFor('preset', ['subtitle']),
		},
		{
			displayName: 'Stroke Color',
			name: 'strokeColor',
			type: 'string',
			default: 'black',
			description: 'Màu viền chữ phụ đề để dễ đọc trên nền video.',
			displayOptions: showFor('preset', ['subtitle']),
		},
		{
			displayName: 'Stroke Width',
			name: 'strokeWidth',
			type: 'number',
			default: 2,
			description: 'Độ dày viền chữ phụ đề.',
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
			description: 'Khoảng im lặng tối thiểu để bị cắt, tính bằng giây.',
			displayOptions: showFor('preset', ['silenceCut']),
		},
		{
			displayName: 'Silence Threshold DB',
			name: 'silenceThresholdDb',
			type: 'number',
			default: -35,
			description: 'Ngưỡng âm lượng dB để xem là im lặng. Giá trị càng thấp càng ít cắt.',
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
			description: 'Định dạng file audio đầu ra.',
			displayOptions: showFor('preset', ['extractAudio']),
		},
		{
			displayName: 'Sample Rate',
			name: 'sampleRate',
			type: 'number',
			default: 44100,
			description: 'Sample rate audio đầu ra, ví dụ 44100 hoặc 48000.',
			displayOptions: showFor('preset', ['extractAudio']),
		},
		{
			displayName: 'FPS',
			name: 'fps',
			type: 'number',
			default: 1,
			description: 'Số frame ảnh trích xuất mỗi giây.',
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
			description: 'Định dạng ảnh frame đầu ra.',
			displayOptions: showFor('preset', ['extractFrames']),
		},
		{
			displayName: 'Max Frames',
			name: 'maxFrames',
			type: 'number',
			default: 10,
			description: 'Số frame tối đa cần trích xuất để tránh tạo quá nhiều artifact.',
			displayOptions: showFor('preset', ['extractFrames']),
		},
	];
}

function splitVideoFields(): INodeTypeDescription['properties'] {
	return [
		{
			displayName: 'Chế độ chia',
			name: 'splitMode',
			type: 'options',
			options: [
				{
					name: 'Tự động — Chia đều theo thời lượng',
					value: 'auto',
					description: 'Chia video thành các đoạn bằng nhau theo số giây mỗi đoạn.',
				},
				{
					name: 'Tùy chỉnh — Tự định mốc cắt',
					value: 'custom',
					description: 'Tự xác định từng đoạn bằng JSON array với thời điểm start và end.',
				},
			],
			default: 'auto',
			description: 'Chọn cách chia clip: tự động chia đều hoặc tự định từng mốc cắt.',
			displayOptions: showFor('preset', ['splitVideo']),
		},
		{
			displayName: 'Thời lượng mỗi đoạn (giây)',
			name: 'segmentSeconds',
			type: 'number',
			default: 30,
			description: 'Mỗi clip con dài bao nhiêu giây. Video sẽ được chia thành các đoạn bằng nhau.',
			displayOptions: {
				show: {
					resource: ['preset'],
					presetOperation: ['splitVideo'],
					splitMode: ['auto'],
				},
			},
		},
		{
			displayName: 'Bắt đầu từ (giây) — tùy chọn',
			name: 'splitStart',
			type: 'number',
			default: 0,
			description: 'Bắt đầu chia từ giây này trong video gốc. Để 0 nếu muốn chia từ đầu.',
			displayOptions: {
				show: {
					resource: ['preset'],
					presetOperation: ['splitVideo'],
					splitMode: ['auto'],
				},
			},
		},
		{
			displayName: 'Kết thúc ở (giây) — tùy chọn',
			name: 'splitEnd',
			type: 'number',
			default: 0,
			description: 'Dừng chia ở giây này trong video gốc. Để 0 nếu muốn chia đến hết video.',
			displayOptions: {
				show: {
					resource: ['preset'],
					presetOperation: ['splitVideo'],
					splitMode: ['auto'],
				},
			},
		},
		{
			displayName: 'Danh sách đoạn cắt (JSON)',
			name: 'segmentsJson',
			type: 'json',
			default: '[\n  { "start": 0, "end": 10 },\n  { "start": 15, "end": 30 },\n  { "start": 45, "duration": 20 }\n]',
			description: 'Danh sách các đoạn cắt dưới dạng JSON array. Mỗi phần tử cần có "start" và "end" hoặc "duration" (tính bằng giây).',
			displayOptions: {
				show: {
					resource: ['preset'],
					presetOperation: ['splitVideo'],
					splitMode: ['custom'],
				},
			},
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
			description: 'Độ ưu tiên job. Số lớn hơn có thể được backend xử lý trước tùy cấu hình hàng đợi.',
		},
		{
			displayName: 'Metadata JSON',
			name: 'metadataJson',
			type: 'json',
			default: '{}',
			description: 'Metadata JSON tùy chọn gắn vào job để truy vết workflow, case test hoặc thông tin người dùng.',
			displayOptions: showFor(resource, operations),
		},
		{
			displayName: 'Advanced Payload JSON',
			name: 'advancedPayloadJson',
			type: 'json',
			default: '{}',
			description: 'JSON object merge vào payload đã tạo. Giá trị ở đây sẽ override field preset khi cần cấu hình nâng cao.',
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
			description: 'Số giây giữa mỗi lần polling. Polling giữ worker n8n, nên dùng Trigger cho render dài.',
			displayOptions: showFor(resource, ['wait']),
		},
		{
			displayName: 'Timeout Seconds',
			name: 'timeoutSeconds',
			type: 'number',
			default: 900,
			description: 'Thời gian chờ tối đa để job chuyển sang done, failed hoặc cancelled.',
			displayOptions: showFor(resource, ['wait']),
		},
		{
			displayName: 'Fail on Failed or Cancelled',
			name: 'failOnTerminalError',
			type: 'boolean',
			default: true,
			description: 'Bật để node fail khi job kết thúc ở trạng thái failed hoặc cancelled.',
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
					description: 'Trả về một item chứa job đã được normalize.',
				},
				{
					name: 'Result Items',
					value: 'resultItems',
					description: 'Trả về một item cho mỗi artifact trong metadata.result_items nếu có.',
				},
			],
			default: 'job',
			description: 'Chọn cách trả output cho node sau. V1 chưa tải binary trực tiếp vì backend chưa có public output route.',
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
