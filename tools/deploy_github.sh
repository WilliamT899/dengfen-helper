#!/bin/bash
# 发布到 GitHub：创建公开仓库 + 注册 SSH 密钥 + 推送（api.github.com + ssh.github.com:443 通道）
# 用法: GH_TOKEN=ghp_xxx REPO_NAME=dengfen-helper bash tools/deploy_github.sh
set -euo pipefail

TOKEN="${GH_TOKEN:?请先设置 GH_TOKEN 环境变量}"
REPO="${REPO_NAME:-dengfen-helper}"
API="https://api.github.com"

# 1. 获取当前登录用户名
USER=$(curl -s -H "Authorization: token $TOKEN" "$API/user" | python3 -c "import sys,json; print(json.load(sys.stdin)['login'])")
echo "GitHub 用户: $USER"

# 2. 创建公开仓库（已存在则跳过）
HTTP=$(curl -s -o /tmp/repo_create.json -w "%{http_code}" -X POST "$API/user/repos" \
  -H "Authorization: token $TOKEN" \
  -d "{\"name\":\"$REPO\",\"private\":false,\"auto_init\":false,\"description\":\"登分助手：小学教师试卷登分工具（离线OCR+Excel导出）\"}")
if [ "$HTTP" = "201" ] || [ "$HTTP" = "422" ]; then
  echo "仓库 $REPO 已就绪"
else
  echo "创建仓库失败 (HTTP $HTTP):"; cat /tmp/repo_create.json; exit 1
fi

# 3. 注册 SSH 公钥（用于 ssh.github.com:443 推送）
PUB=$(cat ~/.ssh/id_ed25519_dengfen.pub)
KEY_TITLE="dengfen-deploy-$(hostname)"
curl -s -o /dev/null -X POST "$API/user/keys" \
  -H "Authorization: token $TOKEN" \
  -d "{\"title\":\"$KEY_TITLE\",\"key\":\"$PUB\"}"
echo "SSH 密钥已注册"

# 4. 通过 ssh.github.com:443 推送
cd "$(dirname "$0")/.."
GIT_SSH_COMMAND="ssh -i ~/.ssh/id_ed25519_dengfen -p 443 -o StrictHostKeyChecking=accept-new" \
  git push "ssh://git@ssh.github.com:443/$USER/$REPO.git" main:main 2>&1 | tail -3
echo "推送完成！"
echo "仓库地址: https://github.com/$USER/$REPO"
echo "打包进度: https://github.com/$USER/$REPO/actions"
