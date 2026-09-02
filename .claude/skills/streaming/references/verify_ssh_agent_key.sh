#!/usr/bin/env bash

set -euo pipefail

error() { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; }

if [[ $# -ne 1 ]]; then
    error "SSH 秘密鍵パスを 1 つ指定してください"
    exit 2
fi

SSH_KEY_PATH="$1"

command -v ssh-keygen >/dev/null 2>&1 || {
    error "ssh-keygen が見つかりません (openssh-client を導入してください)"
    exit 1
}
command -v ssh-add >/dev/null 2>&1 || {
    error "ssh-add が見つかりません (openssh-client を導入してください)"
    exit 1
}

if [[ ! -f "${SSH_KEY_PATH}.pub" ]]; then
    error "公開鍵が見つかりません: ${SSH_KEY_PATH}.pub"
    error "       生成: ssh-keygen -t ed25519 -f ${SSH_KEY_PATH}"
    exit 1
fi

EXPECTED_FP="$(ssh-keygen -lf "${SSH_KEY_PATH}.pub" 2>/dev/null | awk '{print $2}')"
if [[ -z "$EXPECTED_FP" ]]; then
    error "公開鍵から fingerprint を取得できません: ${SSH_KEY_PATH}.pub"
    exit 1
fi
if ! ssh-add -l 2>/dev/null | grep -qF "$EXPECTED_FP"; then
    error "ssh-agent に ${SSH_KEY_PATH} が登録されていません (fingerprint: ${EXPECTED_FP})"
    error "       登録: ssh-add ${SSH_KEY_PATH}"
    error "       注意: \`ssh -i ${SSH_KEY_PATH}\` で通常 SSH できても agent 登録の確認にはなりません"
    error "             (provisioner は agent = true で接続するため、ssh-add -l 出力のみが真の判定材料)"
    exit 1
fi
