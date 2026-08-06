#!/usr/bin/env node
/**
 * sign-extension.mjs — sign ServerKit extension release zips (plan 55, D3).
 *
 * Extensions are signed with ed25519 detached signatures in a minisign-style
 * envelope: base64 of  "ED" (2 bytes) || key_num (8 bytes) || signature (64
 * bytes), where the signature is over the raw zip bytes and key_num is
 * sha256(public_key)[:8]. The panel pins publisher public keys in
 * backend/app/data/extension_signing_keys.json and verifies at install;
 * unsigned extensions install behind an explicit consent step, and a bad
 * signature is a hard failure. See docs/EXTENSIONS.md ("Release signing").
 *
 * Usage:
 *   node scripts/sign-extension.mjs keygen --key-id <id> [--out <dir>]
 *       Generate a publisher keypair. Writes <out>/<id>.signing-key.json
 *       (KEEP THIS FILE PRIVATE and out of git) and prints the public-key
 *       entry to pin in extension_signing_keys.json.
 *
 *   node scripts/sign-extension.mjs sign <bundle.zip> --key <keyfile.json>
 *       Signs the zip, writes <bundle.zip>.minisig next to it, and prints
 *       the `signature` / `publisher_key_id` fields for the registry index.
 *
 *   node scripts/sign-extension.mjs verify <bundle.zip> --key <keyfile.json>
 *       Local sanity check that a zip verifies against the key's public half
 *       (the same check the panel runs at install).
 */
import { createHash, generateKeyPairSync, createPrivateKey, createPublicKey, sign as edSign, verify as edVerify } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';

const MARKER = Buffer.from('ED'); // pure ed25519 over raw bytes
const KEY_NUM_LEN = 8;

const fail = (msg) => {
  process.stderr.write(`error: ${msg}\n`);
  process.exit(1);
};

const keyNumFor = (pubRaw) =>
  createHash('sha256').update(pubRaw).digest().subarray(0, KEY_NUM_LEN);

function loadKeyFile(path) {
  if (!existsSync(path)) fail(`key file not found: ${path}`);
  let data;
  try {
    data = JSON.parse(readFileSync(path, 'utf8'));
  } catch (e) {
    fail(`could not parse key file ${path}: ${e.message}`);
  }
  if (data.algorithm !== 'ed25519' || !data.secret_key_pkcs8 || !data.public_key) {
    fail(`${path} is not a sign-extension key file (need algorithm/public_key/secret_key_pkcs8)`);
  }
  return data;
}

function cmdKeygen(argv) {
  let keyId = null;
  let outDir = '.';
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--key-id') keyId = argv[++i];
    else if (argv[i] === '--out') outDir = argv[++i];
  }
  if (!keyId || !/^[a-z0-9][a-z0-9-]*$/.test(keyId)) {
    fail('keygen needs --key-id <id> (lowercase letters, digits, dashes)');
  }

  const { publicKey, privateKey } = generateKeyPairSync('ed25519');
  const pubDer = publicKey.export({ type: 'spki', format: 'der' });
  const pubRaw = pubDer.subarray(pubDer.length - 32); // SPKI wrapper → raw key
  const secDer = privateKey.export({ type: 'pkcs8', format: 'der' });

  mkdirSync(outDir, { recursive: true });
  const keyPath = join(outDir, `${keyId}.signing-key.json`);
  writeFileSync(keyPath, JSON.stringify({
    key_id: keyId,
    algorithm: 'ed25519',
    created: new Date().toISOString().slice(0, 10),
    public_key: pubRaw.toString('base64'),
    secret_key_pkcs8: secDer.toString('base64'),
  }, null, 2) + '\n', { mode: 0o600 });

  process.stdout.write(`\nPrivate key written to ${keyPath}\n`);
  process.stdout.write('KEEP IT PRIVATE and out of git — anyone holding it can sign as you.\n');
  process.stdout.write('\nPin this entry in backend/app/data/extension_signing_keys.json:\n\n');
  process.stdout.write(JSON.stringify({
    key_id: keyId,
    publisher: 'ServerKit (first-party)',
    algorithm: 'ed25519',
    public_key: pubRaw.toString('base64'),
  }, null, 2) + '\n');
}

function cmdSign(argv) {
  const zipPath = argv.find((a) => !a.startsWith('--'));
  let keyPath = null;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--key') keyPath = argv[++i];
  }
  if (!zipPath) fail('sign needs a zip path: sign <bundle.zip> --key <keyfile.json>');
  if (!keyPath) fail('sign needs --key <keyfile.json> (from keygen)');
  if (!existsSync(zipPath)) fail(`zip not found: ${zipPath}`);

  const key = loadKeyFile(keyPath);
  const privateKey = createPrivateKey({
    key: Buffer.from(key.secret_key_pkcs8, 'base64'), format: 'der', type: 'pkcs8',
  });
  const pubRaw = Buffer.from(key.public_key, 'base64');
  const zipBytes = readFileSync(zipPath);

  const sig = edSign(null, zipBytes, privateKey);
  const envelope = Buffer.concat([MARKER, keyNumFor(pubRaw), sig]);
  const sigB64 = envelope.toString('base64');

  const sigPath = `${zipPath}.minisig`;
  writeFileSync(sigPath, sigB64 + '\n');

  process.stdout.write(`\nSignature written to ${sigPath} (ship it beside the zip as a release asset).\n`);
  process.stdout.write('\nRegistry index fields for this release:\n\n');
  process.stdout.write(`  "signature": "${sigB64}",\n`);
  process.stdout.write(`  "publisher_key_id": "${key.key_id}"\n`);
}

function cmdVerify(argv) {
  const positional = argv.filter((a) => !a.startsWith('--') && a !== argv[argv.indexOf('--key') + 1]);
  const zipPath = positional[0];
  let keyPath = null;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--key') keyPath = argv[++i];
  }
  if (!zipPath) fail('verify needs a zip path: verify <bundle.zip> --key <keyfile.json>');
  if (!keyPath) fail('verify needs --key <keyfile.json> (only its public half is used)');

  const key = loadKeyFile(keyPath);
  const sigPath = `${zipPath}.minisig`;
  if (!existsSync(sigPath)) fail(`signature file not found: ${sigPath}`);
  const blob = Buffer.from(readFileSync(sigPath, 'utf8').trim(), 'base64');
  if (blob.length !== 74 || blob.subarray(0, 2).toString() !== 'ED') {
    fail(`${sigPath} is not a ServerKit ed25519 envelope`);
  }
  const pubRaw = Buffer.from(key.public_key, 'base64');
  if (!blob.subarray(2, 10).equals(keyNumFor(pubRaw))) {
    fail(`signature was made by a different key than ${keyPath}`);
  }
  const publicKey = createPublicKey({
    key: Buffer.concat([
      // SPKI prefix for ed25519 (12 bytes) + raw key
      Buffer.from('302a300506032b6570032100', 'hex'), pubRaw,
    ]),
    format: 'der', type: 'spki',
  });
  const ok = edVerify(null, readFileSync(zipPath), publicKey, blob.subarray(10));
  if (!ok) fail('signature does NOT match the zip bytes (tampered or wrong zip)');
  process.stdout.write(`OK: ${zipPath} verifies with key "${key.key_id}"\n`);
}

const [command, ...rest] = process.argv.slice(2);
if (command === 'keygen') cmdKeygen(rest);
else if (command === 'sign') cmdSign(rest);
else if (command === 'verify') cmdVerify(rest);
else {
  process.stderr.write('usage: sign-extension.mjs <keygen|sign|verify> … (see header comment)\n');
  process.exit(1);
}
