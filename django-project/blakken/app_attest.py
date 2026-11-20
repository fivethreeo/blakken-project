import base64
import hashlib
import io
import time
from dataclasses import dataclass
from pathlib import Path

import cbor2
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ObjectIdentifier


ROOT_CERTIFICATE = Path(__file__).with_name('certs') / 'apple_app_attest_root.pem'
NONCE_EXTENSION = ObjectIdentifier('1.2.840.113635.100.8.2')
PRODUCTION_AAGUID = b'appattest' + b'\x00' * 7
OFFICIAL_VALIDATION_CATEGORIES = (2, 4)


class InvalidAppAttest(ValueError):
    pass


@dataclass(frozen=True)
class AttestationResult:
    public_key: str
    counter: int
    bundle_version: str
    validation_category: int


def assertion_client_data_hash(challenge, request_hash, appid, menu_id):
    client_data = (
        f'POST\n{appid}\n{menu_id}\n'.encode()
        + challenge
        + bytes.fromhex(request_hash)
    )
    return hashlib.sha256(client_data).digest()


def _decode_cbor(data):
    stream = io.BytesIO(data)
    try:
        value = cbor2.CBORDecoder(stream).decode()
    except (cbor2.CBORDecodeError, ValueError) as error:
        raise InvalidAppAttest('Invalid CBOR data.') from error
    if stream.read(1):
        raise InvalidAppAttest('Unexpected trailing CBOR data.')
    return value


def _read_cbor(data, offset):
    stream = io.BytesIO(data)
    stream.seek(offset)
    try:
        value = cbor2.CBORDecoder(stream).decode()
    except (cbor2.CBORDecodeError, ValueError) as error:
        raise InvalidAppAttest('Invalid authenticator data.') from error
    return value, stream.tell()


def _verify_certificate_signature(certificate, issuer):
    public_key = issuer.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise InvalidAppAttest('Unexpected App Attest certificate key type.')
    try:
        public_key.verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            ec.ECDSA(certificate.signature_hash_algorithm),
        )
    except InvalidSignature as error:
        raise InvalidAppAttest('Invalid App Attest certificate signature.') from error


def _der_octet_string(value):
    if len(value) < 4 or value[0] != 0x30:
        raise InvalidAppAttest('Invalid nonce extension.')

    def read_length(data, offset):
        if offset >= len(data):
            raise InvalidAppAttest('Invalid nonce extension length.')
        first = data[offset]
        if first < 0x80:
            return first, offset + 1
        count = first & 0x7F
        if count == 0 or count > 4 or offset + 1 + count > len(data):
            raise InvalidAppAttest('Invalid nonce extension length.')
        length = int.from_bytes(data[offset + 1:offset + 1 + count], 'big')
        return length, offset + 1 + count

    sequence_length, offset = read_length(value, 1)
    if (sequence_length < 4 or offset + sequence_length != len(value) or
            offset >= len(value) or value[offset] != 0xA1):
        raise InvalidAppAttest('Invalid nonce extension sequence.')
    explicit_length, offset = read_length(value, offset + 1)
    if offset + explicit_length != len(value) or value[offset] != 0x04:
        raise InvalidAppAttest('Invalid nonce extension value.')
    octet_length, offset = read_length(value, offset + 1)
    if offset + octet_length != len(value):
        raise InvalidAppAttest('Invalid nonce extension value.')
    return value[offset:]


