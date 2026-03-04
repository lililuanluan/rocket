from pathlib import Path
import subprocess
import re
import argparse
import os
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed

# track running subprocesses globally so we can kill them on SIGINT
running_procs: list[subprocess.Popen] = []

rippled_dir = Path(__file__).parent / "rippled"


def clone_repository_if_not_here():
    # 检测是否存在文件夹

    if not rippled_dir.exists():
        # 执行 git clone git@github.com:lililuanluan/rippled.git
        subprocess.run(
            [
                "git",
                "clone",
                "git@github.com:lililuanluan/rippled.git",
                str(rippled_dir),
            ],
            check=True,
        )


def get_bug_i_branches():
    # 检测rippled目录下所有的 bug{i} 的分支
    result = subprocess.run(
        ["git", "branch", "-r"],
        cwd=rippled_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    branches = result.stdout.splitlines()

    buggy_branches = []
    for branch in branches:
        b = branch.strip()
        if re.match(r"origin/bug\d+$", b):
            buggy_branches.append(b.split("/")[-1])
    return buggy_branches


def generate_dockerfiles(bug_i_branches):
    res = {}  # image name -> dockerfile path
    dockerfile_template = Path(__file__).parent / "Dockerfile.rippled-2.6.0"

    # 生成 Dockerfile，将template中的 RUN git checkout 2.6.0 替换为 RUN git checkout {buggy_branch}，并保存为 Dockerfile.rippled-2.6.0-{buggy_branch}-injected
    for buggy_branch in bug_i_branches:
        image_name = f"xrpld:2.6.0-{buggy_branch}-local"
        docker_file_name = f"Dockerfile.rippled-2.6.0-{buggy_branch}-injected"

        with open(dockerfile_template, "r") as f:
            content = f.read()
        content = content.replace(
            "RUN git checkout 2.6.0", f"RUN git checkout {buggy_branch}"
        )
        new_dockerfile = Path(__file__).parent / docker_file_name
        with open(new_dockerfile, "w") as f:
            f.write(content)
        res[image_name] = docker_file_name
    return res


def generate_makefile(img_dockerfiles):
    makefile_path = Path(__file__).parent / "Makefile"
    with open(makefile_path, "w") as f:
        for img, dockerfile in img_dockerfiles.items():
            f.write(f"{img}: {dockerfile}\n")
            f.write(f"\tdocker build -t {img} -f {dockerfile} .\n\n")


def _run_build_task(args):
    """Top-level helper for ProcessPoolExecutor to execute a docker build.

    Args is a tuple (img, dockerfile, force_flag).
    """
    img, dockerfile, force_flag = args
    print(f"Building {img} with {dockerfile} ...")
    # construct command; when forcing, put --no-cache immediately after 'build'
    cmd = ["docker", "build"]
    if force_flag:
        cmd.append("--no-cache")
    cmd += [
        "-t",
        img,
        "-f",
        dockerfile,
        "--build-arg",
        r"UID=$(id -u)",
        "--build-arg",
        r"GID=$(id -g)",
        ".",
    ]

    # start subprocess in its own process group so we can kill it later
    proc = subprocess.Popen(cmd, preexec_fn=os.setsid)
    running_procs.append(proc)
    try:
        ret = proc.wait()
        if ret != 0:
            raise subprocess.CalledProcessError(ret, cmd)
    finally:
        # remove from list regardless of result
        try:
            running_procs.remove(proc)
        except ValueError:
            pass


# parse command line args to optionally build images
parser = argparse.ArgumentParser(
    description="Generate dockerfiles and optionally build images."
)
parser.add_argument(
    "--build",
    nargs="+",
    metavar="IMAGE",
    help="List of image names to build or 'all' to build everything",
)
parser.add_argument(
    "-f",
    "--force",
    action="store_true",
    help="If set, pass --no-cache to docker build (force rebuild)",
)
args = parser.parse_args()


def build_images(img_dockerfiles, selected, force: bool = False):
    # prepare list of arguments for each build
    to_build = [(t, img_dockerfiles[t], force) for t in selected]

    # execute builds in parallel with a pool of workers
    # imported and running_procs defined at module level

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_run_build_task, args) for args in to_build]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:
                print(f"Build failed: {exc}")
                raise


def main():
    clone_repository_if_not_here()
    bug_i_branches = get_bug_i_branches()
    img_dockerfiles = generate_dockerfiles(bug_i_branches)
    for img, dockerfile in img_dockerfiles.items():
        print(f"Generated Dockerfile {dockerfile} for image {img}")

    # 再增加一些新的镜像
    img_dockerfiles["xrpld:1.4.0-local"] = "Dockerfile.rippled-1.4.0"
    img_dockerfiles["xrpld:1.7.2-local"] = "Dockerfile.rippled-1.7.2"
    img_dockerfiles["xrpld:2.6.0-local"] = "Dockerfile.rippled-2.6.0"

    selected = []
    if args.build is not None:
        # 如果参数是 'all'，则构建所有镜像，否则只构建指定的镜像
        if "all" in args.build:
            selected = list(img_dockerfiles.keys())
        else:
            # 检查是否在 img_dockerfiles 中
            for img in args.build:
                if img not in img_dockerfiles:
                    print(f"Error: Image {img} not found in generated dockerfiles.")
                    return
                selected.append(img)

    if selected:
        try:
            build_images(img_dockerfiles, selected, force=args.force)
        except KeyboardInterrupt:
            print("\nInterrupted by user, terminating ongoing builds...")
            # kill any running docker build subprocesses
            for proc in list(running_procs):
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGTERM)
                except Exception:
                    pass
            raise


if __name__ == "__main__":
    main()
