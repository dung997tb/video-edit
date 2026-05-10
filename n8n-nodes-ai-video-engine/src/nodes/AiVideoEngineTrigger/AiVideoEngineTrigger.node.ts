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
		displayName: 'AI Video Engine Trigger',
		name: 'aiVideoEngineTrigger',
		icon: 'file:aiVideoEngine.svg',
		group: ['trigger'],
		version: 1,
		description: 'Starts a workflow when AI Video Engine posts a job callback',
		defaults: {
			name: 'AI Video Engine Trigger',
		},
		inputs: [],
		outputs: [NodeConnectionTypes.Main],
		webhooks: [
			{
				name: 'default',
				httpMethod: 'POST',
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
				default: 'ai-video-engine-callback',
				required: true,
				description: 'Webhook path to paste into AI Video Engine jobs as payload.webhook_url',
			},
			{
				displayName: 'Events',
				name: 'events',
				type: 'multiOptions',
				options: [
					{
						name: 'Completed',
						value: 'job.completed',
					},
					{
						name: 'Failed',
						value: 'job.failed',
					},
					{
						name: 'Cancelled',
						value: 'job.cancelled',
					},
				],
				default: ['job.completed', 'job.failed', 'job.cancelled'],
				description: 'Events allowed to start this workflow',
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
