import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';

const mappings = [
  ['src/nodes/AiVideoEngine/aiVideoEngine.svg', 'dist/nodes/AiVideoEngine/aiVideoEngine.svg'],
  [
    'src/nodes/AiVideoEngineTrigger/aiVideoEngine.svg',
    'dist/nodes/AiVideoEngineTrigger/aiVideoEngine.svg',
  ],
];

for (const [source, target] of mappings) {
  const targetDir = dirname(target);
  if (!existsSync(targetDir)) {
    mkdirSync(targetDir, { recursive: true });
  }
  cpSync(source, target);
}

const duplicateRoot = join('dist', 'src');
if (existsSync(duplicateRoot)) {
  rmSync(duplicateRoot, { recursive: true, force: true });
}
