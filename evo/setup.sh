#!/bin/bash

cd ..

set -e

export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init --path)"
eval "$(pyenv init -)"

PY_VERSION="3.12.0"

# 检查 3.13.0 是否已安装
if ! pyenv versions | grep -q "$PY_VERSION"; then
  echo "Python $PY_VERSION 未安装，请先运行：pyenv install $PY_VERSION"
  exit 1
fi

pyenv local $PY_VERSION

PYENV_PYTHON="$(pyenv which python3)"

# 如果不存在 .venv，则创建并激活一个新的 Python 虚拟环境；如果已存在则直接激活
if [ ! -d ".venv" ]; then
	python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

pip install -r requirements.txt

docker pull xrpllabsofficial/xrpld:2.3.0

git submodule update --init --recursive

cd rocket_interceptor

# 检测操作系统并安装依赖
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux系统使用apt
    sudo apt install openssl libssl-dev cargo
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS系统使用brew
    brew install openssl rust
else
    echo "不支持的操作系统: $OSTYPE"
    echo "请手动安装 openssl 和 rust/cargo"
    exit 1
fi

./build.sh


# 在Windows上要打开防火墙，用管理员身份打开powershell：
# ndows PowerShell
# 版权所有（C） Microsoft Corporation。保留所有权利。

# 安装最新的 PowerShell，了解新功能和改进！https://aka.ms/PSWindows

# PS C:\Users\33527> netsh int ipv4 set dynamicport tcp start=10000 num=55535
# 确定。

# PS C:\Users\33527> netsh int ipv6 set dynamicport tcp start=10000 num=55535
# 确定。

# PS C:\Users\33527> netsh advfirewall reset
# 确定。

# PS C:\Users\33527> netsh advfirewall firewall add rule name="Allow60000" dir=in action=allow protocol=TCP localport=60000
# 确定。

# PS C:\Users\33527> netsh advfirewall firewall add rule name="Allow60100" dir=in action=allow protocol=TCP localport=60100
# 确定。

# 最后测试：docker run --rm -p 5000:60000 xrpllabsofficial/xrpld:2.3.0