def _verify_certificate_chain(certificates):
    if (not isinstance(certificates, list) or len(certificates) != 2 or
            not all(isinstance(item, bytes) for item in certificates)):
        raise InvalidAppAttest('Invalid App Attest certificate chain.')
    try:
        leaf, intermediate = [
            x509.load_der_x509_certificate(value) for value in certificates
        ]
        root = x509.load_pem_x509_certificate(ROOT_CERTIFICATE.read_bytes())
    except (ValueError, OSError) as error:
        raise InvalidAppAttest('Invalid App Attest certificate.') from error

    for certificate in (leaf, intermediate, root):
        if certificate.not_valid_before_utc.timestamp() > time.time():
            raise InvalidAppAttest('App Attest certificate is not yet valid.')
        if certificate.not_valid_after_utc.timestamp() < time.time():
            raise InvalidAppAttest('App Attest certificate has expired.')
    if leaf.issuer != intermediate.subject or intermediate.issuer != root.subject:
        raise InvalidAppAttest('Invalid App Attest certificate chain issuers.')

    try:
        if leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise InvalidAppAttest('App Attest credential certificate must not be a CA.')
        if not intermediate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise InvalidAppAttest('App Attest intermediate certificate is not a CA.')
    except x509.ExtensionNotFound as error:
        raise InvalidAppAttest('Missing App Attest certificate constraints.') from error

    _verify_certificate_signature(leaf, intermediate)
    _verify_certificate_signature(intermediate, root)
    return leaf


def _authenticator_data(auth_data, app_id):
    if not isinstance(auth_data, bytes) or len(auth_data) < 37:
        raise InvalidAppAttest('Invalid authenticator data.')
    if auth_data[:32] != hashlib.sha256(app_id.encode()).digest():
        raise InvalidAppAttest('App ID hash mismatch.')
    flags = auth_data[32]
    return flags, int.from_bytes(auth_data[33:37], 'big')


def _extensions(auth_data, offset, flags):
    if offset == len(auth_data):
        if flags & 0x80:
            raise InvalidAppAttest('Missing authenticator extensions.')
        return {}
    if offset > len(auth_data):
        raise InvalidAppAttest('Invalid authenticator data.')
    extensions, end = _read_cbor(auth_data, offset)
    if end != len(auth_data) or not isinstance(extensions, dict):
        raise InvalidAppAttest('Invalid authenticator extensions.')
    return extensions


def _validation_category(extensions):
    value = extensions.get('apple_validation_category_01')
    if isinstance(value, bytes) and len(value) == 4:
        value = int.from_bytes(value, 'little')
    return value


def _attestation_claims(auth_data, app_id):
    flags, counter = _authenticator_data(auth_data, app_id)
    if not flags & 0x40 or len(auth_data) < 55:
        raise InvalidAppAttest('Missing attested credential data.')
    if auth_data[37:53] != PRODUCTION_AAGUID:
        raise InvalidAppAttest('App Attest environment is not production.')
    credential_length = int.from_bytes(auth_data[53:55], 'big')
    credential_end = 55 + credential_length
    if credential_end > len(auth_data):
        raise InvalidAppAttest('Invalid credential identifier.')
    credential_id = auth_data[55:credential_end]
    cose_key, key_end = _read_cbor(auth_data, credential_end)
    if not isinstance(cose_key, dict):
        raise InvalidAppAttest('Invalid credential public key.')
    extensions = _extensions(auth_data, key_end, flags)
    if (cose_key.get(1) != 2 or cose_key.get(3) != -7 or
            cose_key.get(-1) != 1 or not isinstance(cose_key.get(-2), bytes) or
            len(cose_key.get(-2)) != 32 or not isinstance(cose_key.get(-3), bytes) or
            len(cose_key.get(-3)) != 32):
        raise InvalidAppAttest('Unsupported credential public key.')
    try:
        public_numbers = ec.EllipticCurvePublicNumbers(
            int.from_bytes(cose_key[-2], 'big'),
            int.from_bytes(cose_key[-3], 'big'),
            ec.SECP256R1(),
        )
        public_key = public_numbers.public_key()
    except ValueError as error:
        raise InvalidAppAttest('Invalid credential public key.') from error

    category = _validation_category(extensions)
    bundle_version = extensions.get('apple_bundle_version_01')
    if (category not in OFFICIAL_VALIDATION_CATEGORIES or
            not isinstance(bundle_version, str) or not bundle_version):
        raise InvalidAppAttest('Missing official app validation claims.')
    return credential_id, public_key, counter, category, bundle_version


