// Reproducible compiler; works without a global Foundry installation.
const fs = require('fs');
const path = require('path');
const solc = require('solc');
const root = path.resolve(__dirname, '..');
const files = ['contracts/AtomicArbitrage.sol', 'contracts/FlashLoanArbitrage.sol',
  'polygon/contracts/FlashLoanArbitragePolygon.sol', 'polygon/contracts/CurveFlashArbPolygon.sol'];
if (process.argv.includes('--test')) files.push('tests/contracts/AtomicMocks.sol');
const sources = Object.fromEntries(files.map(f => [f, {content: fs.readFileSync(path.join(root, f), 'utf8')}]));
const input = {language: 'Solidity', sources, settings: {
  optimizer: {enabled: true, runs: 200},
  remappings: ['@openzeppelin/contracts/=lib/openzeppelin-contracts/contracts/', '@aave/core-v3/=lib/aave-v3-core/'],
  outputSelection: {'*': {'*': ['abi', 'evm.bytecode.object', 'evm.deployedBytecode.object']}}
}};
const output = JSON.parse(solc.compile(JSON.stringify(input), {import: f => {
  try { return {contents: fs.readFileSync(path.join(root, f), 'utf8')}; }
  catch (e) { return {error: e.message}; }
}}));
for (const e of output.errors || []) process.stderr.write(e.formattedMessage + '\n');
if ((output.errors || []).some(e => e.severity === 'error')) process.exit(1);
for (const [file, contracts] of Object.entries(output.contracts)) {
  if (!files.includes(file)) continue;
  for (const [name, c] of Object.entries(contracts)) {
    const dir = path.join(root, file.startsWith('polygon/') ? 'polygon/out' : 'out', path.basename(file));
    fs.mkdirSync(dir, {recursive: true});
    fs.writeFileSync(path.join(dir, name + '.json'), JSON.stringify({abi: c.abi,
      bytecode: {object: '0x' + c.evm.bytecode.object},
      deployedBytecode: {object: '0x' + c.evm.deployedBytecode.object}, compiler: solc.version()}, null, 2));
    process.stdout.write(name + '\n');
  }
}
