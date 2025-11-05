


# TODOs

[-] 创建一个bin文件夹，存储编译好的interceptor二进制。如果如果配置的ripple镜像有对应的二进制，则直接拷贝到interceptor文件夹下。否则使用rebuild_interceptor.py将二进制拷贝过来。

[-] 在python脚本中运行rocket，管理log文件，指定ledger sequence的长度，iteration的次数

[] 实现transaction

[] 对一次execution写一个hash函数，可以将所有 `<sender, receiver, msgType>` 事件进行排序，然后求哈希。测试reproducability。（现在是不可复现的，即使指定了种子）。

[] 实现byzantine node，从配置文件指定，