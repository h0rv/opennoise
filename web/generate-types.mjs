import { readFile, writeFile } from 'node:fs/promises';
import { compile } from 'json-schema-to-typescript';
import Ajv from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import standaloneCode from 'ajv/dist/standalone/index.js';
import { build } from 'esbuild';

const schema = JSON.parse(await readFile('../src/opennoise/catalog.schema.json', 'utf8'));
const input = {
  $defs: schema.$defs,
  type: 'object',
  additionalProperties: false,
  properties: Object.fromEntries(
    Object.keys(schema.$defs).map((name) => [name, { $ref: `#/$defs/${name}` }]),
  ),
};
const types = await compile(input, 'CatalogTypes', {
  bannerComment: '',
  unreachableDefinitions: true,
});
await writeFile('src/catalog.d.ts', types);

const definitions = ['Manifest', 'Genres', 'Search', 'GenreDetail', 'ArtistDetail'];
const ajv = new Ajv({ allErrors: true, inlineRefs: false, code: { source: true, esm: true } });
addFormats(ajv);
ajv.addSchema(schema);
const validators = Object.fromEntries(
  definitions.map((name) => [name, `${schema.$id}#/$defs/${name}`]),
);
const { outputFiles } = await build({
  stdin: { contents: standaloneCode(ajv, validators), resolveDir: process.cwd() },
  bundle: true,
  format: 'esm',
  platform: 'browser',
  write: false,
});
await writeFile('src/catalog-validators.js', outputFiles[0].text);
await writeFile(
  'src/catalog-validators.d.ts',
  `import type { ValidateFunction } from 'ajv';\n${definitions
    .map((name) => `export const ${name}: ValidateFunction;`)
    .join('\n')}\n`,
);
