import type {
	IAuthenticateGeneric,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class AiVideoEngineApi implements ICredentialType {
	name = 'aiVideoEngineApi';

	displayName = 'AI Video Engine API';

	documentationUrl = 'https://github.com/your-org/ai-video-engine/tree/main/n8n-nodes-ai-video-engine';

	properties: INodeProperties[] = [
		{
			displayName: 'Base URL',
			name: 'baseUrl',
			type: 'string',
			default: 'http://localhost:6666',
			placeholder: 'https://api.example.com',
			description: 'Base URL of the AI Video Engine FastAPI service',
			required: true,
		},
		{
			displayName: 'Authentication Type',
			name: 'authType',
			type: 'options',
			options: [
				{
					name: 'X-API-Key Header',
					value: 'apiKey',
				},
				{
					name: 'Bearer Token',
					value: 'bearer',
				},
			],
			default: 'apiKey',
			description: 'Header format used by the AI Video Engine API',
		},
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: {
				password: true,
			},
			default: '',
			required: true,
			description: 'Value of API_SECRET_KEY configured on the AI Video Engine server',
		},
	];

	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				'X-API-Key': '={{$credentials.authType === "apiKey" ? $credentials.apiKey : ""}}',
				Authorization: '={{$credentials.authType === "bearer" ? "Bearer " + $credentials.apiKey : ""}}',
			},
		},
	};

	test: ICredentialTestRequest = {
		request: {
			baseURL: '={{$credentials.baseUrl.replace(/\\/+$/, "")}}',
			url: '/jobs?limit=1',
			method: 'GET',
		},
	};
}