def verify_attestation(attestation_object, key_id, client_data_hash, app_id):
    if not isinstance(client_data_hash, bytes) or len(client_data_hash) != 32:
        raise InvalidAppAttest('Invalid App Attest client data hash.')
    value = _decode_cbor(attestation_object)
    if not isinstance(value, dict) or value.get('fmt') != 'apple-appattest':
        raise InvalidAppAttest('Unsupported App Attest format.')
    statement = value.get('attStmt')
    auth_data = value.get('authData')
    if not isinstance(statement, dict) or not isinstance(auth_data, bytes):
        raise InvalidAppAttest('Invalid App Attest object.')

    credential_id, public_key, counter, category, bundle_version = (
        _attestation_claims(auth_data, app_id)
    )
    if counter != 0:
        raise InvalidAppAttest('Invalid initial assertion counter.')
    try:
        key_id_bytes = base64.b64decode(key_id, validate=True)
    except (ValueError, TypeError) as error:
        raise InvalidAppAttest('Invalid App Attest key identifier.') from error
    if base64.b64encode(key_id_bytes).decode() != key_id:
        raise InvalidAppAttest('Invalid App Attest key identifier.')
    raw_public_key = public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    if (len(key_id_bytes) != 32 or credential_id != key_id_bytes or
            hashlib.sha256(raw_public_key).digest() != key_id_bytes):
        raise InvalidAppAttest('App Attest key identifier mismatch.')

    leaf = _verify_certificate_chain(statement.get('x5c', []))
    try:
        cert_public_key = leaf.public_key()
        nonce_extension = leaf.extensions.get_extension_for_oid(NONCE_EXTENSION).value
    except x509.ExtensionNotFound as error:
        raise InvalidAppAttest('Missing App Attest nonce extension.') from error
    if not isinstance(cert_public_key, ec.EllipticCurvePublicKey):
        raise InvalidAppAttest('Unexpected App Attest credential key type.')
    cert_raw_key = cert_public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    expected_nonce = hashlib.sha256(auth_data + client_data_hash).digest()
    if (cert_raw_key != raw_public_key or
            _der_octet_string(nonce_extension.value) != expected_nonce):
        raise InvalidAppAttest('App Attest credential or nonce mismatch.')

    return AttestationResult(
        public_key=public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode(),
        counter=counter,
        bundle_version=bundle_version,
        validation_category=category,
    )


def verify_assertion(assertion, public_key_pem, app_id, client_data_hash, current_counter):
    if not isinstance(client_data_hash, bytes) or len(client_data_hash) != 32:
        raise InvalidAppAttest('Invalid App Attest client data hash.')
    value = _decode_cbor(assertion)
    if not isinstance(value, dict):
        raise InvalidAppAttest('Invalid App Attest assertion.')
    auth_data = value.get('authenticatorData')
    signature = value.get('signature')
    if not isinstance(auth_data, bytes) or not isinstance(signature, bytes):
        raise InvalidAppAttest('Invalid App Attest assertion fields.')

    flags, counter = _authenticator_data(auth_data, app_id)
    if flags & 0x40 or counter <= current_counter:
        raise InvalidAppAttest('Invalid App Attest assertion counter.')
    extensions = _extensions(auth_data, 37, flags)
    category = _validation_category(extensions)
    bundle_version = extensions.get('apple_bundle_version_01')
    if (category not in OFFICIAL_VALIDATION_CATEGORIES or
            not isinstance(bundle_version, str) or not bundle_version):
        raise InvalidAppAttest('Missing official app validation claims.')

    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode())
        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            raise InvalidAppAttest('Unexpected App Attest credential key type.')
        public_key.verify(
            signature,
            auth_data + client_data_hash,
            ec.ECDSA(hashes.SHA256()),
        )
    except (ValueError, InvalidSignature) as error:
        raise InvalidAppAttest('Invalid App Attest assertion signature.') from error
    return counter, category, bundle_version
