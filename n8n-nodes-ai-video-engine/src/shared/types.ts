import type { IDataObject } from 'n8n-workflow';

export type SourceMode = 'inputUri' | 'sourceKey';

export type JobStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled' | string;

export type ResultItem = IDataObject & {
	id?: string;
	path?: string;
	media_type?: string;
	kind?: string;
	label?: string;
	relative_path?: string;
	artifact_scope?: string;
};

export type JobResponse = IDataObject & {
	id: string;
	status: JobStatus;
	pipeline_type?: string;
	progress?: number;
	current_step?: string | null;
	output_path?: string | null;
	metadata?: IDataObject & {
		result_items?: ResultItem[];
	};
	error?: string | null;
	error_detail?: IDataObject | null;
};

export interface CreateJobRequest extends IDataObject {
	pipeline_type: string;
	input_uri?: string;
	source_key?: string;
	payload: IDataObject;
	metadata?: IDataObject;
	priority?: number;
}

export type OutputMode = 'job' | 'resultItems';

export interface WaitOptions {
	intervalSeconds: number;
	timeoutSeconds: number;
	failOnTerminalError: boolean;
}
