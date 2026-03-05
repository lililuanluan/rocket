import subprocess


def _list_container_names() -> list[str]:
    out = subprocess.check_output(
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        text=True,
    ).strip()
    return [n for n in out.splitlines() if n]


def _remove_containers(names: list[str], quiet: bool = False):
    for name in names:
        try:
            subprocess.run(
                ["docker", "rm", "-f", name],
                check=True,
                stdout=subprocess.DEVNULL if quiet else None,
                stderr=subprocess.DEVNULL if quiet else None,
            )
        except subprocess.CalledProcessError as e:
            if not quiet:
                print(f"Warning: failed to remove {name}: {e}")


def cleanup_instance_docker_containers(instance_id):
    """清理特定实例的容器（validator + key_generator）

    Args:
        instance_id: 实例 ID（也就是 cluster_id）
    """
    try:
        instance_id_str = str(instance_id)
        names = _list_container_names()
        matched = [
            n
            for n in names
            if n.startswith(f"{instance_id_str}_validator_")
            or n == f"{instance_id_str}_key_generator"
        ]
        _remove_containers(matched, quiet=True)
    except FileNotFoundError:
        pass
    except subprocess.CalledProcessError:
        pass
