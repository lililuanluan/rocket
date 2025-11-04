import os
from pathlib import Path
import subprocess
import shutil


def rebuild_interceptor_with(
    img, interceptor_dir=Path(__file__).parent.parent / "rocket_interceptor", dest=None
) -> bool:

    file_to_change = interceptor_dir / "src" / "docker_manager.rs"
    backup_file = Path(f"{file_to_change}.back")

    # 创建备份
    if file_to_change.exists() and file_to_change.is_file():
        try:
            content = file_to_change.read_text(encoding="utf-8")
            backup_file.write_text(content, encoding="utf-8")
            print(f"✓ 备份创建成功: {backup_file}")
        except Exception as e:
            print(f"✗ 备份创建失败: {e}")
            return False
    else:
        print(f"✗ 原文件不存在: {file_to_change}")
        return False

    def copy_back():
        """恢复备份文件"""
        try:
            if backup_file.exists():
                shutil.copy2(backup_file, file_to_change)
                print(f"✓ 已恢复备份")
                # 可选：删除备份文件
                # backup_file.unlink()
        except Exception as e:
            print(f"✗ 恢复备份失败: {e}")

    def copy_to_destination():
        if dest is None:
            print("⚠️ 未指定目标目录，跳过拷贝步骤")
            return True
        """拷贝构建产物到目标目录"""
        try:
            # 确保目标目录存在
            dest_path = Path(dest)
            

            # 源文件和目标文件路径
            source_file = interceptor_dir / "rocket-interceptor"
            target_file = dest_path

            if not source_file.exists():
                print(f"❌ 构建产物不存在: {source_file}")
                return False

            # 执行拷贝
            shutil.copy2(source_file, target_file)
            print(f"✅ 成功拷贝构建产物到: {target_file}")
            return True

        except Exception as e:
            print(f"❌ 拷贝文件失败: {e}")
            return False

    old_text = 'const IMAGE: &str = "xrpllabsofficial/xrpld:2.3.0";'
    new_text = f'const IMAGE: &str = "{img}";'

    if old_text in content:
        new_content = content.replace(old_text, new_text)
        file_to_change.write_text(new_content, encoding="utf-8")
        print(f"✓ 镜像版本已更新: {old_text} -> {new_text}")

        # 保存当前目录以便后续恢复
        original_cwd = os.getcwd()
        try:
            os.chdir(interceptor_dir)
            result = subprocess.run(["./build.sh"], capture_output=True, text=True)

            if result.returncode == 0:
                print("✅ 构建成功完成！")
                if result.stdout.strip():
                    print(f"构建输出: {result.stdout}")

                # 拷贝构建产物
                if copy_to_destination():
                    copy_back()
                    return True
                else:
                    copy_back()
                    return False
            else:
                print(f"❌ 构建失败，返回码: {result.returncode}")
                if result.stderr.strip():
                    print(f"错误输出: {result.stderr}")
                copy_back()
                return False

        except Exception as e:
            print(f"❌ 构建过程中发生错误: {e}")
            copy_back()
            return False
        finally:
            # 恢复原始工作目录
            os.chdir(original_cwd)
    else:
        print(f"✗ 未找到目标文本: {old_text}")
        return False


if __name__ == "__main__":
    img = "ghcr.io/amousavigourabi/docker-rippled/seeded-2.4.0-fully-lowered-threshold:latest"
    rebuild_interceptor_with(img=img)
