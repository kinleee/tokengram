// Birdəfəlik yoxlama: setIssuedAt(now-60) exp-ə təsir etmir.
// İcra: node test/iat_backdate_check.mjs  (admin-server qovluğundan)
import { generateKeyPairSync } from 'node:crypto';
import { SignJWT, importPKCS8, jwtVerify, importSPKI, decodeJwt } from 'jose';

const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const privPem = privateKey.export({ type: 'pkcs8', format: 'pem' });
const pubPem = publicKey.export({ type: 'spki', format: 'pem' });

const nowSec = () => Math.floor(Date.now() / 1000);
const ttlSeconds = 3600;
const before = nowSec();

// server.js issueToken ilə eyni zəncir
const pk = await importPKCS8(privPem, 'RS256');
const token = await new SignJWT({ user_id: 'u_test', license_key: 'k', fingerprint: 'fp' })
    .setProtectedHeader({ alg: 'RS256' })
    .setIssuedAt(nowSec() - 60)
    .setExpirationTime(`${ttlSeconds}s`)
    .setIssuer('mla-license-server')
    .sign(pk);

const claims = decodeJwt(token);
const iatDelta = claims.iat - before;          // gözlənti: ≈ -60
const expDelta = claims.exp - before;          // gözlənti: ≈ +3600 (iat-dan asılı DEYİL)

console.log(`iat delta: ${iatDelta}s (gözlənti ≈ -60)`);
console.log(`exp delta: ${expDelta}s (gözlənti ≈ +${ttlSeconds})`);

const iatOk = iatDelta <= -55 && iatDelta >= -65;
const expOk = expDelta >= ttlSeconds - 5 && expDelta <= ttlSeconds + 5;

// imza + issuer hələ də verify olunur
const spki = await importSPKI(pubPem, 'RS256');
await jwtVerify(token, spki, { issuer: 'mla-license-server' });
console.log('jose verify: OK');

if (!iatOk || !expOk) {
    console.error('FAIL: iat/exp gözləntiyə uymur');
    process.exit(1);
}
console.log('PASS');
