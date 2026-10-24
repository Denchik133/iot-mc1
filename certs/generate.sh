#!/bin/sh
set -eu

CERT_DIR="certs"
mkdir -p "$CERT_DIR"

if [ -f "$CERT_DIR/ca.key" ] || [ -f "$CERT_DIR/server.key" ]; then
  echo "Private key already exists. Refusing to overwrite certificates."
  exit 1
fi

openssl genrsa -out "$CERT_DIR/ca.key" 4096
openssl req -x509 -new -nodes \
  -key "$CERT_DIR/ca.key" \
  -sha256 -days 3650 \
  -out "$CERT_DIR/ca.crt" \
  -subj "/CN=IIoT Local Certificate Authority"

openssl genrsa -out "$CERT_DIR/server.key" 2048
openssl req -new \
  -key "$CERT_DIR/server.key" \
  -out "$CERT_DIR/server.csr" \
  -subj "/CN=mosquitto"

cat > "$CERT_DIR/server.ext" <<'EXT'
subjectAltName = DNS:localhost,DNS:mosquitto,IP:127.0.0.1
extendedKeyUsage = serverAuth
keyUsage = digitalSignature,keyEncipherment
EXT

openssl x509 -req \
  -in "$CERT_DIR/server.csr" \
  -CA "$CERT_DIR/ca.crt" \
  -CAkey "$CERT_DIR/ca.key" \
  -CAcreateserial \
  -out "$CERT_DIR/server.crt" \
  -days 825 -sha256 \
  -extfile "$CERT_DIR/server.ext"

chmod 600 "$CERT_DIR/ca.key" "$CERT_DIR/server.key"

echo "Certificates generated in $CERT_DIR/"
