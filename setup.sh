#!/bin/bash

# 如果不存在.venv，则创建一个新的Python虚拟环境
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

docker pull xrpllabsofficial/xrpld:2.3.0

git submodule update --init --recursive

cd rocket_interceptor

sudo apt install openssl libssl-dev cargo
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
