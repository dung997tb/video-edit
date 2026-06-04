import type {
	IDataObject,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	IWebhookFunctions,
	IWebhookResponseData,
} from 'n8n-workflow';
import { NodeConnectionTypes } from 'n8n-workflow';

export class AiVideoEngineTrigger implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Mewocamm Video Editor Trigger',
		name: 'aiVideoEngineTrigger',
		icon: 'file:aiVideoEngine.svg',
		group: ['trigger'],
		version: 1,
		description: 'Nhận callback khi job video hoàn tất, lỗi hoặc bị hủy.',
		defaults: {
			name: 'Mewocamm Video Editor Trigger',
		},
		inputs: [],
		outputs: [NodeConnectionTypes.Main],
		webhooks: [
			{
				name: 'default',
				httpMethod: 'POST',
				isFullPath: true,
				responseMode: 'onReceived',
				responseData: 'noData',
				path: '={{$parameter["path"]}}',
			},
		],
		properties: [
			{
				displayName: 'Path',
				name: 'path',
				type: 'string',
				default: 'mewocamm-video-callback',
				required: true,
				description: 'Đường dẫn webhook để dán vào payload.webhook_url khi tạo job Mewocamm.',
			},
			{
				displayName: 'Events',
				name: 'events',
				type: 'multiOptions',
				options: [
					{
						name: 'Completed',
						value: 'job.completed',
						description: 'Kích hoạt workflow khi job hoàn tất thành công.',
					},
					{
						name: 'Failed',
						value: 'job.failed',
						description: 'Kích hoạt workflow khi job kết thúc lỗi.',
					},
					{
						name: 'Cancelled',
						value: 'job.cancelled',
						description: 'Kích hoạt workflow khi job bị hủy.',
					},
				],
				default: ['job.completed', 'job.failed', 'job.cancelled'],
				description: 'Chọn loại callback được phép kích hoạt workflow này.',
			},
		],
	};

	async webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
		const body = this.getBodyData();
		const events = this.getNodeParameter('events', []) as string[];
		const event = String(body.event ?? '');
		if (events.length > 0 && !events.includes(event)) {
			return {
				noWebhookResponse: true,
				webhookResponse: { ignored: true, event },
			};
		}

		const normalized = normalizeCallback(body);
		const workflowData: INodeExecutionData[][] = [[{ json: normalized }]];
		return {
			workflowData,
		};
	}
}

function normalizeCallback(body: IDataObject): IDataObject {
	const metadata = isObject(body.metadata) ? body.metadata : {};
	const resultItems = Array.isArray(metadata.result_items) ? metadata.result_items : [];
	return {
		...body,
		event: body.event ?? null,
		job_id: body.job_id ?? null,
		status: body.status ?? null,
		output_path: body.output_path ?? null,
		result_items: resultItems,
		error: body.error ?? null,
		error_detail: body.error_detail ?? null,
	};
}

function isObject(value: unknown): value is IDataObject {
	return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
