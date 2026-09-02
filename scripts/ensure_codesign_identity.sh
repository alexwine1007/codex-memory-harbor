#!/bin/zsh
set -euo pipefail

IDENTITY_NAME="${MEMORY_HARBOR_CODESIGN_IDENTITY_NAME:-Memory Harbor Local Code Signing}"
SIGNING_DIR="${MEMORY_HARBOR_SIGNING_DIR:-$HOME/Library/Application Support/Memory Harbor/Signing}"
KEYCHAIN="${MEMORY_HARBOR_CODESIGN_KEYCHAIN:-$SIGNING_DIR/memory-harbor.keychain}"
PASSWORD_FILE="$SIGNING_DIR/keychain-password"

find_identity() {
  /usr/bin/security find-identity -v -p codesigning "$KEYCHAIN" 2>/dev/null \
    | /usr/bin/awk -v needle="\"$IDENTITY_NAME\"" 'index($0, needle) { print $2; exit }'
}

if [[ -n "${MEMORY_HARBOR_CODESIGN_IDENTITY:-}" ]]; then
  if [[ "$MEMORY_HARBOR_CODESIGN_IDENTITY" == "-" ]]; then
    echo "Memory Harbor refuses ad-hoc signing because macOS cannot retain removable-volume permission across builds." >&2
    exit 1
  fi
  echo "$MEMORY_HARBOR_CODESIGN_IDENTITY"
  exit 0
fi

umask 077
mkdir -p "$SIGNING_DIR"
chmod 700 "$SIGNING_DIR"

if [[ -e "$KEYCHAIN" && ! -f "$PASSWORD_FILE" ]]; then
  echo "Memory Harbor's signing keychain exists without its local unlock file: $KEYCHAIN" >&2
  exit 1
fi

if [[ ! -e "$KEYCHAIN" ]]; then
  PASSWORD="$(/usr/bin/openssl rand -hex 24)"
  print -r -- "$PASSWORD" >"$PASSWORD_FILE"
  chmod 600 "$PASSWORD_FILE"
  /usr/bin/security create-keychain -p "$PASSWORD" "$KEYCHAIN"
  /usr/bin/security set-keychain-settings -lut 21600 "$KEYCHAIN"
else
  PASSWORD="$(<"$PASSWORD_FILE")"
fi

/usr/bin/security unlock-keychain -p "$PASSWORD" "$KEYCHAIN"

# codesign only discovers identities in the user search list. Keep this
# dedicated keychain there without changing the user's default keychain.
SEARCH_KEYCHAINS=("${(@f)$(/usr/bin/security list-keychains -d user | /usr/bin/sed -E 's/^[[:space:]]*\"//; s/\"[[:space:]]*$//')}")
if (( ${SEARCH_KEYCHAINS[(Ie)$KEYCHAIN]} == 0 )); then
  /usr/bin/security list-keychains -d user -s "$KEYCHAIN" "${SEARCH_KEYCHAINS[@]}"
fi

IDENTITY_HASH="$(find_identity)"
if [[ -n "$IDENTITY_HASH" ]]; then
  echo "$IDENTITY_HASH"
  exit 0
fi

TEMP_DIR="$(/usr/bin/mktemp -d /tmp/memory-harbor-signing.XXXXXX)"
cleanup() {
  /bin/rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

# A certificate can survive a partially completed first run. Trust it and reuse
# its private key rather than creating a second identity with the same name.
if /usr/bin/security find-certificate -c "$IDENTITY_NAME" -p "$KEYCHAIN" >"$TEMP_DIR/certificate.pem" 2>/dev/null; then
  /usr/bin/security add-trusted-cert -d -r trustRoot -p codeSign -k "$KEYCHAIN" "$TEMP_DIR/certificate.pem" >/dev/null
else
  PASSWORD="$(/usr/bin/openssl rand -hex 24)"
  /usr/bin/openssl req -new -newkey rsa:2048 -x509 -sha256 -days 3650 -nodes \
    -keyout "$TEMP_DIR/private-key.pem" \
    -out "$TEMP_DIR/certificate.pem" \
    -subj "/CN=$IDENTITY_NAME/O=Memory Harbor" \
    -addext 'basicConstraints=critical,CA:TRUE' \
    -addext 'keyUsage=critical,digitalSignature,keyCertSign' \
    -addext 'extendedKeyUsage=codeSigning' >/dev/null 2>&1
  /usr/bin/openssl pkcs12 -export \
    -inkey "$TEMP_DIR/private-key.pem" \
    -in "$TEMP_DIR/certificate.pem" \
    -out "$TEMP_DIR/identity.p12" \
    -passout "pass:$PASSWORD" \
    -name "$IDENTITY_NAME" >/dev/null 2>&1
  /usr/bin/security import "$TEMP_DIR/identity.p12" \
    -k "$KEYCHAIN" -P "$PASSWORD" -T /usr/bin/codesign >/dev/null
  /usr/bin/security add-trusted-cert -d -r trustRoot -p codeSign \
    -k "$KEYCHAIN" "$TEMP_DIR/certificate.pem" >/dev/null
fi

IDENTITY_HASH="$(find_identity)"
if [[ -z "$IDENTITY_HASH" ]]; then
  echo "Unable to create a reusable Memory Harbor code-signing identity in $KEYCHAIN." >&2
  exit 1
fi

echo "Created reusable local code-signing identity: $IDENTITY_NAME" >&2
echo "$IDENTITY_HASH"
