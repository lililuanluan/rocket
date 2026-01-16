import os
from pathlib import Path
import re
import shutil
import subprocess
import threading


def stream_build(interceptor_dir: Path) -> bool:
    """Run build.sh and stream stdout/stderr."""
    original_cwd = os.getcwd()
    try:
        os.chdir(interceptor_dir)
        print("▶️  正在执行 ./build.sh ...")
        proc = subprocess.Popen(
            ["./build.sh"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        def _stream(pipe, label):
            if not pipe:
                return
            for line in pipe:
                print(f"[{label}] {line.rstrip()}")

        t_out = threading.Thread(target=_stream, args=(proc.stdout, "stdout"))
        t_err = threading.Thread(target=_stream, args=(proc.stderr, "stderr"))
        t_out.start()
        t_err.start()
        proc.wait()
        t_out.join()
        t_err.join()
        if proc.returncode == 0:
            print("✅ 构建成功完成！")
            return True
        print(f"❌ 构建失败，返回码: {proc.returncode}")
        return False
    finally:
        os.chdir(original_cwd)


def copy_to_destination(interceptor_dir: Path, dest: Path | None) -> bool:
    if dest is None:
        print("⚠️ 未指定目标目录，跳过拷贝步骤")
        return True
    try:
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        source_file = interceptor_dir / "rocket-interceptor"
        if not source_file.exists():
            print(f"❌ 构建产物不存在: {source_file}")
            return False
        shutil.copy2(source_file, dest_path)
        print(f"✅ 成功拷贝构建产物到: {dest_path}")
        return True
    except Exception as e:
        print(f"❌ 拷贝文件失败: {e}")
        return False


def rebuild_interceptor_with(
    img: str,
    interceptor_dir: Path = Path(__file__).parent.parent / "rocket_interceptor",
    dest: Path | None = None,
) -> bool:
    # No need to backup since we don't modify source code anymore
    print("✓ Skipping backup as config is external")

    try:
        # Write to config.yaml instead of replacing code
        config_file = interceptor_dir / "config.yaml"
        config_content = f"image: \"{img}\"\n"
        config_file.write_text(config_content, encoding="utf-8")
        print(f"✓ Config updated: {config_file}")

        if not stream_build(interceptor_dir=interceptor_dir):
            return False

        if not copy_to_destination(interceptor_dir, dest):
            return False

        return True

    except Exception as e:
        print(f"❌ 构建过程中发生错误: {e}")
        return False


if __name__ == "__main__":
    img = "xrpllabsofficial/xrpld:3.1.0"
    rebuild_interceptor_with(img=img)
