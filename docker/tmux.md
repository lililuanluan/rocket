# 用 `tmux` 运行 Rocket

这份说明记录了如何在服务器上用 `tmux` 跑长时间实验。这样即使本地电脑关机、
SSH 断开，服务器上的任务也会继续运行。

## 1. 创建 `tmux` 会话

先登录服务器，然后进入仓库根目录：

```bash
cd /data/home/lli21/rocket
```

创建一个新的 `tmux` 会话：

```bash
tmux new -s rocket
```


## 3. 挂起会话但不停止任务

如果你想退出当前终端，但不停止正在运行的任务，按：

```text
Ctrl+b，然后按 d
```

这样会把 `tmux` 会话挂到后台。之后你可以安全关闭 SSH 窗口，任务仍然会继续跑。

## 4. 之后重新连接

重新登录服务器后，先查看当前有哪些 `tmux` 会话：

```bash
tmux ls
```

重新连接到 `rocket` 会话：

```bash
tmux attach -t rocket
```

如果这个会话已经在别的终端附着，可以强制抢占回来：

```bash
tmux attach -d -t rocket
```
