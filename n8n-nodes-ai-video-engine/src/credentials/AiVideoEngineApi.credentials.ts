import type {
	IAuthenticateGeneric,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class AiVideoEngineApi implements ICredentialType {
	name = 'aiVideoEngineApi';

	displayName = 'Mewocamm Video Editor API';

	documentationUrl = 'https://github.com/dung997tb/video-edit/tree/main/n8n-nodes-ai-video-engine';

	properties: INodeProperties[] = [
		{
			displayName: 'Base URL',
			name: 'baseUrl',
			type: 'string',
			default: 'http://localhost:6666',
			placeholder: 'https://api.example.com',
			description: 'URL API backend Mewocamm Video Editor, ví dụ http://localhost:6666 hoặc http://host.docker.internal:6666 khi n8n chạy Docker.',
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
			description: 'Cách gửi khóa xác thực tới API Mewocamm. Mặc định dùng header X-API-Key.',
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
			description: 'Khóa API_SECRET_KEY đang cấu hình trên backend Mewocamm Video Editor.',
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
