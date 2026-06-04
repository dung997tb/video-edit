import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const EXAMPLES_DIR = join(__dirname, '..', 'examples');
const CUSTOM_NODE_TYPES = new Set([
	'n8n-nodes-ai-video-engine.aiVideoEngine',
	'n8n-nodes-ai-video-engine.aiVideoEngineTrigger',
]);

describe('example workflows', () => {
	it('are valid JSON and reference existing custom node types', () => {
		const files = readdirSync(EXAMPLES_DIR).filter((file) => file.endsWith('.json'));

		expect(files.length).toBeGreaterThan(0);
		for (const file of files) {
			const workflow = JSON.parse(readFileSync(join(EXAMPLES_DIR, file), 'utf8')) as {
				nodes?: Array<{ type?: string }>;
			};

			expect(Array.isArray(workflow.nodes), `${file} has nodes`).toBe(true);
			for (const node of workflow.nodes ?? []) {
				if (String(node.type).startsWith('n8n-nodes-ai-video-engine.')) {
					expect(CUSTOM_NODE_TYPES.has(String(node.type)), `${file} references ${node.type}`).toBe(true);
				}
			}
		}
	});
});
