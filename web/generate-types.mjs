import { readFile, writeFile } from 'node:fs/promises';
import { compile } from 'json-schema-to-typescript';

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
