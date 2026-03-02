import subprocess


def cleanup_all_interceptor_processes():
    """清理所有 rocket-interceptor 进程"""
    try:
        print("\n🧹 Cleaning up all rocket-interceptor processes...")
        subprocess.run(
            ["killall", "-9", "rocket-interceptor"],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        print("✓ Cleanup complete")
    except Exception as e:
        print(f"Warning: Could not cleanup processes: {e}")


def cleanup_all_docker_containers():
    """清理所有 validator 容器"""
    try:
        out = subprocess.check_output(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=validator_",
                "--format",
                "{{.Names}}",
            ],
            text=True,
        ).strip()
        if out:
            names = [n for n in out.splitlines() if n]
            for name in names:
                print(f"Stopping and removing container: {name}")
                try:
                    subprocess.run(["docker", "rm", "-f", name], check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Warning: failed to remove {name}: {e}")
    except FileNotFoundError:
        print("docker not found in PATH; skipping validator cleanup")
    except subprocess.CalledProcessError as e:
        print(f"Warning: error while listing validator containers: {e}")


def cleanup_instance_docker_containers(instance_id):
    """清理特定实例的 validator 容器
    
    Args:
        instance_id: 实例 ID，可以是字符串如 "G0T1" 或整数
    """
    try:
        instance_id_str = str(instance_id)
        
        out = subprocess.check_output(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=validator_",
                "--format",
                "{{.Names}}",
            ],
            text=True,
        ).strip()
        if out:
            names = [n for n in out.splitlines() if n]
            for name in names:

                if name.startswith(instance_id_str):
                    try:
                        subprocess.run(["docker", "rm", "-f", name], check=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except subprocess.CalledProcessError:
                        pass
    except Exception:
        pass