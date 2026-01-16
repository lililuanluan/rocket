# 笔记～


## TODOs

[-] 创建一个bin文件夹，存储编译好的interceptor二进制。如果如果配置的ripple镜像有对应的二进制，则直接拷贝到interceptor文件夹下。否则使用rebuild_interceptor.py将二进制拷贝过来。

[-] 在python脚本中运行rocket，管理log文件，指定ledger sequence的长度，iteration的次数

[] 实现transaction

[-] 对一次execution写一个hash函数，可以将所有 `<sender, receiver, msgType>` 事件进行排序，然后求哈希。测试reproducability。（现在是不可复现的，即使指定了种子）。

[-] 实现byzantine node，从配置文件指定

[-] 对validation消息进行解析，序列化，测试签名正确性以及round-trip

[-] Skipping byzz mutation: ledger sequence for node 3 not available yet iterationtype的状态记录有问题

[-] 更改spec checker，只检查correct nodes

[] 如果有多个byzz nodes，是否可以共享私钥？

[] 增加transaction提交逻辑，目前是在on_status_change中实现的
[] 把transaction提交用线程执行，在锁区只负责更新 transaction_sent这个集合
[] 现在的提交逻辑是死循环，容易把程序阻塞，需要改。

## 提交jpynb文件
```bash

pip install nbstripout nbdime
# 在仓库安装 nbstripout 钩子（会自动在 git add 前清理 notebook 输出）
nbstripout --install
# 启用 nbdime 的 git 支持（更友好的 notebook diff/merge）
nbdime install --enable --global
```

## rocket interceptor更改

```rust
    /// Downloads the 'isvanloon/rippled-no-sig-check:latest' image from DockerHub.
    ///
    /// # Panics
    /// * If an error occurred while downloading the image.
    async fn download_image(&mut self) {
        // If image already exists locally, skip pulling
        match self.docker.inspect_image(IMAGE).await {
            Ok(_) => {
                info!("Docker image {} already present locally, skip pull", IMAGE);
                return;
            }
            Err(_) => {
                info!("Docker image {} not found locally, pulling...", IMAGE);
            }
        }

        self.docker
            .create_image(
                Some(CreateImageOptions {
                    from_image: IMAGE,
                    ..Default::default()
                }),
                None,
                None,
            )
            .try_collect::<Vec<_>>()
            .await
            .unwrap();
    }

```